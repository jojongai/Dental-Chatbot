"""
LLM-based workflow intent classifier.

Replaces the keyword _INTENT_MAP when USE_LLM=true.
Returns a Workflow enum value from a single, cheap Gemini call
(no thinking budget, minimal tokens).

Falls back to keyword matching automatically if:
  - USE_LLM is false
  - The API call fails for any reason
  - Gemini returns an unrecognised workflow label

This means tests always run against the keyword path and never hit the API.
"""

from __future__ import annotations

import logging

from schemas.chat import Workflow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical workflow descriptions shown to the model
# ---------------------------------------------------------------------------

_WORKFLOW_DESCRIPTIONS = """
new_patient_registration  — caller is a brand new patient who has never visited before,
                            wants to register and/or book their first appointment.
                            Examples: "I've never been there before", "I'm new",
                            "never been a patient", "I'd like to become a patient",
                            "want to sign up", "first visit"

book_appointment          — existing patient who wants to schedule, book, or
                            make an appointment. Also triggers when someone says
                            they want a specific service (cleaning, check-up, exam)
                            without specifying they are new.
                            Examples: "I need a cleaning", "can I come in next week",
                            "I'd like to see the dentist", "I need to see someone",
                            "book me in", "I need to get my teeth done"

reschedule_appointment    — patient wants to move or change an existing appointment.
                            Examples: "I need to move my appointment", "can we do
                            a different day", "I can't make it Thursday", "change
                            my booking"

cancel_appointment        — patient wants to cancel or remove an existing appointment.
                            Examples: "I need to cancel", "please cancel my booking",
                            "I won't be coming in", "I want to cancel my visit"

emergency_triage          — dental emergency: severe or sudden pain, swelling,
                            broken/cracked/knocked-out tooth, abscess, bleeding.
                            Examples: "my tooth broke", "I'm in a lot of pain",
                            "it's really hurting", "I think I have an abscess",
                            "my gum is bleeding a lot", "I need urgent help",
                            "it hurts so bad", "swollen face"

family_booking            — caller wants to book for multiple family members,
                            kids, or dependants.
                            Examples: "for me and my kids", "my whole family needs
                            appointments", "my children need cleanings", "my husband
                            and I want to come in together"

handoff                   — caller explicitly wants to speak to a human, be called
                            back, or reach the front desk.
                            Examples: "can I talk to someone", "please have someone
                            call me", "I'd like to speak to a person",
                            "can I reach reception"

general_inquiry           — anything else: questions about hours, location, insurance,
                            pricing, parking, services offered, or anything that
                            doesn't fit the above.
                            Examples: "what are your hours", "do you take Sun Life",
                            "where are you located", "how much does a cleaning cost"
"""

_SYSTEM_PROMPT = f"""You are an intent classifier for a dental office SMS chatbot.

Your ONLY job is to read a patient's message and return the single most appropriate
workflow label from the list below. Reply with ONLY the label — no explanation,
no punctuation, no extra words.

Valid labels (pick exactly one):
  new_patient_registration
  book_appointment
  reschedule_appointment
  cancel_appointment
  emergency_triage
  family_booking
  handoff
  general_inquiry

Workflow descriptions to guide your choice:
{_WORKFLOW_DESCRIPTIONS}

Rules:
- If the patient mentions pain, urgency, or a dental emergency, prefer emergency_triage.
- If the patient is clearly new (never visited), prefer new_patient_registration over book_appointment.
- If in doubt, return general_inquiry.
- Return ONLY the label, nothing else.
"""

# ---------------------------------------------------------------------------
# Valid labels → Workflow enum mapping
# ---------------------------------------------------------------------------

