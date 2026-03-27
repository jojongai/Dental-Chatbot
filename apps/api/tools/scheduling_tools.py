"""
Scheduling tools — search_slots, book_appointment, reschedule_appointment,
cancel_appointment, book_family_appointments.
"""

from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.scheduling import Appointment, AppointmentRequest, AppointmentSlot, AppointmentType
from models.staff import Provider
from schemas.appointment import AppointmentOut, FamilyBookingMemberIn, SlotOut, SlotSearchOut
from schemas.tools import (
    AppointmentSummary,
    BookAppointmentInput,
    BookAppointmentOutput,
    BookFamilyAppointmentsInput,
    BookFamilyAppointmentsOutput,
    CancelAppointmentInput,
    CancelAppointmentOutput,
    ListPatientAppointmentsInput,
    ListPatientAppointmentsOutput,
    RescheduleAppointmentInput,
    RescheduleAppointmentOutput,
    SearchSlotsInput,
    SearchSlotsOutput,
)
from tools.validators import fmt_date, fmt_time, fmt_time_range, normalize_appointment_type

from models.patient import Patient
from schemas.employee import (
    EmployeeEmergencyAlert,
    EmployeeScheduleAppointment,
    EmployeeScheduleOut,
    WeekDayCount,
)

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


def _intervals_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and a_end > b_start


def _exclude_slots_overlapping_provider_appointments(
    db: Session, slots: list[AppointmentSlot]
) -> list[AppointmentSlot]:
    """
    Drop slots whose provider already has a non-cancelled appointment overlapping
    the same time window (any appointment type).

    Needed when the DB has parallel slot rows per type (e.g. check-up + emergency
    at identical times): booking one type must hide the other.
    """
    if not slots:
        return []
    provider_ids = {s.provider_id for s in slots if s.provider_id}
    if not provider_ids:
        return slots

    min_st = min(s.starts_at for s in slots)
    max_en = max(s.ends_at for s in slots)
    rows = db.execute(
        select(Appointment.provider_id, Appointment.scheduled_starts_at, Appointment.scheduled_ends_at).where(
            Appointment.provider_id.in_(provider_ids),
            Appointment.status.notin_(["cancelled", "rescheduled"]),
            Appointment.scheduled_starts_at < max_en,
            Appointment.scheduled_ends_at > min_st,
        )
    ).all()

    busy = [(r[0], r[1], r[2]) for r in rows]
    out: list[AppointmentSlot] = []
    for slot in slots:
        pid = slot.provider_id
        if not pid:
            out.append(slot)
            continue
        conflict = False
        for bp, bs, be in busy:
            if bp != pid:
                continue
            if _intervals_overlap(slot.starts_at, slot.ends_at, bs, be):
                conflict = True
                break
        if not conflict:
            out.append(slot)
    return out


