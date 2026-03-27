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

# Workflows that need the "Are you a new or existing patient?" question
# before pivoting to verification or new-patient registration.
# Cancel / reschedule skip this — they require an existing chart; go straight to verification.
_PATIENT_TYPE_GATED = frozenset({
    Workflow.BOOK_APPOINTMENT,
    Workflow.FAMILY_BOOKING,
})

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

# Verbal pivots while mid-flow — also used to refresh the same workflow when the user repeats intent.
_MIDFLOW_OVERRIDE_PHRASES: tuple[tuple[str, Workflow], ...] = (
    ("actually i want to cancel", Workflow.CANCEL_APPOINTMENT),
    ("actually cancel", Workflow.CANCEL_APPOINTMENT),
    ("i need to cancel instead", Workflow.CANCEL_APPOINTMENT),
    ("actually i want to reschedule", Workflow.RESCHEDULE_APPOINTMENT),
    ("actually reschedule", Workflow.RESCHEDULE_APPOINTMENT),
    ("i need to reschedule instead", Workflow.RESCHEDULE_APPOINTMENT),
    ("actually i want to book", Workflow.BOOK_APPOINTMENT),
    ("actually book", Workflow.BOOK_APPOINTMENT),
    ("speak to someone", Workflow.HANDOFF),
    ("talk to a person", Workflow.HANDOFF),
    ("talk to someone", Workflow.HANDOFF),
    ("speak to a human", Workflow.HANDOFF),
)


def midflow_override_target(message: str) -> Workflow | None:
    """If ``message`` matches a mid-flow pivot phrase, return that workflow; else None."""
    lower = message.lower()
    for phrase, target in _MIDFLOW_OVERRIDE_PHRASES:
        if phrase in lower:
            return target
    return None


def detect_intent(message: str, current: WorkflowState) -> Workflow:
    """
    Return the detected workflow for this message.

    Mid-workflow guard runs first — once a workflow is active the machine stays
    in it unless the user explicitly asks to start over. This guard is purely
    deterministic and never calls the LLM.

    For new conversations (workflow == GENERAL_INQUIRY) intent classification
    is delegated to llm/intent.py, which uses Gemini when USE_LLM=true and
    falls back to keyword matching otherwise.

    After new-patient FAQ (``last_clinic_category == \"new_patient\"``), a reply to
    \"Would you like to register now?\" is interpreted via ``interpret_registration_followup``
    (LLM when USE_LLM=true; keyword confirmation fallback when not).
    """
    if current.workflow not in (Workflow.GENERAL_INQUIRY,):
        lower = message.lower()

        # Explicit reset phrases → back to general inquiry
        if any(k in lower for k in ("start over", "cancel everything", "different question")):
            return Workflow.GENERAL_INQUIRY

        # After a failed lookup the bot offers "would you like to register?"
        if current.collected_fields.get("_lookup_failed_offer_registration"):
            _reg_phrases = ("register", "new patient", "sign up", "yes", "yeah", "yep", "sure", "ok", "okay")
            if any(p in lower for p in _reg_phrases):
                return Workflow.NEW_PATIENT_REGISTRATION

        # Allow mid-flow workflow switches for clear intent changes.
        # Emergency always takes priority (the guardrail in process() also handles this,
        # but we let detect_intent cooperate so the flow is clean).
        if _is_emergency(lower) and current.workflow != Workflow.EMERGENCY_TRIAGE:
            return Workflow.EMERGENCY_TRIAGE

        # "Actually I want to X instead" — clear verbal pivot (same target as current is handled in process()).
        pivot = midflow_override_target(message)
        if pivot is not None:
            return pivot

        return current.workflow  # stay in current workflow

    if current.last_clinic_category == "new_patient":
        from llm.interpreter import interpret_registration_followup

        out = interpret_registration_followup(message)
        if _registration_followup_agrees_to_register(out):
            return Workflow.NEW_PATIENT_REGISTRATION

    from llm.intent import classify_intent

    return classify_intent(message)


