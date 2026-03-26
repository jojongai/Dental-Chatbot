"""
WorkflowStateMachine — the core of the chatbot control flow.

Responsibilities
----------------
1. Accept a WorkflowState + a raw user message.
2. Call the LLM interpreter once to understand the message (extract fields,
   detect topic switches, detect escalation signals).
3. Run deterministic regex extractors for high-confidence fields (phone, email,
   DOB, confirmation) as an authoritative override pass.
4. Update collected_fields and recompute missing_fields.
5. Determine the next action:
     a. Sub-workflow needed (patient not yet verified)
        → switch to EXISTING_PATIENT_VERIFICATION, remember pending workflow
     b. Topic switch detected
        → reset to the new workflow
     c. Escalation requested
        → hand off to HANDOFF workflow
     d. Still collecting fields
        → return the next missing field's prompt
     e. Requires confirmation
        → build a summary and ask "does this look right?"
     f. Ready to call tool
        → set ready_to_call=True, tool_name, tool_input_data
6. Return a MachineResult (fully typed; no direct LLM tool calls here).

The router then:
  - Sends result.reply to the user
  - If result.ready_to_call: calls the tool and appends the result
  - Persists the updated WorkflowState

Architecture note
-----------------
Language understanding lives entirely in llm/interpreter.py (InterpreterOutput).
This file owns only deterministic workflow logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from llm.interpreter import WorkflowTransition
from schemas.chat import ActionType, ChatAction, Workflow, WorkflowState
from state_machine.definitions import FIELDS, WORKFLOWS, FieldDef, WorkflowDef

logger = logging.getLogger(__name__)

# Fields where regex is the authoritative source — always run after interpreter.
# These are too structurally strict for the LLM to handle reliably.
_DETERMINISTIC_FIELDS = frozenset({"phone_number", "date_of_birth", "email"})

# ---------------------------------------------------------------------------
# Emergency safety guardrail — deterministic, runs before the LLM
# ---------------------------------------------------------------------------
# These phrases indicate a potential dental emergency regardless of what the
# LLM concludes.  The guardrail fires independently as a backstop so that
# no patient describing a serious situation is ever missed because the LLM
# classified it differently.
_EMERGENCY_PHRASES = frozenset({
    "severe pain", "a lot of pain", "so much pain", "unbearable pain",
    "swollen", "swelling", "my face is",
    "bleeding", "blood",
    "knocked out", "knocked-out", "tooth fell out", "tooth came out",
    "broken tooth", "broke my tooth", "cracked tooth",
    "abscess", "infection", "pus",
    "trouble breathing", "can't breathe", "hard to breathe",
    "trauma", "hit my mouth", "hit in the mouth", "accident",
    "emergency", "urgent", "asap", "as soon as possible",
    "i'm in pain", "im in pain", "in a lot of pain",
})

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
# Workflow intent detection (opening turn / mid-flow guard)
# ---------------------------------------------------------------------------


def detect_intent(message: str, current: WorkflowState) -> Workflow:
    """
    Return the detected workflow for this message.

    Mid-workflow guard runs first — once a workflow is active the machine stays
    in it unless the user explicitly asks to start over. This guard is purely
    deterministic and never calls the LLM.

    For new conversations (workflow == GENERAL_INQUIRY) intent classification
    is delegated to llm/intent.py, which uses Gemini when USE_LLM=true and
    falls back to keyword matching otherwise.
    """
    if current.workflow not in (Workflow.GENERAL_INQUIRY,):
        lower = message.lower()
        if any(k in lower for k in ("start over", "cancel everything", "different question")):
            return Workflow.GENERAL_INQUIRY
        return current.workflow  # stay in current workflow

    from llm.intent import classify_intent

    return classify_intent(message)


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
        # 1. Emergency safety guardrail — deterministic, runs before everything else.
        #    Fires on obvious safety phrases regardless of LLM classification.
        if (
            self.state.workflow != Workflow.EMERGENCY_TRIAGE
            and _is_emergency(message)
        ):
            logger.warning("Emergency guardrail fired for message: %r", message[:80])
            self.state = self.state.model_copy(
                update={
                    "workflow": Workflow.EMERGENCY_TRIAGE,
                    "step": "start",
                    "collected_fields": _carry_forward_fields(self.state.collected_fields),
                    "missing_fields": [],
                }
            )
            return self.process(message)

        # 2. Detect / confirm workflow (opening turn or mid-flow guard)
        workflow = detect_intent(message, self.state)
        wf_def = WORKFLOWS[workflow]

        # Handle sub-workflow: if this workflow needs patient_id and we don't have one,
        # pivot to EXISTING_PATIENT_VERIFICATION and remember where to return.
        if wf_def.requires_patient_id and not self.state.patient_id:
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

        # 3. First turn: set workflow and step
        is_first_turn = self.state.workflow == Workflow.GENERAL_INQUIRY and workflow != Workflow.GENERAL_INQUIRY
        if is_first_turn or self.state.step == "start":
            self.state = self.state.model_copy(
                update={
                    "workflow": workflow,
                    "step": "collecting",
                }
            )

        # 4. Interpret the message (LLM or keyword fallback) + extract fields
        self.state, interp = self._extract_fields(message, wf_def)

        # 5. Log interpreter output for observability
        _log_interpreter_turn(message, self.state, interp)

        # 6. Handle workflow transition signals from interpreter.
        #
        #    SWITCH  — user clearly wants a different workflow; reset only when
        #              confidence is high AND the new intent is materially different.
        #    BRANCH  — side question while staying in current workflow; log only.
        #    CONTINUE — no action needed.
        if interp.workflow_transition == WorkflowTransition.SWITCH:
            if (
                interp.primary_intent
                and interp.primary_intent != self.state.workflow
                and interp.confidence >= 0.75
            ):
                new_workflow = _safe_workflow(interp.primary_intent)
                if new_workflow and new_workflow != Workflow.GENERAL_INQUIRY:
                    logger.info(
                        "Workflow SWITCH: %s → %s (confidence=%.2f, reason=%r)",
                        self.state.workflow,
                        new_workflow,
                        interp.confidence,
                        interp.reasoning_summary,
                    )
                    self.state = self.state.model_copy(
                        update={
                            "workflow": new_workflow,
                            "step": "start",
                            "collected_fields": _carry_forward_fields(self.state.collected_fields),
                            "missing_fields": [],
                        }
                    )
                    return self.process(message)

        elif interp.workflow_transition == WorkflowTransition.BRANCH:
            logger.info(
                "Workflow BRANCH detected in %s (reason=%r) — continuing current workflow",
                self.state.workflow,
                interp.reasoning_summary,
            )
            # Do NOT reset; the current workflow continues after this turn.

        # 7. Handle escalation request (LLM signal — guardrail already handled
        #    obvious phrases above).
        if interp.should_escalate and self.state.workflow not in (
            Workflow.HANDOFF, Workflow.EMERGENCY_TRIAGE
        ):
            logger.info("Escalation requested by interpreter (reason=%r)", interp.reasoning_summary)
            self.state = self.state.model_copy(
                update={
                    "workflow": Workflow.HANDOFF,
                    "step": "start",
                    "collected_fields": _carry_forward_fields(self.state.collected_fields),
                    "missing_fields": [],
                }
            )
            return self.process(message)

        # 8. Compute what's still missing
        missing = self._compute_missing(wf_def)
        self.state = self.state.model_copy(update={"missing_fields": missing})

        # 9. Dispatch to the right next action
        if workflow == Workflow.GENERAL_INQUIRY:
            return self._reply_general_inquiry(wf_def)

        if missing:
            return self._ask_next_field(missing[0], wf_def, is_first_turn)

        # If we already showed the summary and are waiting for a yes/no, handle that first.
        if self.state.step == "awaiting_confirmation":
            from state_machine.extractors import extract_confirmation

            # Regex is authoritative for confirmation (narrow parser).
            # Fall back to interpreter's extracted value for natural language
            # ("yeah that should be fine", "works for me", "let's do it").
            confirmed = extract_confirmation(message)
            if confirmed is None:
                confirmed = interp.extracted_fields.get("confirmation")

            if confirmed is True:
                return self._signal_ready(wf_def)
            if confirmed is False:
                return self._handle_confirmation_rejected(wf_def)
            return MachineResult(
                state=self.state,
                reply="I didn't catch that — should I go ahead?",
                actions=[ChatAction(type=ActionType.REQUEST_INFO, payload={"fields": ["confirmation"]})],
                next_field="confirmation",
            )

        # All required fields present — show confirmation summary if needed
        if wf_def.requires_confirmation:
            return self._ask_confirmation(wf_def)

        return self._signal_ready(wf_def)

    # ------------------------------------------------------------------
    # Field extraction — interpreter-first, deterministic override
    # ------------------------------------------------------------------

    def _extract_fields(
        self, message: str, wf_def: WorkflowDef
    ) -> tuple[WorkflowState, Any]:
        """
        Extract fields from the user message using the LLM interpreter (or its
        keyword fallback), then apply deterministic regex extractors for
        phone_number, date_of_birth, and email as an authoritative override.

        Returns (updated_state, InterpreterOutput).
        """
        from llm.interpreter import InterpreterInput, InterpreterOutput, build_field_hints, interpret

        pending_field: str | None = None
        pending_question: str | None = None
        if self.state.step.startswith("collecting:"):
            pending_field = self.state.step.split(":", 1)[1]
            fd = FIELDS.get(pending_field)
            pending_question = fd.prompt if fd else None

        clean_collected = {
            k: v for k, v in self.state.collected_fields.items() if not k.startswith("_")
        }

        inp = InterpreterInput(
            message=message,
            workflow=self.state.workflow,
            step=self.state.step,
            pending_field=pending_field,
            pending_question=pending_question,
            collected_fields=clean_collected,
            missing_field_hints=build_field_hints(wf_def, self.state.collected_fields),
        )
        interp: InterpreterOutput = interpret(inp)

        collected = dict(self.state.collected_fields)

        # Merge fields from interpreter (semantic fields)
        for k, v in interp.extracted_fields.items():
            if k not in collected and v is not None:
                # first_name interpreter result may be a plain string — handle multi_key
                fd = FIELDS.get(k)
                if fd and fd.multi_key and isinstance(v, dict):
                    collected.update(v)
                else:
                    collected[k] = v
                logger.debug("Interpreter extracted %r = %r", k, v)

        # Deterministic override: regex is authoritative for phone, DOB, email
        for field_key in _DETERMINISTIC_FIELDS:
            if field_key in collected:
                continue
            fd = FIELDS.get(field_key)
            if fd and fd.extractor:
                try:
                    val = fd.extractor(message)  # type: ignore[call-arg]
                    if val is not None:
                        collected[field_key] = val
                except Exception:
                    pass

        # Always attempt name extraction via deterministic regex (useful when
        # the user provides name + phone in the same message)
        if "first_name" not in collected or "last_name" not in collected:
            fd = FIELDS.get("first_name")
            if fd and fd.extractor:
                try:
                    val = fd.extractor(message)  # type: ignore[call-arg]
                    if val is not None and isinstance(val, dict):
                        if "first_name" not in collected:
                            collected.update(val)
                except Exception:
                    pass

        return self.state.model_copy(update={"collected_fields": collected}), interp

    # ------------------------------------------------------------------
    # Missing field computation
    # ------------------------------------------------------------------

    def _compute_missing(self, wf_def: WorkflowDef) -> list[str]:
        """
        Return required fields that are not yet in collected_fields.
        """
        collected = self.state.collected_fields
        missing: list[str] = []

        for field_key in wf_def.required_fields:
            field_def = FIELDS.get(field_key)
            if field_def and field_def.multi_key:
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
                    payload={
                        "field": next_field,
                        "display_name": field_def.display_name if field_def else next_field,
                    },
                )
            ],
            debug=self._debug_snapshot(wf_def),
        )

    def _ask_confirmation(self, wf_def: WorkflowDef) -> MachineResult:
        summary = self._build_summary()
        reply = f"{wf_def.ready_message}\n\n{summary}\n\nDoes everything look correct?"
        return MachineResult(
            state=self.state.model_copy(update={"step": "awaiting_confirmation"}),
            reply=reply,
            ready_to_call=False,
            next_field="confirmation",
            actions=[ChatAction(type=ActionType.CONFIRM_BOOKING, payload={"summary": summary})],
            debug=self._debug_snapshot(wf_def),
        )

    def _handle_confirmation_rejected(self, wf_def: WorkflowDef) -> MachineResult:
        return MachineResult(
            state=self.state.model_copy(update={"step": "collecting"}),
            reply="No problem! What would you like to change?",
            ready_to_call=False,
            actions=[],
            debug=self._debug_snapshot(wf_def),
        )

    def _signal_ready(self, wf_def: WorkflowDef) -> MachineResult:
        ready_reply = wf_def.ready_message or "I have everything I need — one moment…"

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

        # Strip internal sentinel keys before passing to tool
        tool_data = {
            k: v for k, v in self.state.collected_fields.items() if not k.startswith("_")
        }

        return MachineResult(
            state=self.state.model_copy(update={"step": "ready"}),
            reply=ready_reply,
            ready_to_call=True,
            tool_name=wf_def.tool_name,
            tool_input_data=tool_data,
            actions=actions,
            debug=self._debug_snapshot(wf_def),
        )

    def _reply_general_inquiry(self, wf_def: WorkflowDef) -> MachineResult:
        return MachineResult(
            state=self.state.model_copy(update={"step": "ready"}),
            reply=wf_def.greeting,
            ready_to_call=True,
            tool_name="get_clinic_info",
            tool_input_data={"category": None},
            actions=[],
            debug=self._debug_snapshot(wf_def),
        )

    def _signal_handoff(self) -> MachineResult:
        """Fast path when interpreter flags an escalation request."""
        wf_def = WORKFLOWS[Workflow.HANDOFF]
        self.state = self.state.model_copy(
            update={"workflow": Workflow.HANDOFF, "step": "start"}
        )
        return self._ask_next_field("phone_number", wf_def, is_first_turn=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_summary(self) -> str:
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
        return {
            "workflow": self.state.workflow,
            "step": self.state.step,
            "collected": list(self.state.collected_fields.keys()),
            "missing": self.state.missing_fields,
            "tool": wf_def.tool_name,
            "requires_patient_id": wf_def.requires_patient_id,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_workflow(label: str) -> Workflow | None:
    try:
        return Workflow(label)
    except ValueError:
        return None


def _carry_forward_fields(collected: dict[str, Any]) -> dict[str, Any]:
    """Keep name and phone when switching workflows — avoids re-asking."""
    keep = {"first_name", "last_name", "phone_number"}
    return {k: v for k, v in collected.items() if k in keep}


def _is_emergency(message: str) -> bool:
    """
    Deterministic guardrail that fires on obvious safety-related phrases.
    Intentionally conservative — only phrases that unambiguously signal a
    dental emergency or safety concern.  Runs before the LLM so that no
    urgent patient is ever misrouted by an incorrect LLM classification.
    """
    lower = message.lower()
    return any(phrase in lower for phrase in _EMERGENCY_PHRASES)


def _log_interpreter_turn(
    message: str,
    state: WorkflowState,
    interp: Any,
) -> None:
    """
    Emit a structured DEBUG log line per turn so failures are easy to diagnose.
    Enabled at DEBUG level; zero cost in production at INFO/WARNING.
    """
    if not logger.isEnabledFor(logging.DEBUG):
        return

    pending_field: str | None = None
    if state.step.startswith("collecting:"):
        pending_field = state.step.split(":", 1)[1]

    logger.debug(
        "interpreter_turn | workflow=%s step=%s pending=%s "
        "transition=%s escalate=%s confidence=%.2f "
        "extracted=%r answered=%r uncertain=%r "
        "message=%r reasoning=%r",
        state.workflow,
        state.step,
        pending_field,
        interp.workflow_transition,
        interp.should_escalate,
        interp.confidence,
        interp.extracted_fields,
        interp.answered_fields,
        interp.uncertain_fields,
        message[:120],
        interp.reasoning_summary,
    )


# ---------------------------------------------------------------------------
# Convenience: snapshot for the /chat endpoint debug header
# ---------------------------------------------------------------------------


def machine_status(state: WorkflowState) -> dict:
    """
    Return a concise status dict for logging / debugging without processing a message.
    """
    if state.workflow not in WORKFLOWS:
        return {"workflow": state.workflow, "status": "unknown"}

    wf_def = WORKFLOWS[state.workflow]
    required = wf_def.required_fields
    collected = state.collected_fields

    missing: list[str] = []
    for f in required:
        fd = FIELDS.get(f)
        if fd and fd.multi_key and f == "first_name":
            if "first_name" not in collected or "last_name" not in collected:
                missing.append(f)
        elif f not in collected:
            missing.append(f)

    return {
        "workflow": state.workflow,
        "display_name": wf_def.display_name,
        "step": state.step,
        "collected_fields": {k: v for k, v in collected.items() if not k.startswith("_")},
        "missing_fields": missing,
        "required_fields": required,
        "optional_fields": wf_def.optional_fields,
        "ready_to_call_tool": len(missing) == 0,
        "tool_name": wf_def.tool_name,
        "patient_id": state.patient_id,
    }
