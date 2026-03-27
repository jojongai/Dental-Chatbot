"""Employee dashboard schedule API."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from models.base import Base
from models.patient import Patient
from models.practice import Location, Practice
from models.scheduling import Appointment, AppointmentSlot, AppointmentType
from models.staff import Provider
from tools.scheduling_tools import get_employee_schedule

TZ_ = ZoneInfo("America/Toronto")


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    session = Session_()

    practice = Practice(
        id="p1",
        name="bright_smile",
        display_name="Bright Smile Dental",
        timezone="America/Toronto",
    )
    session.add(practice)
    loc = Location(
        id="loc1",
        practice_id=practice.id,
        name="Downtown",
        address_line_1="1 Main",
        city="Toronto",
        province="ON",
        postal_code="M5H1J9",
        phone_number="555",
        is_primary=True,
    )
    session.add(loc)
    at = AppointmentType(
        id="at1",
        practice_id=practice.id,
        code="cleaning",
        display_name="Teeth Cleaning",
        default_duration_minutes=45,
        is_emergency=False,
    )
    session.add(at)
    prov = Provider(
        id="pr1",
        location_id=loc.id,
        provider_type="hygienist",
        display_name="Maria Santos RDH",
        is_bookable=True,
    )
    session.add(prov)
    pat = Patient(
        id="pat1",
        practice_id=practice.id,
        primary_location_id=loc.id,
        first_name="Sam",
        last_name="Patient",
        date_of_birth=date(1990, 1, 1),
        phone_number="4165550100",
        status="active",
    )
    session.add(pat)
    session.flush()

    d = date(2026, 3, 26)
    start = datetime(d.year, d.month, d.day, 10, 0, tzinfo=TZ_)
    end = start + timedelta(minutes=45)
    slot = AppointmentSlot(
        id="slot1",
        location_id=loc.id,
        provider_id=prov.id,
        appointment_type_id=at.id,
        starts_at=start,
        ends_at=end,
        slot_status="booked",
    )
    session.add(slot)
    appt = Appointment(
        id="appt1",
        patient_id=pat.id,
        slot_id=slot.id,
        location_id=loc.id,
        provider_id=prov.id,
        appointment_type_id=at.id,
        status="booked",
        booked_via="chatbot",
        scheduled_starts_at=start,
        scheduled_ends_at=end,
        is_emergency=False,
    )
    session.add(appt)
    session.commit()

    yield session
    session.close()
    engine.dispose()


def test_get_employee_schedule_maps_booked(db: Session) -> None:
    out = get_employee_schedule(db, date(2026, 3, 26))
    assert len(out.appointments) == 1
    a = out.appointments[0]
    assert a.patient_name == "Sam Patient"
    assert a.ui_status == "confirmed"
    assert a.appointment_type_code == "cleaning"
    assert a.provider_display_name == "Maria Santos RDH"
    assert len(out.week_day_counts) == 6
    assert out.provider_count >= 1


