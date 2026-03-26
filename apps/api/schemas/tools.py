"""
Typed tool contracts.

Each tool has a named Input and Output model.  These are the shapes the LLM
orchestration layer will use when constructing tool calls and parsing results.
All fields are documented so an LLM can understand them from the schema alone.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.appointment import (
    AppointmentOut,
    BookAppointmentIn,
    CancelAppointmentIn,
    FamilyBookingIn,
    FamilyBookingOut,
    RescheduleAppointmentIn,
    SlotSearchIn,
    SlotSearchOut,
)
from schemas.patient import PatientCreateIn, PatientLookupIn, PatientOut

# ---------------------------------------------------------------------------
# lookup_patient
# ---------------------------------------------------------------------------


class LookupPatientInput(PatientLookupIn):
    """
    Search for an existing patient.
    Provide phone_number OR (last_name + date_of_birth) — at least one combination.
    """


class LookupPatientOutput(BaseModel):
    found: bool
    patient: PatientOut | None = None
    match_confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="0.0 = no match, 1.0 = exact match on all provided fields",
    )
    multiple_matches: bool = False


# ---------------------------------------------------------------------------
# create_patient
# ---------------------------------------------------------------------------


class CreatePatientInput(PatientCreateIn):
    """Register a new patient from the chatbot new-patient flow."""

    practice_id: str | None = Field(None, description="Resolved from session context if omitted.")


class CreatePatientOutput(BaseModel):
    success: bool
    patient: PatientOut | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# search_slots
# ---------------------------------------------------------------------------


class SearchSlotsInput(SlotSearchIn):
    """Find available appointment slots matching the given criteria."""


class SearchSlotsOutput(SlotSearchOut):
    pass


# ---------------------------------------------------------------------------
# book_appointment
# ---------------------------------------------------------------------------


class BookAppointmentInput(BookAppointmentIn):
    """
    Book a specific slot for a patient.
    If is_emergency=True, an emergency_summary is required and
    a staff notification is automatically created.
    """


class BookAppointmentOutput(BaseModel):
    success: bool
    appointment: AppointmentOut | None = None
    staff_notified: bool = False  # True when emergency notification was sent
    error: str | None = None


# ---------------------------------------------------------------------------
# list_patient_appointments
# ---------------------------------------------------------------------------


class ListPatientAppointmentsInput(BaseModel):
    """Return upcoming (non-cancelled) appointments for a verified patient."""

    patient_id: str


class AppointmentSummary(BaseModel):
    """Compact appointment row for presenting a pick-list to the patient."""

    id: str
    appointment_type_display: str
    date_label: str
    time_label: str
    provider_display_name: str | None = None
    status: str


class ListPatientAppointmentsOutput(BaseModel):
    patient_id: str
    appointments: list[AppointmentSummary]
    total: int


# ---------------------------------------------------------------------------
# reschedule_appointment
# ---------------------------------------------------------------------------


class RescheduleAppointmentInput(RescheduleAppointmentIn):
    """Move an existing appointment to a new slot."""


class RescheduleAppointmentOutput(BaseModel):
    success: bool
    old_appointment: AppointmentOut | None = None
    new_appointment: AppointmentOut | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# cancel_appointment
# ---------------------------------------------------------------------------


class CancelAppointmentInput(CancelAppointmentIn):
    """Cancel an existing appointment and free the slot."""


class CancelAppointmentOutput(BaseModel):
    success: bool
    cancelled_appointment: AppointmentOut | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# book_family_appointments
# ---------------------------------------------------------------------------


class BookFamilyAppointmentsInput(FamilyBookingIn):
    """
    Book back-to-back (or same-day) appointments for multiple family members.
    Each member gets one independent appointment; they are linked via an
    AppointmentRequestGroup for staff visibility.
    """


class BookFamilyAppointmentsOutput(FamilyBookingOut):
    pass


# ---------------------------------------------------------------------------
# create_staff_notification
# ---------------------------------------------------------------------------


class CreateStaffNotificationInput(BaseModel):
    """
    Raise an alert in the staff dashboard.
    Called automatically for emergencies; also used for manual-review escalations.
    """

    notification_type: str = Field(
        ...,
        examples=["emergency", "manual_review", "callback_request", "verification_issue"],
    )
    title: str = Field(..., examples=["Emergency visit requested"])
    body: str = Field(
        ...,
        examples=["Patient reports severe toothache (pain 8/10). Emergency summary attached."],
    )
    priority: str = Field("normal", examples=["urgent", "high", "normal", "low"])
    patient_id: str | None = None
    appointment_id: str | None = None
    conversation_id: str | None = None
    practice_id: str | None = Field(None, description="Resolved from session context if omitted.")


class CreateStaffNotificationOutput(BaseModel):
    success: bool
    notification_id: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# get_clinic_info
# ---------------------------------------------------------------------------


class GetClinicInfoInput(BaseModel):
    """
    Retrieve FAQ entries and clinic settings for a given category.
    Leave category=None to fetch all active entries.
    """

    category: str | None = Field(
        None,
        examples=["insurance", "payment", "hours", "location", "new_patient"],
    )
    question_hint: str | None = Field(
        None,
        description="Free-text hint to help select the most relevant FAQ entries.",
        examples=["Do you accept Sun Life?"],
    )


class FaqEntryOut(BaseModel):
    category: str
    question: str
    answer: str


class ClinicSettingsOut(BaseModel):
    accepts_major_insurance: bool
    self_pay_available: bool
    membership_available: bool
    financing_available: bool
    emergency_escalation_enabled: bool
    location_name: str
    address: str
    phone_number: str | None
    hours_summary: str  # Human-readable, e.g. "Mon–Sat 8:00 AM – 6:00 PM"


class GetClinicInfoOutput(BaseModel):
    faq_entries: list[FaqEntryOut]
    settings: ClinicSettingsOut | None = None


# ---------------------------------------------------------------------------
# Tool registry — maps tool name → (InputModel, OutputModel)
# Used by the orchestration layer to validate tool I/O at runtime.
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "lookup_patient": (LookupPatientInput, LookupPatientOutput),
    "create_patient": (CreatePatientInput, CreatePatientOutput),
    "search_slots": (SearchSlotsInput, SearchSlotsOutput),
    "book_appointment": (BookAppointmentInput, BookAppointmentOutput),
    "reschedule_appointment": (RescheduleAppointmentInput, RescheduleAppointmentOutput),
    "cancel_appointment": (CancelAppointmentInput, CancelAppointmentOutput),
    "book_family_appointments": (BookFamilyAppointmentsInput, BookFamilyAppointmentsOutput),
    "create_staff_notification": (
        CreateStaffNotificationInput,
        CreateStaffNotificationOutput,
    ),
    "get_clinic_info": (GetClinicInfoInput, GetClinicInfoOutput),
}
