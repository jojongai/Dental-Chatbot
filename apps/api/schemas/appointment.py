"""Appointment-related request/response schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

AppointmentTypeCode = Literal[
    "cleaning",
    "general_checkup",
    "emergency",
    "new_patient_exam",
]

TimeOfDay = Literal["morning", "afternoon", "evening", "after_school", "any"]
GroupPreference = Literal["back_to_back", "same_day", "same_provider", "best_available"]


# ---------------------------------------------------------------------------
# Slot search
# ---------------------------------------------------------------------------


class SlotSearchIn(BaseModel):
    """Input for the search_slots tool / GET /appointments/slots."""

    appointment_type_code: AppointmentTypeCode = Field(..., examples=["cleaning"])
    date_from: date = Field(..., examples=["2026-04-01"])
    date_to: date = Field(..., examples=["2026-04-14"])
    preferred_time_of_day: TimeOfDay = "any"
    provider_type: Literal["dentist", "hygienist"] | None = None
    location_id: str | None = None


class SlotOut(BaseModel):
    """A single bookable slot returned from slot search."""

    id: str
    starts_at: datetime
    ends_at: datetime
    date_label: str = Field(..., examples=["Tuesday, April 8"])
    time_label: str = Field(..., examples=["10:00 AM – 11:00 AM"])
    provider_display_name: str | None
    appointment_type_code: str
    appointment_type_display: str


class SlotSearchOut(BaseModel):
    slots: list[SlotOut]
    total: int
    searched_from: date
    searched_to: date


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


class BookAppointmentIn(BaseModel):
    """Input for the book_appointment tool."""

    patient_id: str
    slot_id: str
    appointment_type_code: AppointmentTypeCode
    reason_for_visit: str | None = None
    is_emergency: bool = False
    # Required when is_emergency=True; triggers a staff notification
    emergency_summary: str | None = Field(
        None,
        description="Brief description of the emergency — staff are notified immediately.",
        examples=["Severe toothache, possible abscess, pain level 8/10"],
    )
    special_instructions: str | None = None
    conversation_id: str | None = None
    booked_via: Literal["chatbot", "staff", "phone", "walk_in"] = "chatbot"


# ---------------------------------------------------------------------------
# Reschedule
# ---------------------------------------------------------------------------


class RescheduleAppointmentIn(BaseModel):
    """Input for the reschedule_appointment tool."""

    appointment_id: str
    new_slot_id: str
    reason: str | None = None


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


class CancelAppointmentIn(BaseModel):
    """Input for the cancel_appointment tool."""

    appointment_id: str
    cancel_reason: str = Field(..., examples=["Schedule conflict"])


# ---------------------------------------------------------------------------
# Family booking
# ---------------------------------------------------------------------------


class FamilyBookingMemberIn(BaseModel):
    """One member's booking request within a family booking."""

    patient_id: str
    appointment_type_code: AppointmentTypeCode
    preferred_time_of_day: TimeOfDay = "any"
    special_instructions: str | None = None


class FamilyBookingIn(BaseModel):
    """
    Groups multiple individual booking requests.
    Each member gets their own appointment; shared group_preference guides slot search.
    """

    members: list[FamilyBookingMemberIn] = Field(..., min_length=2)
    group_preference: GroupPreference = "back_to_back"
    date_from: date
    date_to: date
    conversation_id: str | None = None


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class AppointmentOut(BaseModel):
    """Appointment summary returned after booking / lookup."""

    id: str
    patient_id: str
    patient_name: str
    appointment_type_code: str
    appointment_type_display: str
    status: str
    booked_via: str
    scheduled_starts_at: datetime
    scheduled_ends_at: datetime
    date_label: str
    time_label: str
    provider_display_name: str | None
    location_name: str
    is_emergency: bool
    reason_for_visit: str | None


class FamilyBookingOut(BaseModel):
    """Result of a family booking request — one AppointmentOut per member."""

    appointments: list[AppointmentOut]
    group_preference: str
    all_booked: bool
    partial_failures: list[str] = Field(
        default_factory=list,
        description="patient_ids for whom no slot could be confirmed",
    )
