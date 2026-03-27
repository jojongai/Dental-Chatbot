"""
LLM-based conversation interpreter.

This is the single point where language understanding happens.
It is called ONCE per turn and returns a structured InterpreterOutput that the
WorkflowStateMachine uses to update conversation state.

Responsibilities
----------------
- Extract ALL pending semantic fields from the user's message in one shot.
- Detect whether the user is answering the current question, adding a side
  question, or genuinely switching to a different workflow.
- Flag messages that should be escalated to a human.
- Provide a reasoning summary and field-level confidence hints for debugging.

What this module does NOT do
-----------------------------
- Make booking decisions.
- Call any tools or modify the database.
- Determine what to say next (that is the workflow engine's job).

WorkflowTransition semantics
------------------------------
  CONTINUE  — user is clearly still in the current workflow
  BRANCH    — user asked a quick side question but is coming back
              (e.g. "do you take Sun Life? and also I need a cleaning")
              The machine logs this but does NOT reset the workflow.
  SWITCH    — user clearly wants to start a materially different workflow
              (e.g. "actually I want to cancel, not book")
              Machine resets ONLY when confidence >= 0.75.

Fallback (USE_LLM=false)
------------------------
_keyword_interpret() produces the same InterpreterOutput shape using the regex
extractors from extractors.py. All tests run on this path.

Swapping LLM providers
-----------------------
Replace _call_llm() below. Everything else is provider-agnostic.
"""

from __future__ import annotations

import json
import logging
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class WorkflowTransition(StrEnum):
    """How the user's intent relates to the current workflow."""

    CONTINUE = "continue"  # staying in current workflow
    BRANCH = "branch"      # side question; return to current workflow after
    SWITCH = "switch"      # materially different workflow requested


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FieldHint(BaseModel):
    """Description of a single field fed into the interpreter prompt."""

    key: str
    display_name: str
    description: str


class InterpreterInput(BaseModel):
    """Everything the interpreter needs to understand one message turn."""

    message: str
    workflow: str
    step: str
    # The specific field we asked for in the last bot message (if any).
    pending_field: str | None = None
    # The exact text of the last question shown to the user.
    pending_question: str | None = None
    # Fields already collected (cleaned — no internal _ keys).
    collected_fields: dict[str, Any] = Field(default_factory=dict)
    # Descriptions for fields still needed; drives the extraction prompt.
    missing_field_hints: list[FieldHint] = Field(default_factory=list)


class InterpreterOutput(BaseModel):
    """
    Structured interpretation of one user message turn.

    All decisions remain in the workflow engine — this output only describes
    what the user *said*, not what should happen next.
    """

    # ---------- intent & flow ----------
    # Detected workflow intent (or None if continuing the current one).
    primary_intent: str | None = None
    # How this message relates to the current workflow.
    workflow_transition: WorkflowTransition = WorkflowTransition.CONTINUE
    # Confidence in primary_intent / workflow_transition (0.0–1.0).
    confidence: float = 1.0
    # True when the message directly answers the question that was pending.
    is_answering_pending_question: bool = True

    # ---------- extracted data ----------
    # Fields extracted from this message (key → value, may be partial).
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    # Fields the interpreter is confident it answered correctly.
    answered_fields: list[str] = Field(default_factory=list)
    # Fields where the interpreter found something but is not certain of the value.
    uncertain_fields: list[str] = Field(default_factory=list)

    # ---------- routing signals ----------
    # True when the user requests a human agent or the situation is urgent.
    should_escalate: bool = False
    # Short label describing the suggested next step (informational only).
    suggested_next_action: str | None = None

    # ---------- debug ----------
    # Brief LLM reasoning for logging and diagnosis.
    reasoning_summary: str | None = None


# ---------------------------------------------------------------------------
# Fast-path gate — decides whether the LLM is needed for this turn
# ---------------------------------------------------------------------------

# Fields whose values are fully determined by tight regex — LLM adds no value
# and may actually be less reliable (e.g. formatting edge cases for phone/DOB).
_STRUCTURAL_FIELDS = frozenset({"phone_number", "date_of_birth", "email", "confirmation"})

