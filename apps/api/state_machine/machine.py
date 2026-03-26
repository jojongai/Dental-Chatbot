"""
WorkflowStateMachine — the core of the chatbot control flow.

Responsibilities
----------------
1. Accept a WorkflowState + a raw user message.
2. Run every relevant field extractor against the message.
3. Update collected_fields and recompute missing_fields.
4. Determine the next action:
     a. Sub-workflow needed (patient not yet verified)
        → switch to EXISTING_PATIENT_VERIFICATION, remember pending workflow
     b. Still collecting fields
        → return the next missing field's prompt
     c. Requires confirmation
        → build a summary and ask "does this look right?"
     d. Ready to call tool
        → set ready_to_call=True, tool_name, tool_input_data
5. Return a MachineResult (fully typed; no LLM involved).

The router then:
  - Sends result.reply to the user
  - If result.ready_to_call: calls the tool and appends the result
  - Persists the updated WorkflowState
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from schemas.chat import ActionType, ChatAction, Workflow, WorkflowState
from state_machine.definitions import FIELDS, WORKFLOWS, FieldDef, WorkflowDef
from state_machine.extractors import extract_confirmation

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class MachineResult:
    """Everything the router needs after one machine turn."""

    state: WorkflowState

    # Text to send back to the user
    reply: str

    # True when the machine has all required fields and is ready to call a tool
    ready_to_call: bool = False

    # Name of the tool to call (matches TOOL_REGISTRY key in schemas/tools.py)
    tool_name: str | None = None

    # Raw dict of collected fields — router builds the typed Pydantic tool input from this
    tool_input_data: dict[str, Any] = field(default_factory=dict)

    # UI hints for the frontend (show slot picker, confirm button, etc.)
    actions: list[ChatAction] = field(default_factory=list)

    # The field currently being asked for (None if ready or just entered workflow)
    next_field: str | None = None

    # Structured debug info (what the machine knows / needs)
    debug: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Keyword-based workflow intent detection
# ---------------------------------------------------------------------------

_INTENT_MAP: list[tuple[list[str], Workflow]] = [
    # Order matters — more specific phrases first
    (
        [
            "emergency",
            "severe pain",
            "broken tooth",
            "cracked tooth",
            "abscess",
            "swollen",
            "knocked out",
            "toothache",
            "bleeding gum",
        ],
        Workflow.EMERGENCY_TRIAGE,
    ),
    (["new patient", "register", "first time", "first visit", "sign up"], Workflow.NEW_PATIENT_REGISTRATION),
    (
        ["reschedule", "move my appointment", "change my appointment", "different time", "different day"],
        Workflow.RESCHEDULE_APPOINTMENT,
    ),
    (["cancel"], Workflow.CANCEL_APPOINTMENT),
    (
        ["family", "kids", "children", "my kid", "spouse", "husband", "wife", "son", "daughter", "partner"],
        Workflow.FAMILY_BOOKING,
    ),
    (
        ["book", "schedule", "appointment", "cleaning", "checkup", "check-up", "exam", "visit", "coming in"],
        Workflow.BOOK_APPOINTMENT,
    ),
    (["speak to", "talk to", "human", "person", "staff", "someone", "representative", "call me"], Workflow.HANDOFF),
]


def detect_intent(message: str, current: WorkflowState) -> Workflow:
    """
    Return the detected workflow.
    If the user is already mid-workflow, stay in it unless they signal a hard pivot.
    """
    if current.workflow not in (Workflow.GENERAL_INQUIRY,):
        # Allow escape hatches mid-workflow
        lower = message.lower()
        if any(k in lower for k in ("start over", "cancel everything", "different question")):
            return Workflow.GENERAL_INQUIRY
        return current.workflow  # stay in current workflow

    lower = message.lower()
    for keywords, workflow in _INTENT_MAP:
        if any(k in lower for k in keywords):
            return workflow
    return Workflow.GENERAL_INQUIRY


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class WorkflowStateMachine:
    def __init__(self, state: WorkflowState) -> None:
        self.state = state

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process(self, message: str) -> MachineResult:
        """
        Process one user message turn.
        Returns a MachineResult describing what to reply and whether a tool is ready.
        """
        # 1. Detect / confirm workflow
        workflow = detect_intent(message, self.state)
        wf_def = WORKFLOWS[workflow]

        # Handle sub-workflow: if this workflow needs patient_id and we don't have one,
        # pivot to EXISTING_PATIENT_VERIFICATION and remember where to return.
        if wf_def.requires_patient_id and not self.state.patient_id:
            # Store the intended workflow so we resume after verification
            new_state = self.state.model_copy(
                update={
                    "workflow": Workflow.EXISTING_PATIENT_VERIFICATION,
                    "collected_fields": {
                        **self.state.collected_fields,
                        "_pending_workflow": workflow.value,
                    },
                    "missing_fields": list(WORKFLOWS[Workflow.EXISTING_PATIENT_VERIFICATION].required_fields),
                    "step": "verify_identity",
                }
            )
            wf_def = WORKFLOWS[Workflow.EXISTING_PATIENT_VERIFICATION]
            workflow = Workflow.EXISTING_PATIENT_VERIFICATION
            self.state = new_state

        # 2. First turn: greet and set workflow
        is_first_turn = self.state.workflow == Workflow.GENERAL_INQUIRY and workflow != Workflow.GENERAL_INQUIRY
        if is_first_turn or self.state.step == "start":
            self.state = self.state.model_copy(
                update={
                    "workflow": workflow,
                    "step": "collecting",
                }
            )

        # 3. Extract fields from this message
        self.state = self._extract_fields(message, wf_def)

        # 4. Compute what's still missing
        missing = self._compute_missing(wf_def)
        self.state = self.state.model_copy(update={"missing_fields": missing})

        # 5. Dispatch to the right next action
        if workflow == Workflow.GENERAL_INQUIRY:
            return self._reply_general_inquiry(wf_def)

        if missing:
            return self._ask_next_field(missing[0], wf_def, is_first_turn)

        # All required fields present — confirmation or tool call
        if wf_def.requires_confirmation and self.state.step != "confirmed":
            return self._ask_confirmation(wf_def)

        # Handle confirmation response
        if self.state.step == "awaiting_confirmation":
            confirmed = extract_confirmation(message)
            if confirmed is False:
                return self._handle_confirmation_rejected(wf_def)
            if confirmed is None:
                return MachineResult(
                    state=self.state,
                    reply="I didn't catch that — should I go ahead? (yes / no)",
                    actions=[ChatAction(type=ActionType.REQUEST_INFO, payload={"fields": ["confirmation"]})],
                    next_field="confirmation",
                )

        return self._signal_ready(wf_def)

    # ------------------------------------------------------------------
    # Field extraction
    # ------------------------------------------------------------------

    def _extract_fields(self, message: str, wf_def: WorkflowDef) -> WorkflowState:
        """
        Run extractors for every field that is either required or optional in this
        workflow and not yet collected. Returns an updated WorkflowState.
        """
        collected = dict(self.state.collected_fields)
        all_fields = list(wf_def.required_fields) + list(wf_def.optional_fields)

        for field_key in all_fields:
            if field_key in collected:
                continue  # already have this

            field_def: FieldDef | None = FIELDS.get(field_key)
            if not field_def:
                continue

            extractor = field_def.extractor  # type: ignore[attr-defined]
            try:
                value = extractor(message)
            except Exception:
                continue

            if value is None:
                continue

            if field_def.multi_key and isinstance(value, dict):
                collected.update(value)
            else:
                collected[field_key] = value

        return self.state.model_copy(update={"collected_fields": collected})

    # ------------------------------------------------------------------
    # Missing field computation
    # ------------------------------------------------------------------

    def _compute_missing(self, wf_def: WorkflowDef) -> list[str]:
        """
        Return required fields that are not yet in collected_fields.
        Fields that are multi_key may map to multiple collected keys —
        e.g. 'first_name' definition covers both first_name and last_name.
        """
        collected = self.state.collected_fields
        missing: list[str] = []

        for field_key in wf_def.required_fields:
            field_def = FIELDS.get(field_key)
            if field_def and field_def.multi_key:
                # multi_key: satisfied when *all* produced sub-keys are present
                # For full_name this means first_name + last_name
                if field_key == "first_name":
                    if "first_name" not in collected or "last_name" not in collected:
                        missing.append(field_key)
                else:
                    if field_key not in collected:
                        missing.append(field_key)
            else:
                if field_key not in collected:
                    missing.append(field_key)

        return missing

    # ------------------------------------------------------------------
    # Reply builders
    # ------------------------------------------------------------------

    def _ask_next_field(self, next_field: str, wf_def: WorkflowDef, is_first_turn: bool) -> MachineResult:
        field_def = FIELDS.get(next_field)
        prompt = field_def.prompt if field_def else f"Could you provide your {next_field.replace('_', ' ')}?"

        if is_first_turn and wf_def.greeting:
            reply = f"{wf_def.greeting}\n\n{prompt}"
        else:
            reply = prompt

        return MachineResult(
            state=self.state.model_copy(update={"step": f"collecting:{next_field}"}),
            reply=reply,
            ready_to_call=False,
            next_field=next_field,
            actions=[
                ChatAction(
                    type=ActionType.REQUEST_INFO,
                    payload={"field": next_field, "display_name": field_def.display_name if field_def else next_field},
                )
            ],
            debug=self._debug_snapshot(wf_def),
        )

    def _ask_confirmation(self, wf_def: WorkflowDef) -> MachineResult:
        summary = self._build_summary()
        reply = (
            f"{wf_def.ready_message}\n\n{summary}\n\n"
            "Does everything look correct? (yes to confirm / no to change something)"
        )
        return MachineResult(
            state=self.state.model_copy(update={"step": "awaiting_confirmation"}),
            reply=reply,
            ready_to_call=False,
            next_field="confirmation",
            actions=[ChatAction(type=ActionType.CONFIRM_BOOKING, payload={"summary": summary})],
            debug=self._debug_snapshot(wf_def),
        )

    def _handle_confirmation_rejected(self, wf_def: WorkflowDef) -> MachineResult:
        """User said 'no' to confirmation — ask what they'd like to change."""
        return MachineResult(
            state=self.state.model_copy(update={"step": "collecting"}),
            reply="No problem! What would you like to change?",
            ready_to_call=False,
            actions=[],
            debug=self._debug_snapshot(wf_def),
        )

    def _signal_ready(self, wf_def: WorkflowDef) -> MachineResult:
        """All required fields collected and confirmed — ready to call the tool."""
        ready_reply = wf_def.ready_message or "I have everything I need — one moment…"

        # Emergency: add an explicit "staff notified" message
        if wf_def.workflow == Workflow.EMERGENCY_TRIAGE:
            ready_reply = (
                "I've received your details and our dental team has been notified about "
                "your emergency. They will call you back as soon as possible.\n\n"
                "If this is a life-threatening emergency, please call 911 immediately."
            )
            actions = [ChatAction(type=ActionType.ESCALATE_TO_STAFF, payload={"reason": "emergency"})]
        elif wf_def.workflow == Workflow.HANDOFF:
            ready_reply = "I've passed your information to our team. A staff member will call you back shortly."
            actions = [ChatAction(type=ActionType.ESCALATE_TO_STAFF, payload={"reason": "requested_by_patient"})]
        elif wf_def.tool_name == "search_slots":
            actions = [ChatAction(type=ActionType.SHOW_SLOTS, payload={})]
        else:
            actions = []

        return MachineResult(
            state=self.state.model_copy(update={"step": "ready"}),
            reply=ready_reply,
            ready_to_call=True,
            tool_name=wf_def.tool_name,
            tool_input_data=dict(self.state.collected_fields),
            actions=actions,
            debug=self._debug_snapshot(wf_def),
        )

    def _reply_general_inquiry(self, wf_def: WorkflowDef) -> MachineResult:
        """General inquiry: immediately signal tool call so router can fetch clinic info."""
        return MachineResult(
            state=self.state.model_copy(update={"step": "ready"}),
            reply=wf_def.greeting,
            ready_to_call=True,
            tool_name="get_clinic_info",
            tool_input_data={"category": None},
            actions=[],
            debug=self._debug_snapshot(wf_def),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_summary(self) -> str:
        """Build a human-readable summary of collected fields."""
        cf = self.state.collected_fields
        lines: list[str] = []

        def _fmt(key: str, label: str) -> None:
            val = cf.get(key)
            if val is not None:
                val_str = val.strftime("%B %d, %Y") if isinstance(val, date) else str(val)
                lines.append(f"• **{label}**: {val_str}")

        _fmt("first_name", "First name")
        _fmt("last_name", "Last name")
        _fmt("phone_number", "Phone")
        _fmt("date_of_birth", "Date of birth")
        _fmt("insurance_name", "Insurance")
        _fmt("appointment_type", "Appointment type")
        _fmt("preferred_date_from", "Preferred date")
        _fmt("preferred_time_of_day", "Preferred time")
        _fmt("emergency_summary", "Emergency description")
        _fmt("cancel_reason", "Cancellation reason")
        _fmt("family_count", "Family members")
        _fmt("group_preference", "Scheduling preference")

        return "\n".join(lines) if lines else "(no details collected yet)"

    def _debug_snapshot(self, wf_def: WorkflowDef) -> dict:
        """Return a debug-friendly view of current machine state."""
        return {
            "workflow": self.state.workflow,
            "step": self.state.step,
            "collected": list(self.state.collected_fields.keys()),
            "missing": self.state.missing_fields,
            "tool": wf_def.tool_name,
            "requires_patient_id": wf_def.requires_patient_id,
        }


# ---------------------------------------------------------------------------
# Convenience: snapshot for the /chat endpoint debug header
# ---------------------------------------------------------------------------


def machine_status(state: WorkflowState) -> dict:
    """
    Return a concise status dict for logging / debugging without processing a message.
    Useful for staff dashboard: what does the machine know and what does it still need?
    """
    if state.workflow not in WORKFLOWS:
        return {"workflow": state.workflow, "status": "unknown"}

    wf_def = WORKFLOWS[state.workflow]
    required = wf_def.required_fields
    missing = [f for f in required if f not in state.collected_fields]

    return {
        "workflow": state.workflow,
        "display_name": wf_def.display_name,
        "step": state.step,
        "collected_fields": {k: v for k, v in state.collected_fields.items() if not k.startswith("_")},
        "missing_fields": missing,
        "required_fields": required,
        "optional_fields": wf_def.optional_fields,
        "ready_to_call_tool": len(missing) == 0,
        "tool_name": wf_def.tool_name,
        "patient_id": state.patient_id,
    }