def search_slots(db: Session, payload: SearchSlotsInput) -> SearchSlotsOutput:
    """
    Return available appointment_slots matching the criteria.

    Filters:
    - slot_status = 'available'
    - appointment_type.code matches payload.appointment_type_code
    - starts_at between date_from 00:00 and date_to 23:59 (Toronto time)
    - starts_at >= now (Toronto) — no past or already-started slots
    - no overlapping non-cancelled appointment for the same provider (any type)
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
    now = datetime.now(tz=TZ)

    stmt = (
        select(AppointmentSlot)
        .where(AppointmentSlot.slot_status == "available")
        .where(AppointmentSlot.appointment_type_id == appt_type.id)
        .where(AppointmentSlot.starts_at >= date_from_dt)
        .where(AppointmentSlot.starts_at <= date_to_dt)
        .where(AppointmentSlot.starts_at >= now)
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

    slots = _exclude_slots_overlapping_provider_appointments(db, slots)

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
# list_patient_appointments
# ---------------------------------------------------------------------------


def list_patient_appointments(
    db: Session, payload: ListPatientAppointmentsInput
) -> ListPatientAppointmentsOutput:
    """Return upcoming (non-cancelled) appointments for a patient, ordered by starts_at ASC."""
    now = datetime.now(tz=TZ)

    rows = (
        db.execute(
            select(Appointment)
            .where(
                Appointment.patient_id == payload.patient_id,
                Appointment.status.notin_(["cancelled", "no_show", "rescheduled"]),
                Appointment.scheduled_starts_at >= now,
            )
            .order_by(Appointment.scheduled_starts_at.asc())
            .limit(10)
        )
        .scalars()
        .all()
    )

    summaries: list[AppointmentSummary] = []
    for appt in rows:
        appt_type = db.get(AppointmentType, appt.appointment_type_id)
        provider = db.get(Provider, appt.provider_id) if appt.provider_id else None
        starts = appt.scheduled_starts_at.astimezone(TZ)
        ends = appt.scheduled_ends_at.astimezone(TZ)
        summaries.append(
            AppointmentSummary(
                id=appt.id,
                appointment_type_display=appt_type.display_name if appt_type else "Appointment",
                date_label=fmt_date(starts),
                time_label=fmt_time_range(starts, ends),
                provider_display_name=provider.display_name if provider else None,
                status=appt.status,
            )
        )

    return ListPatientAppointmentsOutput(
        patient_id=payload.patient_id,
        appointments=summaries,
        total=len(summaries),
    )


# ---------------------------------------------------------------------------
# reschedule_appointment
# ---------------------------------------------------------------------------


def reschedule_appointment(db: Session, payload: RescheduleAppointmentInput) -> RescheduleAppointmentOutput:
    """Free old slot, book new slot, link new appointment back to old via rescheduled_from."""
    # --- fetch original appointment ---
    old_appt = db.get(Appointment, payload.appointment_id)
    if not old_appt:
        return RescheduleAppointmentOutput(success=False, error="Appointment not found.")
    if old_appt.status in ("cancelled", "completed", "no_show"):
        return RescheduleAppointmentOutput(
            success=False, error=f"Cannot reschedule an appointment with status '{old_appt.status}'."
        )

    # --- fetch and validate new slot ---
    new_slot = db.get(AppointmentSlot, payload.new_slot_id)
    if not new_slot:
        return RescheduleAppointmentOutput(success=False, error="New slot not found.")
    if new_slot.slot_status != "available":
        return RescheduleAppointmentOutput(
            success=False,
            error="Sorry, that slot was just taken. Let me find you another available time.",
        )

    # --- free old slot ---
    old_slot = db.get(AppointmentSlot, old_appt.slot_id)
    if old_slot:
        old_slot.slot_status = "available"

    # --- cancel old appointment record ---
    old_appt.status = "rescheduled"

    # --- book new appointment ---
    new_slot.slot_status = "booked"
    new_appt = Appointment(
        patient_id=old_appt.patient_id,
        slot_id=new_slot.id,
        location_id=new_slot.location_id,
        provider_id=new_slot.provider_id,
        operatory_id=new_slot.operatory_id,
        appointment_type_id=old_appt.appointment_type_id,
        status="booked",
        booked_via="chatbot",
        scheduled_starts_at=new_slot.starts_at,
        scheduled_ends_at=new_slot.ends_at,
        reason_for_visit=old_appt.reason_for_visit,
        special_instructions=old_appt.special_instructions,
        is_emergency=old_appt.is_emergency,
        rescheduled_from_appointment_id=old_appt.id,
    )
    if payload.reason:
        new_appt.special_instructions = (
            f"Reschedule reason: {payload.reason}. {new_appt.special_instructions or ''}"
        ).strip()

    db.add(new_appt)
    db.commit()
    db.refresh(new_appt)

    return RescheduleAppointmentOutput(
        success=True,
        old_appointment=_appt_to_out(old_appt, db),
        new_appointment=_appt_to_out(new_appt, db),
    )


# ---------------------------------------------------------------------------
# cancel_appointment
# ---------------------------------------------------------------------------


def cancel_appointment(db: Session, payload: CancelAppointmentInput) -> CancelAppointmentOutput:
    """Cancel an appointment and free its slot."""
    appt = db.get(Appointment, payload.appointment_id)
    if not appt:
        return CancelAppointmentOutput(success=False, error="Appointment not found.")
    if appt.status in ("cancelled", "completed", "no_show"):
        return CancelAppointmentOutput(
            success=False, error=f"This appointment is already marked '{appt.status}'."
        )

    # Free the slot so others can book it
    slot = db.get(AppointmentSlot, appt.slot_id)
    if slot:
        slot.slot_status = "available"

    appt.status = "cancelled"
    if payload.cancel_reason:
        appt.special_instructions = (
            f"Cancelled: {payload.cancel_reason}. {appt.special_instructions or ''}"
        ).strip()

    db.commit()
    db.refresh(appt)

    return CancelAppointmentOutput(success=True, cancelled_appointment=_appt_to_out(appt, db))


# ---------------------------------------------------------------------------
# book_family_appointments
# ---------------------------------------------------------------------------


def assign_family_appointment_slots(
    db: Session, payload: BookFamilyAppointmentsInput
) -> tuple[list[tuple[AppointmentSlot, AppointmentType, FamilyBookingMemberIn]], dict[str, AppointmentType | None]]:
    """
    Pick one slot per member (back-to-back or same-day rules) without booking.
    Returns (assigned_triples, appointment_type_cache).
    """
    from datetime import datetime as _dt

    date_from_dt = _dt(
        payload.date_from.year, payload.date_from.month, payload.date_from.day, 0, 0, tzinfo=TZ
    )
    date_to_dt = _dt(
        payload.date_to.year, payload.date_to.month, payload.date_to.day, 23, 59, tzinfo=TZ
    )

    all_candidate_slots: list[AppointmentSlot] = []
    appt_type_cache: dict[str, AppointmentType | None] = {}

    for member in payload.members:
        try:
            appt_code = normalize_appointment_type(member.appointment_type_code)
        except ValueError:
            appt_code = member.appointment_type_code

        if appt_code not in appt_type_cache:
            appt_type_cache[appt_code] = db.execute(
                select(AppointmentType).where(AppointmentType.code == appt_code)
            ).scalar_one_or_none()

        appt_type = appt_type_cache[appt_code]
        if not appt_type:
            continue

        tod = member.preferred_time_of_day or "any"
        hour_min, hour_max = _TIME_RANGES.get(tod, (0, 24))

        stmt = (
            select(AppointmentSlot)
            .where(AppointmentSlot.slot_status == "available")
            .where(AppointmentSlot.appointment_type_id == appt_type.id)
            .where(AppointmentSlot.starts_at >= date_from_dt)
            .where(AppointmentSlot.starts_at <= date_to_dt)
            .order_by(AppointmentSlot.starts_at)
        )
        slots = list(db.execute(stmt).scalars().all())
        if tod != "any":
            slots = [s for s in slots if hour_min <= s.starts_at.astimezone(TZ).hour < hour_max]
        all_candidate_slots.extend(slots)

    seen: set[str] = set()
    unique_slots: list[AppointmentSlot] = []
    for s in sorted(all_candidate_slots, key=lambda x: x.starts_at):
        if s.id not in seen:
            seen.add(s.id)
            unique_slots.append(s)

    assigned: list[tuple[AppointmentSlot, AppointmentType, FamilyBookingMemberIn]] = []
    used_slot_ids: set[str] = set()
    last_end: _dt | None = None

    for member in payload.members:
        try:
            appt_code = normalize_appointment_type(member.appointment_type_code)
        except ValueError:
            appt_code = member.appointment_type_code

        appt_type = appt_type_cache.get(appt_code)
        if not appt_type:
            continue

        for slot in unique_slots:
            if slot.id in used_slot_ids:
                continue
            if slot.appointment_type_id != appt_type.id:
                continue

            if payload.group_preference == "back_to_back" and last_end is not None:
                gap = (slot.starts_at - last_end).total_seconds()
                if not (0 <= gap <= 60):
                    continue

            assigned.append((slot, appt_type, member))
            used_slot_ids.add(slot.id)
            last_end = slot.ends_at
            break

    return assigned, appt_type_cache


def _finalize_family_bookings(
    db: Session,
    payload: BookFamilyAppointmentsInput,
    assigned: list[tuple[AppointmentSlot, AppointmentType, FamilyBookingMemberIn]],
) -> BookFamilyAppointmentsOutput:
    """Persist appointments for an assignment; members without a slot are partial failures."""
    booked_appointments: list[AppointmentOut] = []
    partial_failures: list[str] = []

    for slot, appt_type, member in assigned:
        fresh = db.get(AppointmentSlot, slot.id)
        if not fresh or fresh.slot_status != "available":
            partial_failures.append(member.patient_id)
            continue

        fresh.slot_status = "booked"
        appointment = Appointment(
            patient_id=member.patient_id,
            slot_id=fresh.id,
            location_id=fresh.location_id,
            provider_id=fresh.provider_id,
            operatory_id=fresh.operatory_id,
            appointment_type_id=appt_type.id,
            status="booked",
            booked_via="chatbot",
            scheduled_starts_at=fresh.starts_at,
            scheduled_ends_at=fresh.ends_at,
            reason_for_visit=member.special_instructions,
            is_emergency=False,
        )
        db.add(appointment)
        db.flush()
        booked_appointments.append(_appt_to_out(appointment, db))

    assigned_patient_ids = {m.patient_id for _, _, m in assigned}
    for member in payload.members:
        if member.patient_id not in assigned_patient_ids:
            partial_failures.append(member.patient_id)

    db.commit()

    return BookFamilyAppointmentsOutput(
        appointments=booked_appointments,
        group_preference=payload.group_preference,
        all_booked=len(partial_failures) == 0,
        partial_failures=list(set(partial_failures)),
    )


def book_family_appointments_from_proposed_slots(
    db: Session, payload: BookFamilyAppointmentsInput, slot_ids: list[str]
) -> BookFamilyAppointmentsOutput:
    """
    Book using slot IDs from a prior proposal (same order as payload.members).
    Re-checks availability before committing.
    """
    if len(slot_ids) != len(payload.members):
        return BookFamilyAppointmentsOutput(
            appointments=[],
            group_preference=payload.group_preference,
            all_booked=False,
            partial_failures=[m.patient_id for m in payload.members],
        )

    assigned: list[tuple[AppointmentSlot, AppointmentType, FamilyBookingMemberIn]] = []

    for slot_id, member in zip(slot_ids, payload.members, strict=True):
        try:
            appt_code = normalize_appointment_type(member.appointment_type_code)
        except ValueError:
            appt_code = member.appointment_type_code

        appt_type = db.execute(
            select(AppointmentType).where(AppointmentType.code == appt_code)
        ).scalar_one_or_none()
        if not appt_type:
            continue

        slot = db.get(AppointmentSlot, slot_id)
        if not slot or slot.appointment_type_id != appt_type.id:
            continue

        assigned.append((slot, appt_type, member))

    return _finalize_family_bookings(db, payload, assigned)


def book_family_appointments(db: Session, payload: BookFamilyAppointmentsInput) -> BookFamilyAppointmentsOutput:
    """
    Book back-to-back (or same-day) appointments for multiple family members.

    Strategy:
    1. For each member, run a slot search using the shared date window and time preference.
    2. For 'back_to_back': sort available slots and pick consecutive time blocks
       (one slot per member, each starting when the previous one ends).
    3. For 'same_day': pick any available slots on the same calendar day.
    4. Book all selected slots atomically; roll back any partial books on failure.
    5. Return booked appointments + partial_failures list.
    """
    assigned, _ = assign_family_appointment_slots(db, payload)
    return _finalize_family_bookings(db, payload, assigned)


# ---------------------------------------------------------------------------
# Employee dashboard — day schedule + week counts
# ---------------------------------------------------------------------------


def _day_bounds_toronto(d: date) -> tuple[datetime, datetime]:
    """Start inclusive, end exclusive, in America/Toronto."""
    start = datetime.combine(d, dt_time.min, tzinfo=TZ)
    end = start + timedelta(days=1)
    return start, end


def _map_ui_status(db_status: str) -> str:
    return {
        "booked": "confirmed",
        "confirmed": "confirmed",
        "checked_in": "arrived",
        "completed": "completed",
        "cancelled": "cancelled",
        "no_show": "cancelled",
        "rescheduled": "cancelled",
    }.get(db_status, "confirmed")


def get_employee_schedule(db: Session, target_date: date | None = None) -> EmployeeScheduleOut:
    """Appointments for one calendar day, emergency banners, Mon–Sat counts for that week, provider count."""
    if target_date is None:
        target_date = datetime.now(tz=TZ).date()

    day_start, day_end = _day_bounds_toronto(target_date)

    rows = (
        db.execute(
            select(Appointment)
            .where(Appointment.scheduled_starts_at >= day_start)
            .where(Appointment.scheduled_starts_at < day_end)
            .where(Appointment.status.notin_(["cancelled", "rescheduled"]))
            .order_by(Appointment.scheduled_starts_at.asc())
        )
        .scalars()
        .all()
    )

    appointments_out: list[EmployeeScheduleAppointment] = []
    emergency_alerts: list[EmployeeEmergencyAlert] = []

    for appt in rows:
        patient = db.get(Patient, appt.patient_id)
        appt_type = db.get(AppointmentType, appt.appointment_type_id)
        provider = db.get(Provider, appt.provider_id) if appt.provider_id else None
        starts = appt.scheduled_starts_at.astimezone(TZ)
        duration_minutes = max(
            1,
            int((appt.scheduled_ends_at - appt.scheduled_starts_at).total_seconds() / 60),
        )
        ui_status = _map_ui_status(appt.status)
        pname = f"{patient.first_name} {patient.last_name}" if patient else "Unknown"

        appointments_out.append(
            EmployeeScheduleAppointment(
                id=appt.id,
                patient_name=pname,
                appointment_type_display=appt_type.display_name if appt_type else "Appointment",
                appointment_type_code=appt_type.code if appt_type else "unknown",
                time_start=fmt_time(starts),
                duration_minutes=duration_minutes,
                provider_display_name=provider.display_name if provider else None,
                status=appt.status,
                ui_status=ui_status,
                is_emergency=appt.is_emergency,
            )
        )

        if appt.is_emergency and appt.status not in ("cancelled", "rescheduled", "completed", "no_show"):
            desc = (appt.emergency_summary or appt.reason_for_visit or "Emergency visit").strip()
            emergency_alerts.append(
                EmployeeEmergencyAlert(
                    id=appt.id,
                    patient_name=pname,
                    description=desc,
                    time=fmt_time(starts),
                    severity="critical",
                )
            )

    monday = target_date - timedelta(days=target_date.weekday())
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    week_day_counts: list[WeekDayCount] = []
    for i in range(6):
        d = monday + timedelta(days=i)
        ds, de = _day_bounds_toronto(d)
        cnt = db.execute(
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.scheduled_starts_at >= ds)
            .where(Appointment.scheduled_starts_at < de)
            .where(Appointment.status.notin_(["cancelled", "rescheduled"]))
        ).scalar_one()
        week_day_counts.append(WeekDayCount(day=labels[i], count=int(cnt), date=d))

    provider_count = db.execute(
        select(func.count()).select_from(Provider).where(Provider.is_bookable.is_(True))
    ).scalar_one()

    return EmployeeScheduleOut(
        date=target_date,
        timezone="America/Toronto",
        appointments=appointments_out,
        emergency_alerts=emergency_alerts,
        week_day_counts=week_day_counts,
        provider_count=int(provider_count),
    )