# Slot choice: a single digit 1–5, optionally surrounded by whitespace
_SLOT_CHOICE_RE = re.compile(r"^\s*[1-5]\s*$")


def _needs_llm(inp: InterpreterInput) -> bool:
    """
    Return True only when the LLM is actually needed for this turn.

    Returns False (fast-path, skip LLM) when ANY of the following hold:

    1. Pending field is structural (phone, DOB, email, confirmation) —
       regex handles these with higher reliability than the LLM.
    2. Message looks like a slot choice (single digit 1-5).
    3. All remaining missing fields are structural — nothing semantic to
       extract regardless of what the LLM might say.
    4. First turn of a new workflow with no missing fields yet — the
       message was purely an intent trigger (e.g. "Yep, looking to book");
       classify_intent() already handled routing and there is nothing
       to extract.

    The LLM is still called for genuinely ambiguous or mixed messages
    such as "I'm not insured and next Tuesday works" or
    "Actually I wanted to ask about coverage before booking".
    """
    m = inp.message.strip()

    # Open-ended replies to proposed family slots — prefer LLM over yes/no regex.
    if inp.step == "awaiting_family_slot_confirmation":
        return True

    # Rule 1 — pending field is deterministic
    if inp.pending_field in _STRUCTURAL_FIELDS:
        return False

    # Rule 2 — slot choice (numeric answer to a presented list)
    if _SLOT_CHOICE_RE.match(m):
        return False

    # Rule 3 — every pending hint is structural; nothing semantic to extract
    if inp.missing_field_hints:
        has_semantic = any(h.key not in _STRUCTURAL_FIELDS for h in inp.missing_field_hints)
        if not has_semantic:
            return False

    # Rule 4 — first turn of a new workflow; no fields collected yet and
    # no hints because the workflow just started.  The message was already
    # routed by classify_intent() and contains only an intent trigger.
    if not inp.missing_field_hints and inp.step in ("collecting", "start", "verify_identity"):
        return False

    # Rule 5 — existing-patient verification: classify_intent() already picked the workflow;
    # name/phone are filled by _keyword_interpret + regex overrides in the machine.
    # The LLM sees the original intent phrase (e.g. "I'd like to book an appointment") and
    # returns SWITCH → book_appointment, causing infinite recursion.
    if inp.step == "verify_identity":
        return False

    # Rule 6 — new vs returning gate: keyword parser only.
    if inp.step == "awaiting_patient_type":
        return False

    return True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def interpret_registration_followup(message: str) -> InterpreterOutput:
    """
    Interpret a reply to \"Would you like to register now?\" after new-patient FAQ.

    Always uses the LLM when USE_LLM=true (bypasses the _needs_llm fast-path).
    Falls back to extract_confirmation when USE_LLM=false or on API failure.
    """
    inp = InterpreterInput(
        message=message,
        workflow="general_inquiry",
        step="awaiting_registration_followup",
        pending_field=None,
        pending_question=(
            "Would you like to register now? (You can complete registration in this chat.)"
        ),
        collected_fields={},
        missing_field_hints=[],
    )
    try:
        from config import get_settings

        if not get_settings().use_llm:
            return _keyword_registration_followup(inp)

        raw = _call_llm(inp)
        return _parse_llm_response(raw, inp)
    except Exception as exc:
        logger.warning("interpret_registration_followup failed (%s) — keyword fallback", exc)
        return _keyword_registration_followup(inp)


