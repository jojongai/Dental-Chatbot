"""
Field and workflow definitions.

A FieldDef describes one piece of data the chatbot needs to collect:
  - what to ask the user
  - which extractor to use

A WorkflowDef describes a complete chatbot workflow:
  - ordered required fields (the machine asks for them in this order)
  - optional fields (extracted opportunistically but never explicitly prompted)
  - which tool to call when all required fields are present
  - whether to pause for confirmation before calling the tool

Every workflow also declares a `sub_workflow` — when the primary workflow
needs patient identity first (e.g. book_appointment needs patient_id), the
machine switches to `existing_patient_verification` as a sub-workflow and
resumes the parent when verification succeeds.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas.chat import Workflow
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

# ---------------------------------------------------------------------------
# Field definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldDef:
    key: str
    display_name: str
    prompt: str
    # Extractor function; returns a scalar, dict, or None.
    # If it returns a dict, each key in the dict is merged into collected_fields.
    extractor: object  # Callable[[str], Any | None]
    optional: bool = False
    # True when this extractor returns {'first_name':…, 'last_name':…} instead of a scalar
    multi_key: bool = False


# --- individual field definitions ---

FIELDS: dict[str, FieldDef] = {
    "first_name": FieldDef(
        key="first_name",
        display_name="first name",
        prompt="Could I start with your full name?",
        extractor=extract_full_name,
        multi_key=True,  # also populates last_name
    ),
    "last_name": FieldDef(
        key="last_name",
        display_name="last name",
        prompt="Could you tell me your last name?",
        extractor=extract_last_name,
    ),
    "phone_number": FieldDef(
        key="phone_number",
        display_name="phone number",
        prompt="What's the best phone number to reach you at?",
        extractor=extract_phone,
    ),
    "date_of_birth": FieldDef(
        key="date_of_birth",
        display_name="date of birth",
        prompt="And your date of birth? (e.g. March 14, 1985)",
        extractor=extract_dob,
    ),
    "insurance_name": FieldDef(
        key="insurance_name",
        display_name="insurance provider",
        prompt="Do you have dental insurance? If so, what's the name of your provider? "
        "(It's okay if you don't — just say 'no insurance'.)",
        extractor=extract_insurance,
        optional=True,
    ),
    "appointment_type": FieldDef(
        key="appointment_type",
        display_name="appointment type",
        prompt="What type of appointment would you like? "
        "We offer: cleaning, general check-up, new patient exam, or emergency.",
        extractor=extract_appointment_type,
    ),
    "preferred_date_from": FieldDef(
        key="preferred_date_from",
        display_name="preferred date",
        prompt="What date or date range works best for you? (e.g. 'next week', 'April 5')",
        extractor=extract_preferred_date,
    ),
    "preferred_time_of_day": FieldDef(
        key="preferred_time_of_day",
        display_name="preferred time of day",
        prompt="Do you have a preference for morning, afternoon, or evening?",
        extractor=extract_time_of_day,
        optional=True,
    ),
    "emergency_summary": FieldDef(
        key="emergency_summary",
        display_name="emergency description",
        prompt="Please briefly describe what's happening — where is the pain, "
        "how severe (1–10), and when did it start?",
        extractor=extract_emergency_summary,
    ),
    "cancel_reason": FieldDef(
        key="cancel_reason",
        display_name="reason for cancellation",
        prompt="Could you let us know why you'd like to cancel? (e.g. schedule conflict, feeling better, etc.)",
        extractor=extract_cancel_reason,
    ),
    "group_preference": FieldDef(
        key="group_preference",
        display_name="scheduling preference",
        prompt="How would you like the appointments arranged? "
        "Options: back-to-back, same day, same provider, or any (best available).",
        extractor=extract_group_preference,
        optional=True,
    ),
    "family_count": FieldDef(
        key="family_count",
        display_name="number of family members",
        prompt="How many people need appointments in total?",
        extractor=extract_family_count,
    ),
    "email": FieldDef(
        key="email",
        display_name="email address",
        prompt="Could you share your email address so I can find your exact record?",
        extractor=extract_email,
        optional=True,
    ),
    "confirmation": FieldDef(
        key="confirmation",
        display_name="confirmation",
        prompt="Does that all look correct? (yes / no)",
        extractor=extract_confirmation,
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
        greeting="I can help with hours, location, insurance, or booking. What do you need?",
    ),
    # ------------------------------------------------------------------
    # New patient registration
    # Collect: name, phone, DOB, insurance (optional), appointment type, date
    # Tool: create_patient  (then search_slots in next step)
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
            "preferred_date_from",
        ],
        optional_fields=["preferred_time_of_day"],
        tool_name="create_patient",
        requires_confirmation=True,
        greeting="I can get you registered as a new patient right here. What is your full name?",
        ready_message=(
            "Great, I have everything I need to register you. Let me just confirm the details before we proceed."
        ),
    ),
    # ------------------------------------------------------------------
    # Existing patient verification
    # Collect: first_name + last_name (via multi_key full-name extractor) + phone_number
    # first_name prompt asks for full name → populates both first_name and last_name.
    # phone_number may already be pre-filled from caller ID, so often only one question needed.
    # email is optional — only asked if two records share the same name + phone (edge case).
    # Tool: lookup_patient
    # ------------------------------------------------------------------
    Workflow.EXISTING_PATIENT_VERIFICATION: WorkflowDef(
        workflow=Workflow.EXISTING_PATIENT_VERIFICATION,
        display_name="Patient Verification",
        required_fields=["first_name", "last_name", "phone_number"],
        optional_fields=["email"],
        tool_name="lookup_patient",
        greeting="To pull up your file, could you tell me your full name and phone number?",
        ready_message="Thanks — let me look you up in our system.",
    ),
    # ------------------------------------------------------------------
    # Book appointment (existing patient)
    # Requires patient_id — machine runs verification sub-workflow first if absent.
    # Collect: appointment_type, preferred date
    # Tool: search_slots  (then book_appointment after slot selection)
    # ------------------------------------------------------------------
    Workflow.BOOK_APPOINTMENT: WorkflowDef(
        workflow=Workflow.BOOK_APPOINTMENT,
        display_name="Book Appointment",
        required_fields=["appointment_type", "preferred_date_from"],
        optional_fields=["preferred_time_of_day"],
        tool_name="search_slots",
        requires_patient_id=True,
        greeting=(
            "I can book an appointment for you. "
            "What type do you need - cleaning, check-up, new patient exam, or emergency?"
        ),
        ready_message="Let me search for available slots for you.",
    ),
    # ------------------------------------------------------------------
    # Reschedule appointment
    # Requires patient_id + appointment_id (appointment_id set after patient lookup
    # shows their upcoming appointments and they select one).
    # Collect: preferred_date_from, optional time_of_day
    # Tool: search_slots  (then reschedule_appointment after slot selection)
    # ------------------------------------------------------------------
    Workflow.RESCHEDULE_APPOINTMENT: WorkflowDef(
        workflow=Workflow.RESCHEDULE_APPOINTMENT,
        display_name="Reschedule Appointment",
        # appointment_id is set programmatically after showing the patient their bookings.
        required_fields=["preferred_date_from"],
        optional_fields=["preferred_time_of_day"],
        tool_name="search_slots",
        requires_patient_id=True,
        greeting="Sure, I can reschedule your appointment. Let me first pull up your file.",
        ready_message="Let me find available slots for rescheduling.",
    ),
    # ------------------------------------------------------------------
    # Cancel appointment
    # Requires patient_id + appointment_id (set after lookup + selection).
    # Collect: cancel_reason, confirmation
    # Tool: cancel_appointment
    # ------------------------------------------------------------------
    Workflow.CANCEL_APPOINTMENT: WorkflowDef(
        workflow=Workflow.CANCEL_APPOINTMENT,
        display_name="Cancel Appointment",
        required_fields=["cancel_reason"],
        optional_fields=[],
        tool_name="cancel_appointment",
        requires_patient_id=True,
        requires_confirmation=True,
        greeting="Sure, I can cancel your appointment. Let me first pull up your file.",
        ready_message="Understood. Let me confirm the cancellation details.",
    ),
    # ------------------------------------------------------------------
    # Family booking
    # Collect: family count + each member's appointment type, date range,
    # and optional group preference.
    # Tool: book_family_appointments
    # ------------------------------------------------------------------
    Workflow.FAMILY_BOOKING: WorkflowDef(
        workflow=Workflow.FAMILY_BOOKING,
        display_name="Family Booking",
        required_fields=["family_count", "appointment_type", "preferred_date_from"],
        optional_fields=["group_preference", "preferred_time_of_day"],
        tool_name="book_family_appointments",
        requires_patient_id=True,
        requires_confirmation=True,
        greeting="I can book for your whole family. How many people need appointments?",
        ready_message=("Got it. I'll look for back-to-back slots for your family. Let me just confirm the details."),
    ),
    # ------------------------------------------------------------------
    # Emergency triage
    # Collect: name, phone, emergency_summary
    # Tool: create_staff_notification (urgent) — staff are notified immediately.
    # Slot booking handled in a second step after staff acknowledgement.
    # ------------------------------------------------------------------
    Workflow.EMERGENCY_TRIAGE: WorkflowDef(
        workflow=Workflow.EMERGENCY_TRIAGE,
        display_name="Emergency Triage",
        required_fields=["first_name", "phone_number", "emergency_summary"],
        optional_fields=["preferred_date_from", "preferred_time_of_day"],
        tool_name="create_staff_notification",
        requires_confirmation=False,  # do NOT delay — notify staff immediately
        greeting=(
            "I want to help right away. Please share your name and briefly describe "
            "what is happening - location of pain, severity 1-10, and when it started."
        ),
        ready_message=(
            "Thank you. I've notified our dental team about your emergency "
            "and they will be in touch with you shortly. "
            "We'll do our best to see you as soon as possible today."
        ),
    ),
    # ------------------------------------------------------------------
    # Handoff — explicit escalation to human staff
    # No tool; just acknowledge and create a staff notification.
    # ------------------------------------------------------------------
    Workflow.HANDOFF: WorkflowDef(
        workflow=Workflow.HANDOFF,
        display_name="Staff Handoff",
        required_fields=["phone_number"],
        optional_fields=["first_name"],
        tool_name="create_staff_notification",
        greeting=(
            "I'll have a team member call you back. What's your phone number?"
        ),
        ready_message=("I've let our team know. A staff member will call you back as soon as possible."),
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
