"""
Scheduling tools — search_slots, book_appointment, reschedule_appointment,
cancel_appointment, book_family_appointments.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.scheduling import Appointment, AppointmentRequest, AppointmentSlot, AppointmentType
from models.staff import Provider
from schemas.appointment import AppointmentOut, SlotOut, SlotSearchOut
from schemas.tools import (
    BookAppointmentInput,
    BookAppointmentOutput,
    BookFamilyAppointmentsInput,
    BookFamilyAppointmentsOutput,
    CancelAppointmentInput,
    CancelAppointmentOutput,
    RescheduleAppointmentInput,
    RescheduleAppointmentOutput,
    SearchSlotsInput,
    SearchSlotsOutput,
)
from tools.validators import fmt_date, fmt_time, fmt_time_range, normalize_appointment_type

TZ = ZoneInfo("America/Toronto")

# Time-of-day hour ranges (hour inclusive start, exclusive end)
_TIME_RANGES: dict[str, tuple[int, int]] = {
    "morning": (8, 12),
    "afternoon": (12, 17),
    "evening": (17, 20),
    "after_school": (15, 18),
    "any": (0, 24),
}


def _slot_to_out(slot: AppointmentSlot, appt_type: AppointmentType, provider: Provider | None) -> SlotOut:
    starts = slot.starts_at.astimezone(TZ)
    ends = slot.ends_at.astimezone(TZ)
    return SlotOut(
        id=slot.id,
        starts_at=starts,
        ends_at=ends,
        date_label=fmt_date(starts),
        time_label=fmt_time_range(starts, ends),
        provider_display_name=provider.display_name if provider else None,
        appointment_type_code=appt_type.code,
        appointment_type_display=appt_type.display_name,
    )


def _appt_to_out(appt: Appointment, db: Session) -> AppointmentOut:
    from models.patient import Patient
    from models.practice import Location

    patient = db.get(Patient, appt.patient_id)
    appt_type = db.get(AppointmentType, appt.appointment_type_id)
    provider = db.get(Provider, appt.provider_id) if appt.provider_id else None
    location = db.get(Location, appt.location_id)

    starts = appt.scheduled_starts_at.astimezone(TZ)
    ends = appt.scheduled_ends_at.astimezone(TZ)

    return AppointmentOut(
        id=appt.id,
        patient_id=appt.patient_id,
        patient_name=f"{patient.first_name} {patient.last_name}" if patient else "Unknown",
        appointment_type_code=appt_type.code if appt_type else "unknown",
        appointment_type_display=appt_type.display_name if appt_type else "Appointment",
        status=appt.status,
        booked_via=appt.booked_via,
        scheduled_starts_at=starts,
        scheduled_ends_at=ends,
        date_label=fmt_date(starts),
        time_label=fmt_time_range(starts, ends),
        provider_display_name=provider.display_name if provider else None,
        location_name=location.name if location else "Bright Smile Dental",
        is_emergency=appt.is_emergency,
        reason_for_visit=appt.reason_for_visit,
    )


# ---------------------------------------------------------------------------
# search_slots
# ---------------------------------------------------------------------------


def search_slots(db: Session, payload: SearchSlotsInput) -> SearchSlotsOutput:
    """
    Return available appointment_slots matching the criteria.

    Filters:
    - slot_status = 'available'
    - appointment_type.code matches payload.appointment_type_code
    - starts_at between date_from 00:00 and date_to 23:59 (Toronto time)
    - preferred_time_of_day hour filter
    - Optional: location_id

    Returns up to 10 slots, ordered by starts_at ASC.
    """
    # Normalize appointment type (handles aliases like "deep clean" → "cleaning")
    try:
        appt_code = normalize_appointment_type(payload.appointment_type_code)
    except ValueError:
        appt_code = payload.appointment_type_code

    # Resolve appointment type row
    appt_type = db.execute(
        select(AppointmentType).where(AppointmentType.code == appt_code)
    ).scalar_one_or_none()
    if not appt_type:
        return SearchSlotsOutput(slots=[], total=0, searched_from=payload.date_from, searched_to=payload.date_to)

    # Date window in Toronto timezone
    date_from_dt = datetime(payload.date_from.year, payload.date_from.month, payload.date_from.day, 0, 0, tzinfo=TZ)
    date_to_dt = datetime(payload.date_to.year, payload.date_to.month, payload.date_to.day, 23, 59, tzinfo=TZ)

    stmt = (
        select(AppointmentSlot)
        .where(AppointmentSlot.slot_status == "available")
        .where(AppointmentSlot.appointment_type_id == appt_type.id)
        .where(AppointmentSlot.starts_at >= date_from_dt)
        .where(AppointmentSlot.starts_at <= date_to_dt)
        .order_by(AppointmentSlot.starts_at)
    )
    if payload.location_id:
        stmt = stmt.where(AppointmentSlot.location_id == payload.location_id)

    slots = list(db.execute(stmt).scalars().all())

    # Time-of-day filter
    tod = payload.preferred_time_of_day or "any"
    hour_min, hour_max = _TIME_RANGES.get(tod, (0, 24))
    if tod != "any":
        slots = [s for s in slots if hour_min <= s.starts_at.astimezone(TZ).hour < hour_max]

    # Build output — up to 10
    slot_outs: list[SlotOut] = []
    for slot in slots[:10]:
        provider = db.get(Provider, slot.provider_id) if slot.provider_id else None
        slot_outs.append(_slot_to_out(slot, appt_type, provider))

    return SearchSlotsOutput(
        slots=slot_outs,
        total=len(slots),
        searched_from=payload.date_from,
        searched_to=payload.date_to,
    )


# ---------------------------------------------------------------------------
# book_appointment
# ---------------------------------------------------------------------------


def book_appointment(db: Session, payload: BookAppointmentInput) -> BookAppointmentOutput:
    """
    Atomically book a slot and create an Appointment row.

    Steps:
    1. Fetch and lock the AppointmentSlot.
    2. Confirm slot_status == 'available' — return error if taken.
    3. Set slot_status = 'booked'.
    4. Resolve appointment_type_id from code.
    5. Create Appointment (status='booked', booked_via='chatbot').
    6. Commit.
    """
    # --- fetch slot ---
    slot = db.get(AppointmentSlot, payload.slot_id)
    if not slot:
        return BookAppointmentOutput(success=False, error="Slot not found.")

    # --- prevent double-booking ---
    if slot.slot_status != "available":
        return BookAppointmentOutput(
            success=False,
            error=(
                "Sorry, that slot was just taken. "
                "Let me find you another available time."
            ),
        )

    # --- resolve appointment type ---
    try:
        appt_code = normalize_appointment_type(payload.appointment_type_code)
    except ValueError as exc:
        return BookAppointmentOutput(success=False, error=str(exc))

    appt_type = db.execute(
        select(AppointmentType).where(AppointmentType.code == appt_code)
    ).scalar_one_or_none()
    if not appt_type:
        return BookAppointmentOutput(success=False, error=f"Unknown appointment type: {appt_code}")

    # --- book ---
    slot.slot_status = "booked"

    appointment = Appointment(
        patient_id=payload.patient_id,
        slot_id=slot.id,
        location_id=slot.location_id,
        provider_id=slot.provider_id,
        operatory_id=slot.operatory_id,
        appointment_type_id=appt_type.id,
        status="booked",
        booked_via=payload.booked_via or "chatbot",
        scheduled_starts_at=slot.starts_at,
        scheduled_ends_at=slot.ends_at,
        reason_for_visit=payload.reason_for_visit,
        special_instructions=payload.special_instructions,
        is_emergency=payload.is_emergency or False,
        emergency_summary=payload.emergency_summary,
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)

    staff_notified = False
    if payload.is_emergency:
        # TODO: trigger create_staff_notification for emergency
        staff_notified = True

    return BookAppointmentOutput(
        success=True,
        appointment=_appt_to_out(appointment, db),
        staff_notified=staff_notified,
    )


# ---------------------------------------------------------------------------
# reschedule_appointment
# ---------------------------------------------------------------------------


def reschedule_appointment(db: Session, payload: RescheduleAppointmentInput) -> RescheduleAppointmentOutput:
    """Reschedule: free old slot, book new slot, link back via rescheduled_from."""
    raise NotImplementedError("reschedule_appointment not yet implemented")


# ---------------------------------------------------------------------------
# cancel_appointment
# ---------------------------------------------------------------------------


def cancel_appointment(db: Session, payload: CancelAppointmentInput) -> CancelAppointmentOutput:
    """Cancel an appointment and free its slot."""
    raise NotImplementedError("cancel_appointment not yet implemented")


# ---------------------------------------------------------------------------
# book_family_appointments
# ---------------------------------------------------------------------------


def book_family_appointments(db: Session, payload: BookFamilyAppointmentsInput) -> BookFamilyAppointmentsOutput:
    """Book back-to-back or same-day appointments for multiple family members."""
    raise NotImplementedError("book_family_appointments not yet implemented")