def _keyword_registration_followup(inp: InterpreterInput) -> InterpreterOutput:
    """USE_LLM=false / API failure: same yes/no signal as before, structured as InterpreterOutput."""
    from state_machine.extractors import extract_confirmation

    c = extract_confirmation(inp.message)
    if c is True:
        return InterpreterOutput(
            primary_intent="new_patient_registration",
            workflow_transition=WorkflowTransition.SWITCH,
            confidence=0.85,
            is_answering_pending_question=True,
            extracted_fields={"confirmation": True},
            answered_fields=["confirmation"],
            uncertain_fields=[],
            should_escalate=False,
            suggested_next_action="start_new_patient_registration",
            reasoning_summary="keyword fallback: affirmative to register",
        )
    if c is False:
        return InterpreterOutput(
            primary_intent="general_inquiry",
            workflow_transition=WorkflowTransition.CONTINUE,
            confidence=0.85,
            is_answering_pending_question=True,
            extracted_fields={"confirmation": False},
            answered_fields=["confirmation"],
            uncertain_fields=[],
            should_escalate=False,
            suggested_next_action=None,
            reasoning_summary="keyword fallback: declined registration for now",
        )
    return InterpreterOutput(
        primary_intent=None,
        workflow_transition=WorkflowTransition.CONTINUE,
        confidence=0.3,
        is_answering_pending_question=False,
        extracted_fields={},
        answered_fields=[],
        uncertain_fields=[],
        should_escalate=False,
        suggested_next_action=None,
        reasoning_summary="keyword fallback: unclear reply to registration offer",
    )


def interpret(inp: InterpreterInput) -> InterpreterOutput:
    """
    Interpret a user message and return structured output.

    Decision order:
      1. If USE_LLM=false  → keyword/regex path always.
      2. If _needs_llm() is False → fast-path (keyword/regex, no API call).
      3. Otherwise → Gemini API call.
      4. On API failure → fall back to keyword/regex.

    Never raises.
    """
    try:
        from config import get_settings

        if not get_settings().use_llm:
            return _keyword_interpret(inp)

        if not _needs_llm(inp):
            logger.debug("fast-path interpreter: skipping LLM for %r", inp.message[:60])
            return _keyword_interpret(inp)

        raw = _call_llm(inp)
        return _parse_llm_response(raw, inp)

    except Exception as exc:
        logger.warning("Interpreter LLM call failed (%s) — falling back to keyword path", exc)
        return _keyword_interpret(inp)


def build_field_hints(wf_def: Any, collected_fields: dict[str, Any]) -> list[FieldHint]:
    """
    Build FieldHint objects for every field still needed by the workflow.
    Called by the machine to populate InterpreterInput.missing_field_hints.
    """
    from state_machine.definitions import FIELDS

    hints: list[FieldHint] = []
    all_field_keys = list(wf_def.required_fields) + list(wf_def.optional_fields)
    for key in all_field_keys:
        if key in collected_fields:
            continue
        fd = FIELDS.get(key)
        if fd:
            hints.append(FieldHint(key=fd.key, display_name=fd.display_name, description=fd.description))
    return hints


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a conversation interpreter for a dental-office SMS chatbot called Maya.
Your ONLY job is to analyse a patient's message and return a structured JSON object.
You do NOT decide what to say next. You do NOT book appointments. You only interpret language.

Return ONLY valid JSON matching this exact schema — no explanation, no markdown fences:
{
  "primary_intent": "<workflow label or null>",
  "workflow_transition": "<continue | branch | switch>",
  "confidence": <0.0-1.0>,
  "is_answering_pending_question": <true/false>,
  "extracted_fields": { "<field_key>": <value>, ... },
  "answered_fields": ["<key>", ...],
  "uncertain_fields": ["<key>", ...],
  "should_escalate": <true/false>,
  "suggested_next_action": "<short label or null>",
  "reasoning_summary": "<1-2 sentence explanation of your interpretation>"
}

Valid workflow labels for primary_intent:
  new_patient_registration, book_appointment, reschedule_appointment,
  cancel_appointment, emergency_triage, family_booking, handoff, general_inquiry

workflow_transition rules:
  "continue" — user is clearly still in the current workflow
  "branch"   — user asked a quick side question while staying in the current workflow
               (e.g. "do you take Sun Life? and also I need a cleaning next week")
  "switch"   — user clearly wants to start a materially different workflow
               (e.g. "actually forget the booking, I need to cancel instead")
  Only use "switch" when the new intent is BOTH clear AND materially different from current.
  A side question or additional info is always "branch" or "continue", never "switch".

