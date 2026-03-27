"""
End-to-end tests for the new patient booking flow.

Uses an in-memory SQLite database seeded with minimal fixture data so every
real DB call (create_patient, search_slots, book_appointment) can succeed.
No Gemini API calls are made (USE_LLM=false via conftest).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Must be set before any app import
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["USE_LLM"] = "false"

from models.base import Base
from models.content import ClinicSettings
from models.patient import InsurancePlan, Patient
from models.practice import Location, Practice
from models.scheduling import AppointmentSlot, AppointmentType
from models.staff import Provider
from tools.patient_tools import create_patient, lookup_patient
from tools.scheduling_tools import book_appointment, search_slots
from tools.validators import normalize_appointment_type

from schemas.tools import (
    BookAppointmentInput,
    CreatePatientInput,
    LookupPatientInput,
    SearchSlotsInput,
)

TZ = ZoneInfo("America/Toronto")

# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def db() -> Session:  # type: ignore[return]
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    session = Session_()
    _seed(session)
    yield session
    session.close()
    engine.dispose()


def _seed(db: Session) -> None:
    """Minimal fixture data for new-patient booking tests."""
    practice = Practice(id="p1", name="bright_smile", display_name="Bright Smile Dental", timezone="America/Toronto")
    db.add(practice)
    db.flush()

    location = Location(
        id="loc1",
        practice_id=practice.id,
        name="Downtown Toronto",
        address_line_1="123 King St W",
        city="Toronto",
        province="ON",
        postal_code="M5H 1J9",
        phone_number="(416) 555-0100",
        is_primary=True,
    )
    db.add(location)

    provider = Provider(
        id="prov1",
        location_id=location.id,
        provider_type="hygienist",
        display_name="Dr. Smith",
        is_bookable=True,
    )
    db.add(provider)

    at_cleaning = AppointmentType(
        id="at1",
        practice_id=practice.id,
        code="cleaning",
        display_name="Teeth Cleaning",
        default_duration_minutes=60,
        requires_provider_type="hygienist",
        is_emergency=False,
    )
    db.add(at_cleaning)
    db.flush()

    # Generate 3 available slots next week
    start_day = date.today() + timedelta(days=7)
    for i in range(3):
        day = start_day + timedelta(days=i)
        starts = datetime(day.year, day.month, day.day, 10 + i, 0, tzinfo=TZ)
        ends = starts + timedelta(hours=1)
        db.add(AppointmentSlot(
            id=f"slot{i+1}",
            location_id=location.id,
            provider_id=provider.id,
            appointment_type_id=at_cleaning.id,
            starts_at=starts,
            ends_at=ends,
            slot_status="available",
        ))

    db.add(ClinicSettings(
        practice_id=practice.id,
        default_location_id=location.id,
        accepts_major_insurance=True,
        self_pay_available=True,
        membership_available=True,
        financing_available=True,
        emergency_escalation_enabled=True,
    ))

    db.add(InsurancePlan(
        id="ins1",
        practice_id=practice.id,
        carrier_name="Sun Life",
        plan_name="Personal Health Insurance",
        plan_code="SL-PHI",
        acceptance_status="accepted",
    ))

    db.commit()


# ---------------------------------------------------------------------------
# Validator unit tests
# ---------------------------------------------------------------------------


def test_normalize_phone_strips_formatting() -> None:
    assert normalize_appointment_type("deep clean") == "cleaning"
    assert normalize_appointment_type("checkup") == "general_checkup"
    assert normalize_appointment_type("emergency") == "emergency"
    assert normalize_appointment_type("new patient exam") == "new_patient_exam"


def test_normalize_phone_raises_on_bad_input() -> None:
    from tools.validators import normalize_phone

    with pytest.raises(ValueError, match="10 digits"):
        normalize_phone("123")


def test_normalize_phone_nanp() -> None:
    from tools.validators import normalize_phone

    assert normalize_phone("+1 416-555-1234") == "4165551234"
    assert normalize_phone("(416) 555-1234") == "4165551234"


# ---------------------------------------------------------------------------
# create_patient
# ---------------------------------------------------------------------------


def test_create_patient_success(db: Session) -> None:
    result = create_patient(
        db,
        CreatePatientInput(
            first_name="Jane",
            last_name="Doe",
            phone_number="(416) 555-9900",
            date_of_birth=date(1990, 5, 15),
        ),
        practice_id="p1",
    )
    assert result.success
    assert result.patient is not None
    assert result.patient.first_name == "Jane"
    assert result.patient.status == "lead"


def test_create_patient_links_insurance(db: Session) -> None:
    result = create_patient(
        db,
        CreatePatientInput(
            first_name="Bob",
            last_name="Smith",
            phone_number="(416) 555-8800",
            date_of_birth=date(1985, 3, 10),
            insurance_name="Sun Life",
        ),
        practice_id="p1",
    )
    assert result.success
    assert result.patient is not None
    assert result.patient.primary_insurance == "Sun Life"


def test_create_patient_invalid_phone(db: Session) -> None:
    result = create_patient(
        db,
        CreatePatientInput(
            first_name="Bad",
            last_name="Phone",
            phone_number="123",
            date_of_birth=date(1990, 1, 1),
        ),
        practice_id="p1",
    )
    assert not result.success
    assert result.error is not None
    assert "10 digits" in result.error


def test_create_patient_future_dob(db: Session) -> None:
    result = create_patient(
        db,
        CreatePatientInput(
            first_name="Future",
            last_name="Person",
            phone_number="(416) 555-7700",
            date_of_birth=date.today() + timedelta(days=1),
        ),
        practice_id="p1",
    )
    assert not result.success
    assert result.error is not None


def test_create_patient_duplicate_phone(db: Session) -> None:
    create_patient(
        db,
        CreatePatientInput(
            first_name="Alice",
            last_name="One",
            phone_number="(416) 999-1111",
            date_of_birth=date(1988, 1, 1),
        ),
        practice_id="p1",
    )
    result2 = create_patient(
        db,
        CreatePatientInput(
            first_name="Alice",
            last_name="Two",
            phone_number="4169991111",  # same digits, different format
            date_of_birth=date(1992, 6, 1),
        ),
        practice_id="p1",
    )
    assert not result2.success
    assert "already exists" in (result2.error or "")


# ---------------------------------------------------------------------------
# search_slots
# ---------------------------------------------------------------------------


def test_search_slots_returns_available(db: Session) -> None:
    date_from = date.today() + timedelta(days=6)
    result = search_slots(
        db,
        SearchSlotsInput(
            appointment_type_code="cleaning",
            date_from=date_from,
            date_to=date_from + timedelta(days=14),
        ),
    )
    assert len(result.slots) == 3
    for slot in result.slots:
        assert slot.appointment_type_code == "cleaning"
        assert slot.id.startswith("slot")


def test_search_slots_time_of_day_filter(db: Session) -> None:
    date_from = date.today() + timedelta(days=6)
    # Slots are at 10, 11, 12 AM — "morning" should only return 10 and 11
    result = search_slots(
        db,
        SearchSlotsInput(
            appointment_type_code="cleaning",
            date_from=date_from,
            date_to=date_from + timedelta(days=14),
            preferred_time_of_day="morning",
        ),
    )
    for slot in result.slots:
        assert slot.starts_at.hour < 12


def test_search_slots_no_match_returns_empty(db: Session) -> None:
    result = search_slots(
        db,
        SearchSlotsInput(
            appointment_type_code="emergency",
            date_from=date.today(),
            date_to=date.today() + timedelta(days=7),
        ),
    )
    assert result.slots == []


def test_search_slots_excludes_past_start_times(db: Session) -> None:
    """Same-day slots that already started must not be offered (Toronto time)."""
    slot1 = db.get(AppointmentSlot, "slot1")
    assert slot1 is not None
    past_start = datetime.now(TZ) - timedelta(hours=3)
    past_end = past_start + timedelta(hours=1)
    db.add(
        AppointmentSlot(
            id="slot_past",
            location_id=slot1.location_id,
            provider_id=slot1.provider_id,
            appointment_type_id=slot1.appointment_type_id,
            starts_at=past_start,
            ends_at=past_end,
            slot_status="available",
        )
    )
    db.commit()

    result = search_slots(
        db,
        SearchSlotsInput(
            appointment_type_code="cleaning",
            date_from=past_start.date(),
            date_to=past_start.date() + timedelta(days=1),
        ),
    )
    assert "slot_past" not in {s.id for s in result.slots}


def test_search_slots_hides_parallel_type_when_provider_busy(db: Session) -> None:
    """Emergency slot row at same time as a booked cleaning must not appear as free."""
    slot1 = db.get(AppointmentSlot, "slot1")
    assert slot1 is not None

    at_em = AppointmentType(
        id="at_em",
        practice_id="p1",
        code="emergency",
        display_name="Emergency",
        default_duration_minutes=60,
        requires_provider_type="hygienist",
        is_emergency=True,
    )
    db.add(at_em)
    db.flush()

    em_slot = AppointmentSlot(
        id="slot_em_overlap",
        location_id=slot1.location_id,
        provider_id=slot1.provider_id,
        appointment_type_id=at_em.id,
        starts_at=slot1.starts_at,
        ends_at=slot1.ends_at,
        slot_status="available",
    )
    db.add(em_slot)
    db.commit()

    pat = create_patient(
        db,
        CreatePatientInput(
            first_name="Busy",
            last_name="Provider",
            phone_number="(416) 555-9999",
            date_of_birth=date(1991, 4, 4),
        ),
        practice_id="p1",
    )
    assert pat.success and pat.patient

    book_result = book_appointment(
        db,
        BookAppointmentInput(
            patient_id=pat.patient.id,
            slot_id="slot1",
            appointment_type_code="cleaning",
        ),
    )
    assert book_result.success

    result = search_slots(
        db,
        SearchSlotsInput(
            appointment_type_code="emergency",
            date_from=slot1.starts_at.date(),
            date_to=slot1.starts_at.date() + timedelta(days=14),
        ),
    )
    assert "slot_em_overlap" not in {s.id for s in result.slots}


def test_emergency_slot_selection_creates_patient_when_state_has_no_patient_id(db: Session) -> None:
    """Emergency triage collects identity but may omit patient_id — slot pick must still book."""
    from routers.chat import _handle_slot_selection
    from schemas.chat import Workflow, WorkflowState

    slot1 = db.get(AppointmentSlot, "slot1")
    assert slot1 is not None

    at_em = AppointmentType(
        id="at_em_book",
        practice_id="p1",
        code="emergency",
        display_name="Emergency",
        default_duration_minutes=60,
        requires_provider_type="hygienist",
        is_emergency=True,
    )
    db.add(at_em)
    db.flush()

    em_slot = AppointmentSlot(
        id="slot_em_book",
        location_id=slot1.location_id,
        provider_id=slot1.provider_id,
        appointment_type_id=at_em.id,
        starts_at=slot1.starts_at + timedelta(days=1),
        ends_at=slot1.ends_at + timedelta(days=1),
        slot_status="available",
    )
    db.add(em_slot)
    db.commit()

    state = WorkflowState(
        workflow=Workflow.EMERGENCY_TRIAGE,
        step="selecting_slot",
        patient_id=None,
        slot_options=[{"id": "slot_em_book", "label": "Emergency slot"}],
        collected_fields={
            "first_name": "Eve",
            "last_name": "Urgent",
            "phone_number": "4165558888",
            "emergency_summary": "Severe tooth pain",
            "_is_emergency": True,
            "appointment_type": "emergency",
        },
    )
    response = _handle_slot_selection("1", state, db, "p1")
    assert response.state.patient_id
    low = response.reply.lower()
    assert "confirm" in low or "set" in low or "see you" in low


# ---------------------------------------------------------------------------
# book_appointment
# ---------------------------------------------------------------------------


def test_book_appointment_success(db: Session) -> None:
    # First create a patient
    pat = create_patient(
        db,
        CreatePatientInput(
            first_name="Tom",
            last_name="Booking",
            phone_number="(416) 555-4444",
            date_of_birth=date(1985, 1, 1),
        ),
        practice_id="p1",
    )
    assert pat.success and pat.patient

    result = book_appointment(
        db,
        BookAppointmentInput(
            patient_id=pat.patient.id,
            slot_id="slot1",
            appointment_type_code="cleaning",
        ),
    )
    assert result.success
    assert result.appointment is not None
    assert result.appointment.appointment_type_code == "cleaning"
    assert result.appointment.date_label != ""


def test_book_appointment_prevents_double_booking(db: Session) -> None:
    pat = create_patient(
        db,
        CreatePatientInput(
            first_name="Double",
            last_name="Book",
            phone_number="(416) 555-5555",
            date_of_birth=date(1990, 3, 3),
        ),
        practice_id="p1",
    )
    assert pat.success and pat.patient
    pid = pat.patient.id

    r1 = book_appointment(db, BookAppointmentInput(patient_id=pid, slot_id="slot2", appointment_type_code="cleaning"))
    assert r1.success

    r2 = book_appointment(db, BookAppointmentInput(patient_id=pid, slot_id="slot2", appointment_type_code="cleaning"))
    assert not r2.success
    assert "taken" in (r2.error or "").lower()


# ---------------------------------------------------------------------------
# Full new-patient booking flow (end-to-end)
# ---------------------------------------------------------------------------


def test_full_new_patient_booking_flow(db: Session) -> None:
    """Simulates the complete new-patient → search → book pipeline."""
    # 1. Register patient
    create_result = create_patient(
        db,
        CreatePatientInput(
            first_name="Cindy",
            last_name="New",
            phone_number="(416) 777-1234",
            date_of_birth=date(1995, 7, 20),
            insurance_name="Sun Life",
        ),
        practice_id="p1",
    )
    assert create_result.success
    patient_id = create_result.patient.id  # type: ignore[union-attr]

    # 2. Search slots
    date_from = date.today() + timedelta(days=6)
    slots_result = search_slots(
        db,
        SearchSlotsInput(
            appointment_type_code="cleaning",
            date_from=date_from,
            date_to=date_from + timedelta(days=14),
        ),
    )
    assert len(slots_result.slots) >= 1

    # 3. Book slot 1
    book_result = book_appointment(
        db,
        BookAppointmentInput(
            patient_id=patient_id,
            slot_id=slots_result.slots[0].id,
            appointment_type_code="cleaning",
        ),
    )
    assert book_result.success
    appt = book_result.appointment
    assert appt is not None
    assert appt.patient_id == patient_id
    assert appt.status == "booked"
    assert appt.date_label != ""
    assert appt.time_label != ""