def _registration_followup_agrees_to_register(out: Any) -> bool:
    """True when the interpreter says the patient agreed to start new-patient registration."""
    pi = (out.primary_intent or "").strip().lower().replace("-", "_")
    conf = float(out.confidence or 0)
    if pi == "general_inquiry":
        return False
    if pi == "new_patient_registration" and conf >= 0.45:
        return True
    if out.extracted_fields.get("confirmation") is True and pi in ("new_patient_registration", ""):
        return conf >= 0.45
    return False


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def compute_missing_fields(workflow: Workflow, collected: dict[str, Any]) -> list[str]:
    """Return required field keys not yet satisfied for ``workflow``."""
    wf_def = WORKFLOWS[workflow]
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


class WorkflowStateMachine:
    def __init__(self, state: WorkflowState) -> None:
        self.state = state

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    _MAX_RECURSION_DEPTH = 3

    def process(self, message: str, _depth: int = 0) -> MachineResult:
        """
        Process one user message turn.
        Returns a MachineResult describing what to reply and whether a tool is ready.
        """
        if _depth >= self._MAX_RECURSION_DEPTH:
            logger.error("process() recursion depth exceeded (%d); returning safe fallback", _depth)
            return MachineResult(
                state=self.state,
                reply="Something went wrong on our end. Please try again or call (416) 555-0100.",
            )

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
            return self.process(message, _depth=_depth + 1)

        # 2. Detect / confirm workflow (opening turn or mid-flow guard)
        original_workflow = self.state.workflow
        workflow = detect_intent(message, self.state)
        wf_def = WORKFLOWS[workflow]

        # 2a. Same-workflow pivot: user repeats "actually I want to cancel" while stuck in cancel, etc.
        pivot_wf = midflow_override_target(message)
        if (
            pivot_wf is not None
            and pivot_wf == workflow == self.state.workflow
            and self.state.workflow != Workflow.GENERAL_INQUIRY
        ):
            self.state = self.state.model_copy(
                update={
                    "step": "collecting",
                    "collected_fields": _carry_forward_fields(self.state.collected_fields),
                    "missing_fields": [],
                    "appointment_id": None,
                    "appointment_options": [],
                    "slot_options": [],
                    "selected_slot_id": None,
                }
            )

        # 2b. Workflow sync: if detect_intent returned a different workflow
        #     (e.g. failed-lookup → NEW_PATIENT_REGISTRATION), reset state.
        if workflow != self.state.workflow and self.state.workflow != Workflow.GENERAL_INQUIRY:
            self.state = self.state.model_copy(
                update={
                    "workflow": workflow,
                    "step": "start",
                    "collected_fields": _strip_identity_for_new_registration(self.state.collected_fields)
                    if workflow == Workflow.NEW_PATIENT_REGISTRATION
                    else _carry_forward_fields(self.state.collected_fields),
                    "missing_fields": [],
                }
            )

        # 2c. Patient-type gate: ask "new or existing?" before verification pivot.
        #     Also handles returning from the gate when step == awaiting_patient_type.
        gate_result = self._patient_type_gate(message, workflow, wf_def)
        if gate_result is not None:
            return gate_result
        # After the gate, workflow/wf_def may have been updated by the gate.
        workflow = self.state.workflow if self.state.step == "verify_identity" else workflow
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
        #    Use original_workflow (captured before pivot) so the greeting fires
        #    even when the pivot already changed self.state.workflow.
        is_first_turn = original_workflow == Workflow.GENERAL_INQUIRY and workflow != Workflow.GENERAL_INQUIRY
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
                    return self.process(message, _depth=_depth + 1)

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
            return self.process(message, _depth=_depth + 1)

        # 7.5 Family booking — multi-person collection (not driven by required_fields)
        if self.state.workflow == Workflow.FAMILY_BOOKING and self.state.patient_id:
            from state_machine.family_booking import run_family_booking_turn

            fb_result = run_family_booking_turn(self, message, wf_def, is_first_turn, interp)
            if fb_result is not None:
                return fb_result

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
        elif self.state.step == "awaiting_family_slot_confirmation":
            pending_field = "confirmation"
            pending_question = (
                "Maya listed specific appointment times for each family member and asked whether "
                "to go ahead and reserve those times."
            )
        elif self.state.step == "family:awaiting_member_confirm":
            pending_field = "confirmation"
            pending_question = (
                "Maya listed each family member’s name, relation, patient status, and visit type "
                "and asked whether that’s correct before scheduling dates and times."
            )

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

        from state_machine.extractors import (
            extract_full_name,
            is_false_positive_name_pair,
            merge_extracted_name_into_collected,
        )

        # Merge fields from interpreter (semantic fields)
        for k, v in interp.extracted_fields.items():
            if v is None:
                continue
            fd = FIELDS.get(k)
            if fd and fd.multi_key and isinstance(v, dict):
                if k == "first_name":
                    merge_extracted_name_into_collected(collected, v)
                    logger.debug("Interpreter extracted first_name multi_key → %r", v)
                else:
                    for sub_k, sub_v in v.items():
                        if sub_k not in collected and sub_v is not None:
                            collected[sub_k] = sub_v
                            logger.debug("Interpreter extracted %r = %r (multi_key)", sub_k, sub_v)
            elif k not in collected:
                collected[k] = v
                logger.debug("Interpreter extracted %r = %r", k, v)

        # Deterministic override: regex is authoritative for phone, DOB, email.
        # Phone: always re-run regex even if the LLM filled a bogus value (e.g. pain "6" as phone).
        for field_key in _DETERMINISTIC_FIELDS:
            if field_key in collected and field_key != "phone_number":
                continue
            fd = FIELDS.get(field_key)
            if fd and fd.extractor:
                try:
                    val = fd.extractor(message)  # type: ignore[call-arg]
                    if val is not None:
                        collected[field_key] = val
                except Exception:
                    pass

        if "phone_number" in collected:
            from tools.validators import normalize_phone

            try:
                collected["phone_number"] = normalize_phone(str(collected["phone_number"]).strip())
            except ValueError:
                collected.pop("phone_number", None)

        # Resolve preferred_date_from: the LLM often returns raw text ("next week",
        # "tomorrow") instead of a date object — run the regex extractor to convert.
        pdf = collected.get("preferred_date_from")
        if isinstance(pdf, str):
            from state_machine.extractors import extract_preferred_date
            parsed = extract_preferred_date(pdf)
            if parsed is not None:
                collected["preferred_date_from"] = parsed

        # Deterministic full name (overwrites bogus pairs like Cancel/Appointment from intent text).
        merge_extracted_name_into_collected(collected, extract_full_name(message))
        if is_false_positive_name_pair(collected.get("first_name"), collected.get("last_name")):
            collected.pop("first_name", None)
            collected.pop("last_name", None)

        return self.state.model_copy(update={"collected_fields": collected}), interp

    # ------------------------------------------------------------------
    # Missing field computation
    # ------------------------------------------------------------------

    def _compute_missing(self, wf_def: WorkflowDef) -> list[str]:
        return compute_missing_fields(wf_def.workflow, self.state.collected_fields)

    # ------------------------------------------------------------------
    # Reply builders
    # ------------------------------------------------------------------

    _REASK_HINTS: dict[str, str] = {
        "phone_number": (
            "That doesn't look like a valid phone number. "
            "Please enter a 10-digit number, e.g. 416-555-1234."
        ),
        "date_of_birth": (
            "I couldn't read that date. "
            "Try a format like March 14, 1990 or 03/14/1990."
        ),
        "preferred_date_from": (
            "I couldn't read that date. "
            "Try something like next Monday, April 5, or tomorrow."
        ),
        "email": (
            "That doesn't look like a valid email. "
            "Please enter an address like name@example.com."
        ),
    }

    def _ask_next_field(self, next_field: str, wf_def: WorkflowDef, is_first_turn: bool) -> MachineResult:
        field_def = FIELDS.get(next_field)
        prompt = (
            wf_def.prompt_overrides.get(next_field)
            or (field_def.prompt if field_def else f"Could you provide your {next_field.replace('_', ' ')}?")
        )

        is_reask = self.state.step == f"collecting:{next_field}"
        if is_reask and not is_first_turn:
            hint = self._REASK_HINTS.get(next_field)
            if hint:
                prompt = hint

        if is_first_turn and wf_def.greeting:
            if wf_def.greeting.rstrip().endswith("?"):
                reply = wf_def.greeting
            else:
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
        if wf_def.workflow == Workflow.CANCEL_APPOINTMENT:
            summary = self._build_cancel_confirmation_summary()
        else:
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
        next_step = (
            "family:scheduling:preference"
            if wf_def.workflow == Workflow.FAMILY_BOOKING
            else "collecting"
        )
        return MachineResult(
            state=self.state.model_copy(update={"step": next_step}),
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
        from tools.validators import display_name_for_appointment_type

        cf = self.state.collected_fields
        lines: list[str] = []

        def _fmt(key: str, label: str) -> None:
            val = cf.get(key)
            if val is not None:
                val_str = val.strftime("%B %d, %Y") if isinstance(val, date) else str(val)
                lines.append(f"• **{label}**: {val_str}")

        def _fmt_appt_type(key: str, label: str) -> None:
            val = cf.get(key)
            if val is not None:
                lines.append(f"• **{label}**: {display_name_for_appointment_type(str(val))}")

        _fmt("first_name", "First name")
        _fmt("last_name", "Last name")
        _fmt("phone_number", "Phone")
        _fmt("date_of_birth", "Date of birth")
        _fmt("insurance_name", "Insurance")
        _fmt_appt_type("appointment_type", "Appointment type")
        _fmt("preferred_date_from", "Preferred date")
        _fmt("preferred_time_of_day", "Preferred time")
        _fmt("emergency_summary", "Emergency description")
        _fmt("cancel_reason", "Cancellation reason")
        _fmt("family_count", "Family members")
        _fmt("group_preference", "Scheduling preference")

        return "\n".join(lines) if lines else "(no details collected yet)"

    def _build_cancel_confirmation_summary(self) -> str:
        """Cancel flow: show patient name + selected appointment date/time + reason (no phone)."""
        from state_machine.extractors import is_false_positive_name_pair

        cf = self.state.collected_fields
        verified = (cf.get("_verified_patient_name") or "").strip()
        fn = (cf.get("first_name") or "").strip()
        ln = (cf.get("last_name") or "").strip()
        if is_false_positive_name_pair(fn, ln):
            fn, ln = "", ""
        typed = f"{fn} {ln}".strip()
        # Typed name wins when present (user correction). Chart name from lookup when
        # cancel-reason / LLM noise wiped or spoofed first+last (e.g. "Scheduling Issue").
        if typed:
            name = typed
        elif verified:
            name = verified
        else:
            name = "—"
        date_l = (cf.get("_cancel_appointment_date_label") or "").strip() or "—"
        time_l = (cf.get("_cancel_appointment_time_label") or "").strip() or "—"
        reason = cf.get("cancel_reason")
        if isinstance(reason, date):
            reason_str = reason.strftime("%B %d, %Y")
        else:
            reason_str = str(reason).strip() if reason is not None else "—"
        line = (cf.get("_cancel_appointment_line") or "").strip()
        if date_l == "—" and time_l == "—" and line:
            return (
                f"• **Name**: {name}\n"
                f"• **Appointment**: {line}\n"
                f"• **Reason**: {reason_str}"
            )
        return (
            f"• **Name**: {name}\n"
            f"• **Date**: {date_l}\n"
            f"• **Time**: {time_l}\n"
            f"• **Reason**: {reason_str}"
        )

    def _build_family_booking_summary(self) -> str:
        from state_machine.family_booking import family_booking_summary_markdown

        return family_booking_summary_markdown(dict(self.state.collected_fields))

    def _debug_snapshot(self, wf_def: WorkflowDef) -> dict:
        return {
            "workflow": self.state.workflow,
            "step": self.state.step,
            "collected": list(self.state.collected_fields.keys()),
            "missing": self.state.missing_fields,
            "tool": wf_def.tool_name,
            "requires_patient_id": wf_def.requires_patient_id,
        }

    # ------------------------------------------------------------------
    # Patient-type gate
    # ------------------------------------------------------------------

    def _patient_type_gate(
        self, message: str, workflow: Workflow, wf_def: WorkflowDef
    ) -> MachineResult | None:
        """
        Ask "Are you a new or existing patient?" for booking-related workflows
        before pivoting to verification or new-patient registration.

        Returns a MachineResult when the gate handles the turn (either asking
        the question or processing the answer).  Returns None when the gate
        does not apply and process() should continue normally.
        """
        from state_machine.extractors import parse_booking_patient_type

        # --- Entry: first time hitting a gated workflow without patient_id ---
        if (
            workflow in _PATIENT_TYPE_GATED
            and not self.state.patient_id
            and self.state.step not in ("awaiting_patient_type", "verify_identity")
            and self.state.workflow != workflow  # only on fresh intent, not mid-flow
        ):
            self.state = self.state.model_copy(
                update={
                    "workflow": workflow,
                    "step": "awaiting_patient_type",
                    "collected_fields": {
                        **self.state.collected_fields,
                        "_pending_workflow": workflow.value,
                    },
                    "missing_fields": [],
                }
            )
            return MachineResult(
                state=self.state,
                reply=(
                    "Sure, I can help with that! Before we get started "
                    "— are you a new or existing patient?"
                ),
                actions=[ChatAction(type=ActionType.REQUEST_INFO, payload={"field": "patient_type"})],
                debug=self._debug_snapshot(wf_def),
            )

        # --- Reply: user answered the "new or existing?" question ---
        if self.state.step == "awaiting_patient_type":
            patient_type = parse_booking_patient_type(message)

            if patient_type == "new":
                self.state = self.state.model_copy(
                    update={
                        "workflow": Workflow.NEW_PATIENT_REGISTRATION,
                        "step": "collecting",
                        "collected_fields": _strip_identity_for_new_registration(
                            self.state.collected_fields
                        ),
                        "missing_fields": list(WORKFLOWS[Workflow.NEW_PATIENT_REGISTRATION].required_fields),
                    }
                )
                new_wf_def = WORKFLOWS[Workflow.NEW_PATIENT_REGISTRATION]
                missing = self._compute_missing(new_wf_def)
                return self._ask_next_field(missing[0], new_wf_def, is_first_turn=True)

            if patient_type == "existing":
                self.state = self.state.model_copy(
                    update={
                        "workflow": Workflow.EXISTING_PATIENT_VERIFICATION,
                        "step": "verify_identity",
                        "missing_fields": list(
                            WORKFLOWS[Workflow.EXISTING_PATIENT_VERIFICATION].required_fields
                        ),
                    }
                )
                ver_wf_def = WORKFLOWS[Workflow.EXISTING_PATIENT_VERIFICATION]
                missing = self._compute_missing(ver_wf_def)
                return self._ask_next_field(missing[0], ver_wf_def, is_first_turn=True)

            # Unclear reply — ask again
            return MachineResult(
                state=self.state,
                reply="Sorry, I didn't catch that — are you a new patient or have you been here before?",
                actions=[ChatAction(type=ActionType.REQUEST_INFO, payload={"field": "patient_type"})],
                debug=self._debug_snapshot(wf_def),
            )

        return None


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
    keep = {"first_name", "last_name", "phone_number", "_verified_patient_name"}
    return {k: v for k, v in collected.items() if k in keep}


def _strip_identity_for_new_registration(collected: dict[str, Any]) -> dict[str, Any]:
    """Remove identity + internal keys when switching from failed lookup to new-patient registration."""
    drop = {"first_name", "last_name", "phone_number", "email"}
    return {k: v for k, v in collected.items() if k not in drop and not k.startswith("_")}


_NEGATION_PREFIXES = ("not ", "no ", "isn't ", "isnt ", "isn't ", "not an ", "no need", "don't ", "dont ")


def _is_emergency(message: str) -> bool:
    """
    Deterministic guardrail that fires on obvious safety-related phrases.
    Intentionally conservative — only phrases that unambiguously signal a
    dental emergency or safety concern.  Runs before the LLM so that no
    urgent patient is ever misrouted by an incorrect LLM classification.

    Ignores negated phrases like "not urgent", "not an emergency".
    """
    lower = message.lower()
    for phrase in _EMERGENCY_PHRASES:
        idx = lower.find(phrase)
        if idx == -1:
            continue
        # Check for a negation word immediately before the matched phrase
        prefix = lower[:idx].rstrip()
        if any(prefix.endswith(neg.rstrip()) for neg in _NEGATION_PREFIXES):
            continue
        return True
    return False


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