should_escalate rules:
  true only when the user explicitly asks for a human, OR describes a dental emergency
  (severe pain, swelling, trauma, bleeding, knocked-out tooth, trouble breathing).

For extracted_fields:
  Include ONLY fields listed in the "Fields to extract" section.
  Omit any key where the message contains no information about it.
  Do NOT include null values — omit the key entirely.
  answered_fields: keys you are confident about.
  uncertain_fields: keys you extracted but are not fully certain of.

Field value constraints:
  appointment_type: exactly one of "cleaning", "general_checkup", "new_patient_exam", "emergency"
  insurance_name: provider name, or "self_pay" if patient has no insurance
  preferred_time_of_day: exactly one of "morning", "afternoon", "evening"
  group_preference: exactly one of "back_to_back", "same_day", "same_provider", "any"
  family_count: integer
  confirmation: true (yes/agree/confirmed) or false (no/disagree/change)
  phone_number: ONLY a North American 10-digit phone (e.g. 416-555-1234 or (416) 555-1234).
    Never put a pain-severity number (1–10), "probably a 6", or any single digit here — those belong
    in emergency_summary or nowhere if the patient only gave pain level without a phone.
"""


def _build_user_prompt(inp: InterpreterInput) -> str:
    lines: list[str] = []

    lines.append(f"Current workflow: {inp.workflow}")
    lines.append(f"Current step: {inp.step}")

    if inp.step == "awaiting_registration_followup":
        lines.append(
            "\nSPECIAL CONTEXT — registration follow-up:\n"
            "Maya just told the patient they can register in this SMS chat, explained what is needed, "
            'and asked something like "Would you like to register now?"\n'
            "The patient's reply below may be: agreeing to start new-patient registration (yes, sure, "
            "let's do it, etc.), declining (no, not now), or changing the subject.\n"
            "If they agree to register, set primary_intent to \"new_patient_registration\" with "
            "workflow_transition \"switch\" and confidence reflecting how clear they were.\n"
            "If they decline or are non-committal, set primary_intent to \"general_inquiry\" and "
            "workflow_transition \"continue\".\n"
            "You may set extracted_fields.confirmation to true/false when the reply is clearly yes or no."
        )

    if inp.step == "awaiting_family_slot_confirmation":
        lines.append(
            "\nSPECIAL CONTEXT — family appointment times just proposed:\n"
            "Maya listed specific date and time windows for each family member (one appointment each).\n"
            "The patient may agree in many natural ways (e.g. go ahead, book it, those work, perfect, "
            "sounds good, let's do it, lock it in, that works for us).\n"
            "They may push back or ask to change (e.g. too late in the day, need mornings, different day, "
            "can't do that Friday, let me think, not those times).\n"
            "Set extracted_fields.confirmation to true if they are accepting these proposed times and "
            "want you to reserve them.\n"
            "Set extracted_fields.confirmation to false if they want different times/dates or are "
            "clearly not ready to book these slots.\n"
            "If the message is unrelated or too ambiguous to tell, omit confirmation (do not guess)."
        )

    if inp.pending_field and inp.pending_question:
        lines.append(f'Last question asked: "{inp.pending_question}" (asking for: {inp.pending_field})')
    elif inp.pending_field:
        lines.append(f"Currently collecting: {inp.pending_field}")

    if inp.collected_fields:
        clean = {k: str(v) for k, v in inp.collected_fields.items() if not k.startswith("_")}
        if clean:
            lines.append(f"Already collected: {json.dumps(clean)}")

    if inp.missing_field_hints:
        lines.append("\nFields to extract from the patient message:")
        for hint in inp.missing_field_hints:
            lines.append(f'  "{hint.key}" ({hint.display_name}): {hint.description}')

    lines.append(f'\nPatient message: "{inp.message}"')
    return "\n".join(lines)


def _call_llm(inp: InterpreterInput) -> str:
    """Call Gemini and return the raw text response. Raises on API errors."""
    from google.genai import types as genai_types

    from llm.gemini import _model_name, get_client

    client = get_client()
    response = client.models.generate_content(
        model=_model_name(),
        contents=_build_user_prompt(inp),
        config=genai_types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            max_output_tokens=512,
            temperature=0.0,
        ),
    )
    return response.text.strip()


# ---------------------------------------------------------------------------
# Parse and validate the LLM response
# ---------------------------------------------------------------------------

_VALID_APPOINTMENT_TYPES = {"cleaning", "general_checkup", "new_patient_exam", "emergency"}
_VALID_TIME_OF_DAY = {"morning", "afternoon", "evening"}
_VALID_GROUP_PREFS = {"back_to_back", "same_day", "same_provider", "any"}


def _parse_llm_response(raw: str, inp: InterpreterInput) -> InterpreterOutput:
    """Parse the JSON returned by the LLM into a validated InterpreterOutput."""
    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    data: dict[str, Any] = json.loads(raw)

    # Remove null values from extracted_fields
    extracted = {k: v for k, v in (data.get("extracted_fields") or {}).items() if v is not None}
    extracted = _normalise_extracted(extracted)

    # Parse workflow_transition safely
    raw_transition = data.get("workflow_transition", "continue")
    try:
        transition = WorkflowTransition(raw_transition)
    except ValueError:
        transition = WorkflowTransition.CONTINUE

    return InterpreterOutput(
        primary_intent=data.get("primary_intent") or None,
        workflow_transition=transition,
        confidence=float(data.get("confidence", 1.0)),
        is_answering_pending_question=bool(data.get("is_answering_pending_question", True)),
        extracted_fields=extracted,
        answered_fields=list(data.get("answered_fields") or []),
        uncertain_fields=list(data.get("uncertain_fields") or []),
        should_escalate=bool(data.get("should_escalate", False)),
        suggested_next_action=data.get("suggested_next_action") or None,
        reasoning_summary=data.get("reasoning_summary") or None,
    )


def _normalise_extracted(extracted: dict[str, Any]) -> dict[str, Any]:
    """Coerce and validate LLM-produced field values to expected Python types."""
    out: dict[str, Any] = {}
    for key, value in extracted.items():
        try:
            if key == "appointment_type":
                val = str(value).strip().lower()
                if val in _VALID_APPOINTMENT_TYPES:
                    out[key] = val
            elif key == "preferred_time_of_day":
                val = str(value).strip().lower()
                if val in _VALID_TIME_OF_DAY:
                    out[key] = val
            elif key == "group_preference":
                val = str(value).strip().lower()
                if val in _VALID_GROUP_PREFS:
                    out[key] = val
            elif key == "family_count":
                out[key] = int(value)
            elif key == "confirmation":
                if isinstance(value, bool):
                    out[key] = value
                elif isinstance(value, str):
                    if value.lower() in ("true", "yes"):
                        out[key] = True
                    elif value.lower() in ("false", "no"):
                        out[key] = False
            elif key == "first_name":
                name_str = str(value).strip()
                parts = name_str.split()
                if len(parts) >= 2:
                    out["first_name"] = parts[0]
                    if "last_name" not in extracted:
                        out["last_name"] = " ".join(parts[1:])
                else:
                    out[key] = name_str
            elif key in (
                "insurance_name", "preferred_date_from", "emergency_summary",
                "cancel_reason", "last_name",
            ):
                out[key] = str(value).strip()
            elif key == "phone_number":
                from tools.validators import normalize_phone

                try:
                    out[key] = normalize_phone(str(value).strip())
                except ValueError:
                    # LLM often mislabels pain scores (e.g. "6" on a 1–10 scale) as phone_number.
                    pass
            else:
                out[key] = value
        except (ValueError, TypeError):
            logger.debug("Could not normalise extracted field %r = %r", key, value)
    return out


# ---------------------------------------------------------------------------
# Keyword / regex fallback (USE_LLM=false or API failure)
# ---------------------------------------------------------------------------


def _keyword_interpret(inp: InterpreterInput) -> InterpreterOutput:
    """
    Produce an InterpreterOutput using regex extractors when the LLM is unavailable.
    Mirrors the old _extract_fields() behaviour so existing tests stay green.
    This is a COMPATIBILITY path, not the production brain.
    """
    from state_machine.extractors import (
        extract_appointment_type,
        extract_cancel_reason,
        extract_confirmation,
        extract_dob,
        extract_email,
        extract_emergency_summary,
        extract_family_count,
        extract_full_name,
        extract_group_preference,
        extract_insurance,
        extract_last_name,
        extract_phone,
        extract_preferred_date,
        extract_time_of_day,
    )

    _REGEX_MAP: dict[str, Any] = {
        "first_name": extract_full_name,       # multi_key → dict
        "last_name": extract_last_name,
        "phone_number": extract_phone,
        "date_of_birth": extract_dob,
        "email": extract_email,
        "confirmation": extract_confirmation,
        "insurance_name": extract_insurance,
        "appointment_type": extract_appointment_type,
        "preferred_date_from": extract_preferred_date,
        "preferred_time_of_day": extract_time_of_day,
        "emergency_summary": extract_emergency_summary,
        "cancel_reason": extract_cancel_reason,
        "group_preference": extract_group_preference,
        "family_count": extract_family_count,
    }

    if inp.step == "awaiting_family_slot_confirmation":
        c = extract_confirmation(inp.message)
        transition = _detect_transition(inp.message, inp.workflow)
        if c is True:
            return InterpreterOutput(
                primary_intent=None,
                workflow_transition=transition,
                confidence=0.85,
                is_answering_pending_question=True,
                extracted_fields={"confirmation": True},
                answered_fields=["confirmation"],
                uncertain_fields=[],
                should_escalate=False,
                suggested_next_action=None,
                reasoning_summary="keyword fallback: affirmative to proposed family slots",
            )
        if c is False:
            return InterpreterOutput(
                primary_intent=None,
                workflow_transition=transition,
                confidence=0.85,
                is_answering_pending_question=True,
                extracted_fields={"confirmation": False},
                answered_fields=["confirmation"],
                uncertain_fields=[],
                should_escalate=False,
                suggested_next_action=None,
                reasoning_summary="keyword fallback: wants different times or declined",
            )

    extracted: dict[str, Any] = {}
    answered: list[str] = []

    # Avoid cross-field date contamination when one date field is active
    active_field: str | None = None
    if inp.step.startswith("collecting:"):
        active_field = inp.step.split(":", 1)[1]
    _DATE_GROUP = frozenset({"date_of_birth", "preferred_date_from"})

    for hint in inp.missing_field_hints:
        key = hint.key
        if active_field and active_field != key:
            if key in _DATE_GROUP and active_field in _DATE_GROUP:
                continue

        extractor_fn = _REGEX_MAP.get(key)
        if extractor_fn is None:
            continue
        try:
            val = extractor_fn(inp.message)
        except Exception:
            continue

        if val is None:
            continue

        if isinstance(val, dict):
            extracted.update(val)
            answered.extend(val.keys())
        else:
            extracted[key] = val
            answered.append(key)

    transition = _detect_transition(inp.message, inp.workflow)

    return InterpreterOutput(
        primary_intent=None,
        workflow_transition=transition,
        confidence=1.0,
        is_answering_pending_question=True,
        extracted_fields=extracted,
        answered_fields=answered,
        uncertain_fields=[],
        should_escalate=False,
        suggested_next_action=None,
        reasoning_summary="keyword/regex fallback path",
    )


def _detect_transition(message: str, current_workflow: str) -> WorkflowTransition:
    """
    Lightweight keyword heuristic for the fallback path.
    The LLM path uses the richer prompt instead.
    """
    lower = message.lower()
    # Explicit restart signals → switch
    if any(p in lower for p in ("start over", "cancel everything", "never mind the")):
        return WorkflowTransition.SWITCH
    # Clear workflow-change phrases → switch
    if any(p in lower for p in ("actually i want to cancel", "forget the booking",
                                "i need to reschedule instead", "actually reschedule")):
        return WorkflowTransition.SWITCH
    return WorkflowTransition.CONTINUE