_LABEL_TO_WORKFLOW: dict[str, Workflow] = {
    "new_patient_registration": Workflow.NEW_PATIENT_REGISTRATION,
    "book_appointment": Workflow.BOOK_APPOINTMENT,
    "reschedule_appointment": Workflow.RESCHEDULE_APPOINTMENT,
    "cancel_appointment": Workflow.CANCEL_APPOINTMENT,
    "emergency_triage": Workflow.EMERGENCY_TRIAGE,
    "family_booking": Workflow.FAMILY_BOOKING,
    "handoff": Workflow.HANDOFF,
    "general_inquiry": Workflow.GENERAL_INQUIRY,
}


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def classify_intent(message: str, fallback_fn=None) -> Workflow:
    """
    Classify the user's opening message into a Workflow using Gemini.

    Only called when the conversation is at GENERAL_INQUIRY (start / restart).
    The "stay in current workflow" guard in machine.py runs before this and
    short-circuits for mid-workflow messages.

    Parameters
    ----------
    message:
        The raw user message to classify.
    fallback_fn:
        Optional callable(message) -> Workflow used when LLM is disabled or
        the API call fails. Defaults to the keyword _INTENT_MAP lookup.

    Returns
    -------
    Workflow enum value — never raises.
    """
    from config import get_settings

    settings = get_settings()

    if not settings.use_llm:
        return _keyword_fallback(message, fallback_fn)

    try:
        from llm.gemini import get_client, _model_name
        from google.genai import types as genai_types

        client = get_client()
        response = client.models.generate_content(
            model=_model_name(),
            contents=message,
            config=genai_types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                # No thinking budget — pure classification, fast + cheap.
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
                max_output_tokens=16,
                temperature=0.0,
            ),
        )
        label = response.text.strip().lower().rstrip(".")
        workflow = _LABEL_TO_WORKFLOW.get(label)
        if workflow is not None:
            logger.debug("LLM intent: %r → %s", message[:60], label)
            return workflow

        logger.warning("LLM returned unknown intent label %r — falling back to keywords", label)

    except Exception as exc:
        logger.warning("LLM intent classification failed (%s) — falling back to keywords", exc)

    return _keyword_fallback(message, fallback_fn)


# ---------------------------------------------------------------------------
# Keyword fallback (mirrors the old _INTENT_MAP logic)
# ---------------------------------------------------------------------------

_KEYWORD_MAP: list[tuple[list[str], Workflow]] = [
    (
        ["emergency", "severe pain", "broken tooth", "broke a tooth", "cracked tooth",
         "abscess", "swollen", "knocked out", "toothache", "bleeding gum"],
        Workflow.EMERGENCY_TRIAGE,
    ),
    (
        ["new patient", "register", "first time", "first visit", "sign up"],
        Workflow.NEW_PATIENT_REGISTRATION,
    ),
    (
        ["reschedule", "move my appointment", "change my appointment",
         "different time", "different day"],
        Workflow.RESCHEDULE_APPOINTMENT,
    ),
    (["cancel"], Workflow.CANCEL_APPOINTMENT),
    (
        ["family", "kids", "children", "my kid", "spouse",
         "husband", "wife", "son", "daughter", "partner"],
        Workflow.FAMILY_BOOKING,
    ),
    (
        ["existing patient", "already a patient", "been a patient"],
        Workflow.BOOK_APPOINTMENT,  # triggers EXISTING_PATIENT_VERIFICATION sub-workflow
    ),
    (
        ["book", "schedule", "appointment", "cleaning", "checkup",
         "check-up", "exam", "visit", "coming in"],
        Workflow.BOOK_APPOINTMENT,
    ),
    (
        ["speak to", "talk to", "human", "person", "staff",
         "someone", "representative", "call me"],
        Workflow.HANDOFF,
    ),
]


def _keyword_fallback(message: str, override_fn=None) -> Workflow:
    if override_fn is not None:
        return override_fn(message)
    lower = message.lower()
    for keywords, workflow in _KEYWORD_MAP:
        if any(k in lower for k in keywords):
            return workflow
    return Workflow.GENERAL_INQUIRY
