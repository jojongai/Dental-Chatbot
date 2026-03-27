"""
Field and workflow definitions.

A FieldDef describes one piece of data the chatbot needs to collect:
  - what to ask the user
  - a natural-language description fed to the LLM interpreter
  - which extractor to run (only for deterministic / high-confidence fields)

A WorkflowDef describes a complete chatbot workflow:
  - ordered required fields (the machine asks for them in this order)
  - optional fields (extracted opportunistically but never explicitly prompted)
  - which tool to call when all required fields are present
  - whether to pause for confirmation before calling the tool

Field taxonomy
--------------
Deterministic fields — extractor is set; regex is reliable and high-confidence:
  first_name / last_name, phone_number, date_of_birth, email, confirmation

Semantic fields — extractor is None; the LLM interpreter handles these because
  they need contextual understanding (e.g. "no insurance", "next Tuesday",
  "my tooth is killing me"). The regex fallbacks still exist in extractors.py
  and are used by the interpreter's USE_LLM=false keyword path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas.chat import Workflow
from state_machine.extractors import (
    extract_confirmation,
    extract_dob,
    extract_email,
    extract_full_name,
    extract_last_name,
    extract_phone,
)

# ---------------------------------------------------------------------------
# Field definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldDef:
    key: str
    display_name: str
    prompt: str
    # Natural-language description fed into the LLM interpreter prompt.
    description: str
    # Regex/heuristic extractor. None for semantic fields (interpreter handles them).
    extractor: object | None = None  # Callable[[str], Any | None]
    optional: bool = False
    # True when this extractor returns {'first_name':…, 'last_name':…} instead of a scalar.
    multi_key: bool = False


# --- individual field definitions ---

FIELDS: dict[str, FieldDef] = {
    # ------------------------------------------------------------------
    # Deterministic fields — extractor set, regex is reliable
    # ------------------------------------------------------------------
    "first_name": FieldDef(
        key="first_name",
        display_name="first name",
        prompt="What's your full name?",
        description=(
            "The patient's first name and last name. "
            "Look for any phrase that introduces a person's name: "
            "'I'm John Smith', 'My name is Alice', or just a bare two-word name."
        ),
        extractor=extract_full_name,
        multi_key=True,  # also populates last_name
    ),
    "last_name": FieldDef(
        key="last_name",
        display_name="last name",
        prompt="What's your last name?",
        description="The patient's family/last name.",
        extractor=extract_last_name,
    ),
    "phone_number": FieldDef(
        key="phone_number",
        display_name="phone number",
        prompt="What's a good number to reach you at?",
        description=(
            "A 10-digit North American phone number. "
            "Accept any common format: 647-638-5400, (647) 638-5400, 6476385400."
        ),
        extractor=extract_phone,
    ),
    "date_of_birth": FieldDef(
        key="date_of_birth",
        display_name="date of birth",
        prompt="What's your date of birth?",
        description=(
            "The patient's date of birth as a date. "
            "Accepts formats like 'August 28, 2003', '08/28/2003', '2003-08-28'."
        ),
        extractor=extract_dob,
    ),
    "email": FieldDef(
        key="email",
        display_name="email address",
        prompt=(
            "I found a couple of records that match — "
            "could you share your email so I can find the right one?"
        ),
        description="The patient's email address (used as a tiebreaker when duplicate records exist).",
        extractor=extract_email,
        optional=True,
    ),
    "confirmation": FieldDef(
        key="confirmation",
        display_name="confirmation",
        prompt="Does everything look good?",
        description=(
            "Whether the patient is confirming (yes) or declining (no) the booking summary. "
            "True = yes/confirmed; False = no/change something."
        ),
        extractor=extract_confirmation,
    ),

    # ------------------------------------------------------------------
    # Semantic fields — extractor=None, LLM interpreter handles extraction
    # ------------------------------------------------------------------
    "insurance_name": FieldDef(
        key="insurance_name",
        display_name="insurance provider",
        prompt="Do you have dental insurance? If so, which provider? No worries if you don't.",
        description=(
            "The patient's dental insurance provider. "
            "Return the provider name (e.g. 'Sun Life', 'MetLife') or 'self_pay' if they "
            "have no insurance. Treat responses like 'No', 'Nope', 'I don't', "
            "'pay out of pocket', 'not insured', 'covered through work' all as valid answers."
        ),
        extractor=None,
        optional=True,
    ),
    "appointment_type": FieldDef(
        key="appointment_type",
        display_name="appointment type",
        prompt="What kind of appointment are you looking for?",
        description=(
            "The type of dental appointment. Return exactly one of: "
            "'cleaning' (hygiene, polish, scale), "
            "'general_checkup' (check-up, routine exam, regular visit), "
            "'new_patient_exam' (first visit, new patient, registration exam), "
            "'emergency' (pain, broken/cracked tooth, abscess, swelling, urgent care)."
        ),
        extractor=None,
    ),
    "preferred_date_from": FieldDef(
        key="preferred_date_from",
        display_name="preferred date",
        prompt="When would you like your appointment?",
        description=(
            "The patient's preferred appointment date or time-frame. "
            "Return an ISO date (YYYY-MM-DD) for exact dates, or a natural phrase "
            "like 'next week', 'next Monday', 'sometime in April', 'as soon as possible' "
            "for relative expressions. Must be a future date."
        ),
        extractor=None,
    ),
    "preferred_time_of_day": FieldDef(
        key="preferred_time_of_day",
        display_name="preferred time of day",
        prompt="Any preference on time of day — morning, afternoon, or evening?",
        description=(
            "The patient's preferred time of day for their appointment. "
            "Return exactly one of: 'morning', 'afternoon', 'evening'. "
            "Map loosely: 'early' → morning; 'lunch'/'midday' → afternoon; "
            "'after work'/'PM'/'late' → evening."
        ),
        extractor=None,
        optional=True,
    ),
    "emergency_summary": FieldDef(
        key="emergency_summary",
        display_name="emergency description",
        prompt=(
            "Can you quickly describe what's going on? "
            "Where's the pain, how bad on a scale of 1–10, and when did it start?"
        ),
        description=(
            "A brief description of the dental emergency: location of pain, severity "
            "on a 1–10 scale, and when it started. Capture the patient's own words "
            "as a short free-text summary."
        ),
        extractor=None,
    ),
    "cancel_reason": FieldDef(
        key="cancel_reason",
        display_name="reason for cancellation",
        prompt="Mind sharing why you need to cancel?",
        description=(
            "The patient's reason for cancelling their appointment. "
            "Accept any free-text answer; return a short summary. "
            "If they don't give a reason, return 'Patient request'."
        ),
        extractor=None,
    ),
    "group_preference": FieldDef(
        key="group_preference",
        display_name="scheduling preference",
        prompt=(
            "How would you like to schedule everyone? "
            "Back-to-back, same day, same provider, or just whatever's available?"
        ),
        description=(
            "Scheduling preference for a family/group booking. "
            "Return one of: 'back_to_back', 'same_day', 'same_provider', 'any'. "
            "Map phrases like 'doesn't matter' or 'whatever works' to 'any'."
        ),
        extractor=None,
        optional=True,
    ),
    "family_count": FieldDef(
        key="family_count",
        display_name="number of family members",
        prompt="How many people are we booking for?",
        description=(
            "The number of family members / people to book appointments for. "
            "Return an integer. Accept digit words: 'two' → 2, 'three' → 3, etc."
        ),
        extractor=None,
    ),
}


# ---------------------------------------------------------------------------
# Workflow definitions
# ---------------------------------------------------------------------------


@dataclass
class WorkflowDef:
    workflow: Workflow
    display_name: str

    # Fields asked in order; machine asks for them one at a time.
    required_fields: list[str]

    # Collected opportunistically from any message but never prompted for.
    optional_fields: list[str] = field(default_factory=list)

    # Tool to call once all required_fields are present.
    tool_name: str | None = None

    # If True, show a confirmation summary and wait for "yes" before calling tool.
    requires_confirmation: bool = False

    # Opening message for this workflow (sent when workflow is first entered).
    greeting: str = ""

    # Message shown once all fields are collected (just before confirmation/tool call).
    ready_message: str = ""

    # Per-workflow overrides for field prompts (field_key → custom prompt).
    prompt_overrides: dict[str, str] = field(default_factory=dict)

    # If this workflow needs patient identity verified first, set this to
    # EXISTING_PATIENT_VERIFICATION; the machine will run it as a sub-workflow.
    requires_patient_id: bool = False


WORKFLOWS: dict[Workflow, WorkflowDef] = {
    # ------------------------------------------------------------------
    # General inquiry — no field collection, call get_clinic_info directly
    # ------------------------------------------------------------------
    Workflow.GENERAL_INQUIRY: WorkflowDef(
        workflow=Workflow.GENERAL_INQUIRY,
        display_name="General Inquiry",
        required_fields=[],
        optional_fields=[],
        tool_name="get_clinic_info",
        greeting="Of course! What can I help you with?",
    ),
    # ------------------------------------------------------------------
    # New patient registration
    # ------------------------------------------------------------------
    Workflow.NEW_PATIENT_REGISTRATION: WorkflowDef(
        workflow=Workflow.NEW_PATIENT_REGISTRATION,
        display_name="New Patient Registration",
        required_fields=[
            "first_name",  # multi_key → also sets last_name
            "phone_number",
            "date_of_birth",
            "insurance_name",  # optional but explicitly asked
            "appointment_type",
        ],
        optional_fields=["preferred_time_of_day"],
        tool_name="create_patient",
        requires_confirmation=True,
        greeting="Great, I can get you set up right now!",
        ready_message="Awesome, I've got everything I need. Just want to confirm before I go ahead:",
    ),
    # ------------------------------------------------------------------
    # Existing patient verification
    # ------------------------------------------------------------------
    Workflow.EXISTING_PATIENT_VERIFICATION: WorkflowDef(
        workflow=Workflow.EXISTING_PATIENT_VERIFICATION,
        display_name="Patient Verification",
        required_fields=["first_name", "last_name", "phone_number"],
        optional_fields=["email"],
        tool_name="lookup_patient",
        greeting="Sure! Let me pull up your file.",
        ready_message="Perfect, give me one sec to look you up!",
        prompt_overrides={"phone_number": "What's your phone number?"},
    ),
    # ------------------------------------------------------------------
    # Book appointment (existing patient)
    # ------------------------------------------------------------------
    Workflow.BOOK_APPOINTMENT: WorkflowDef(
        workflow=Workflow.BOOK_APPOINTMENT,
        display_name="Book Appointment",
        required_fields=["appointment_type", "preferred_date_from"],
        optional_fields=["preferred_time_of_day"],
        tool_name="search_slots",
        requires_patient_id=True,
        greeting=(
            "Happy to get that booked for you! "
            "What kind of appointment are you looking for — cleaning, check-up, new patient exam, or is it urgent?"
        ),
        ready_message="Let me check what's available for you...",
    ),
    # ------------------------------------------------------------------
    # Reschedule appointment
    # ------------------------------------------------------------------
    Workflow.RESCHEDULE_APPOINTMENT: WorkflowDef(
        workflow=Workflow.RESCHEDULE_APPOINTMENT,
        display_name="Reschedule Appointment",
        required_fields=["preferred_date_from"],
        optional_fields=["preferred_time_of_day"],
        tool_name="search_slots",
        requires_patient_id=True,
        greeting="No problem, I can move that for you! Let me pull up your file first.",
        ready_message="Let me see what other times are open for you...",
    ),
    # ------------------------------------------------------------------
    # Cancel appointment
    # ------------------------------------------------------------------
    Workflow.CANCEL_APPOINTMENT: WorkflowDef(
        workflow=Workflow.CANCEL_APPOINTMENT,
        display_name="Cancel Appointment",
        required_fields=["cancel_reason"],
        optional_fields=[],
        tool_name="cancel_appointment",
        requires_patient_id=True,
        requires_confirmation=True,
        greeting="Got it, I can take care of that for you. Let me pull up your file first.",
        ready_message="Just want to make sure I have the right appointment before I cancel it.",
    ),
    # ------------------------------------------------------------------
    # Family booking
    # ------------------------------------------------------------------
    Workflow.FAMILY_BOOKING: WorkflowDef(
        workflow=Workflow.FAMILY_BOOKING,
        display_name="Family Booking",
        # Per-member + group scheduling are driven by state_machine/family_booking.py
        required_fields=[],
        optional_fields=[],
        tool_name="book_family_appointments",
        requires_patient_id=True,
        # Confirmation is handled inside family_booking.py (members, then slot list).
        requires_confirmation=False,
        greeting="Love it — I can get everyone booked.",
        ready_message="Here's what I have for your family booking:",
    ),
    # ------------------------------------------------------------------
    # Emergency triage
    # ------------------------------------------------------------------
    Workflow.EMERGENCY_TRIAGE: WorkflowDef(
        workflow=Workflow.EMERGENCY_TRIAGE,
        display_name="Emergency Triage",
        required_fields=["first_name", "phone_number", "emergency_summary"],
        optional_fields=["preferred_date_from", "preferred_time_of_day"],
        tool_name="create_staff_notification",
        requires_confirmation=False,  # do NOT delay — notify staff immediately
        greeting=(
            "Oh no, I'm so sorry — we want to help right away. "
            "Can you tell me your name and quickly describe what's going on? "
            "Like where the pain is, how bad (1–10), and when it started?"
        ),
        ready_message=(
            "I've just sent an alert to our team. "
            "Someone will reach out to you very shortly — hang tight, we've got you."
        ),
    ),
    # ------------------------------------------------------------------
    # Handoff — explicit escalation to human staff
    # ------------------------------------------------------------------
    Workflow.HANDOFF: WorkflowDef(
        workflow=Workflow.HANDOFF,
        display_name="Staff Handoff",
        required_fields=["phone_number"],
        optional_fields=["first_name"],
        tool_name="create_staff_notification",
        greeting="Of course! What number should they call you back on?",
        ready_message="Done! Someone from our team will give you a call back shortly.",
    ),
}


# ---------------------------------------------------------------------------
# Workflow field summary — used for debugging and the chatbot dashboard
# ---------------------------------------------------------------------------


def workflow_field_summary(workflow: Workflow) -> dict:
    """Return human-readable required/optional field lists for a workflow."""
    wf = WORKFLOWS[workflow]
    return {
        "workflow": workflow.value,
        "display_name": wf.display_name,
        "required_fields": wf.required_fields,
        "optional_fields": wf.optional_fields,
        "tool_name": wf.tool_name,
        "requires_patient_id": wf.requires_patient_id,
        "requires_confirmation": wf.requires_confirmation,
    }
