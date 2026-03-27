"""
Tests for the existing-patient verification + booking flow.

Lookup strategy (in priority order):
  1. phone + first_name + last_name  → confidence 1.0  (standard verification path)
     - email as last-resort tiebreaker if two records share all three fields
  2. phone only                       → confidence 0.8  (REQUIRED for _caller_lookup:
                                         silent pre-identification from caller ID before
                                         any workflow starts — name not yet collected)
  3. first_name + last_name only      → confidence 0.7  (graceful fallback; e.g. transposed
                                         phone digit — returns a weaker match rather than
                                         failing entirely)

Covers:
  - Exact match by phone + full name → confidence 1.0
  - Multiple matches on all three fields → email disambiguates → 1.0
  - Multiple matches, no email → multiple_matches flag
  - Wrong name with duplicate phone → multiple_matches (phone hit, name didn't narrow)
  - Wrong phone falls back to name-only match → confidence 0.7
  - Phone-only match (_caller_lookup path) → confidence 0.8
  - Unknown phone → not found
  - Duplicate phone without name → multiple_matches
  - Name-only unique match → confidence 0.7
  - Multiple same-name records, no email → multiple_matches
  - Unknown name → not found
  - Verified patient with pending booking → auto slot search
  - Duplicate prompt → disambiguating step, _lookup_retry flag
  - Not found → identity fields cleared
  - Not found after retry → "still wasn't able" message
  - Verified with no pending workflow → generic welcome-back
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["USE_LLM"] = "false"

from models.base import Base
from models.content import ClinicSettings
from models.patient import Patient
from models.practice import Location, Practice
from models.scheduling import AppointmentSlot, AppointmentType
from models.staff import Provider
from tools.patient_tools import lookup_patient
from schemas.tools import LookupPatientInput

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
    practice = Practice(
        id="p1",
        name="bright_smile",
        display_name="Bright Smile Dental",
        timezone="America/Toronto",
    )
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

    start_day = date.today() + timedelta(days=7)
    for i in range(3):
        day = start_day + timedelta(days=i)
        starts = datetime(day.year, day.month, day.day, 10 + i, 0, tzinfo=TZ)
        ends = starts + timedelta(hours=1)
        db.add(
            AppointmentSlot(
                id=f"slot{i + 1}",
                location_id=location.id,
                provider_id=provider.id,
                appointment_type_id=at_cleaning.id,
                starts_at=starts,
                ends_at=ends,
                slot_status="available",
            )
        )

    db.add(
        ClinicSettings(
            practice_id=practice.id,
            default_location_id=location.id,
            accepts_major_insurance=True,
            self_pay_available=True,
            membership_available=True,
            financing_available=True,
            emergency_escalation_enabled=True,
        )
    )

    # Primary test patient
    db.add(
        Patient(
            id="pat1",
            practice_id=practice.id,
            first_name="Alice",
            last_name="Thompson",
            phone_number="4165550201",
            date_of_birth=date(1985, 3, 14),
            email="alice@example.com",
            status="active",
        )
    )

    # Duplicate: same phone + name (extreme edge case, tests email tiebreaker)
    db.add(
        Patient(
            id="pat2",
            practice_id=practice.id,
            first_name="Alice",
            last_name="Thompson",
            phone_number="4165550201",  # same phone intentionally
            date_of_birth=date(1985, 3, 14),
            email="alice2@example.com",
            status="active",
        )
    )

    # Different patient, no phone duplicates
    db.add(
        Patient(
            id="pat3",
            practice_id=practice.id,
            first_name="Carol",
            last_name="Williams",
            phone_number="4165550203",
            date_of_birth=date(1990, 7, 4),
            email="carol@example.com",
            status="active",
        )
    )

    db.commit()


PRACTICE_ID = "p1"

# ---------------------------------------------------------------------------
# lookup_patient unit tests
# ---------------------------------------------------------------------------


class TestLookupPrimaryKey:
    """phone + first_name + last_name — the standard verification path."""

    def test_exact_match_all_three(self, db: Session) -> None:
        """Two Alice Thompsons in DB — email tiebreaker resolves to pat1."""
        result = lookup_patient(
            db,
            LookupPatientInput(first_name="Alice", last_name="Thompson", phone_number="(416) 555-0201",
                               email="alice@example.com"),
            practice_id=PRACTICE_ID,
        )
        assert result.found is True
        assert result.patient is not None
        assert result.patient.id == "pat1"
        assert result.match_confidence == 1.0

    def test_multiple_matches_no_email_returns_flag(self, db: Session) -> None:
        """Same phone + name with no email → multiple_matches."""
        result = lookup_patient(
            db,
            LookupPatientInput(first_name="Alice", last_name="Thompson", phone_number="(416) 555-0201"),
            practice_id=PRACTICE_ID,
        )
        assert result.found is False
        assert result.multiple_matches is True

    def test_multiple_matches_resolved_by_email(self, db: Session) -> None:
        """Email disambiguates between two Alice Thompsons."""
        result = lookup_patient(
            db,
            LookupPatientInput(first_name="Alice", last_name="Thompson", phone_number="(416) 555-0201",
                               email="alice2@example.com"),
            practice_id=PRACTICE_ID,
        )
        assert result.found is True
        assert result.patient is not None
        assert result.patient.id == "pat2"
        assert result.match_confidence == 1.0

    def test_wrong_name_with_duplicate_phone_returns_multiple_matches(self, db: Session) -> None:
        """
        "Bob Thompson" + a phone that belongs to two Alice Thompson records:
        strategy 1 finds 0 Bob Thompsons on that phone; strategy 2 hits the phone
        and can't narrow by name → multiple_matches so we can ask for email.
        """
        result = lookup_patient(
            db,
            LookupPatientInput(first_name="Bob", last_name="Thompson", phone_number="(416) 555-0201"),
            practice_id=PRACTICE_ID,
        )
        assert result.found is False
        # The phone matched records; system cannot verify Bob — caller should provide email.
        assert result.multiple_matches is True

    def test_wrong_phone_falls_back_to_name_match(self, db: Session) -> None:
        """
        Carol Williams supplies a wrong phone number.
        Strategies 1 & 2 miss; strategy 3 (name-only) still finds her at confidence 0.7.
        This graceful fallback is intentional — avoids false negatives for transposed digits.
        """
        result = lookup_patient(
            db,
            LookupPatientInput(first_name="Carol", last_name="Williams", phone_number="(999) 000-0000"),
            practice_id=PRACTICE_ID,
        )
        assert result.found is True
        assert result.match_confidence == 0.7


class TestLookupPhoneOnly:
    """Caller ID path: phone pre-filled, name not yet collected."""

    def test_unique_phone_returns_patient(self, db: Session) -> None:
        result = lookup_patient(
            db,
            LookupPatientInput(phone_number="(416) 555-0203"),
            practice_id=PRACTICE_ID,
        )
        assert result.found is True
        assert result.patient is not None
        assert result.patient.first_name == "Carol"
        assert result.match_confidence == 0.8

    def test_unknown_phone_not_found(self, db: Session) -> None:
        result = lookup_patient(
            db,
            LookupPatientInput(phone_number="(999) 000-0000"),
            practice_id=PRACTICE_ID,
        )
        assert result.found is False

    def test_duplicate_phone_without_name_returns_flag(self, db: Session) -> None:
        """Two patients share the same phone — multiple_matches until email provided."""
        result = lookup_patient(
            db,
            LookupPatientInput(phone_number="(416) 555-0201"),
            practice_id=PRACTICE_ID,
        )
        assert result.multiple_matches is True


class TestLookupNameOnly:
    """Fallback: no phone supplied at all."""

    def test_unique_name_match(self, db: Session) -> None:
        result = lookup_patient(
            db,
            LookupPatientInput(first_name="Carol", last_name="Williams"),
            practice_id=PRACTICE_ID,
        )
        assert result.found is True
        assert result.match_confidence == 0.7

    def test_multiple_same_name_no_email(self, db: Session) -> None:
        result = lookup_patient(
            db,
            LookupPatientInput(first_name="Alice", last_name="Thompson"),
            practice_id=PRACTICE_ID,
        )
        assert result.multiple_matches is True

    def test_not_found_unknown_name(self, db: Session) -> None:
        result = lookup_patient(
            db,
            LookupPatientInput(first_name="John", last_name="Doe"),
            practice_id=PRACTICE_ID,
        )
        assert result.found is False


# ---------------------------------------------------------------------------
# Router-level dispatch edge case tests
# ---------------------------------------------------------------------------


class TestDispatchLookupPatient:
    """Exercises _dispatch_tool('lookup_patient', ...) directly."""

    def _make_state(self, extra_fields: dict | None = None, step: str = "collecting"):
        from schemas.chat import Workflow, WorkflowState

        collected: dict = {
            "first_name": "Carol",
            "last_name": "Williams",
            "phone_number": "4165550203",
            "_pending_workflow": "book_appointment",
            "appointment_type": "cleaning",
            "preferred_date_from": (date.today() + timedelta(days=7)).isoformat(),
        }
        if extra_fields:
            collected.update(extra_fields)
        return WorkflowState(
            workflow=Workflow.EXISTING_PATIENT_VERIFICATION,
            step=step,
            collected_fields=collected,
        )

    def _import_dispatch(self):
        import sys, os as _os
        _os.chdir("/Users/jojongai/Desktop/code/Dental-Chatbot/apps/api")
        if "/Users/jojongai/Desktop/code/Dental-Chatbot/apps/api" not in sys.path:
            sys.path.insert(0, "/Users/jojongai/Desktop/code/Dental-Chatbot/apps/api")
        from routers.chat import _dispatch_tool
        return _dispatch_tool

    def test_verified_with_pending_booking_asks_appointment_details(self, db: Session) -> None:
        """Carol Williams verified → asks for appointment type/date instead of auto-searching slots."""
        _dispatch_tool = self._import_dispatch()
        state = self._make_state()
        reply, new_state, tools = _dispatch_tool(
            tool_name="lookup_patient",
            tool_input_data=dict(state.collected_fields),
            state=state,
            db=db,
            practice_id=PRACTICE_ID,
        )
        assert "welcome back" in reply.lower()
        from schemas.chat import Workflow
        assert new_state.workflow == Workflow.BOOK_APPOINTMENT
        assert new_state.step == "collecting"
        assert new_state.patient_id == "pat3"

    def test_duplicate_returns_disambiguation_prompt(self, db: Session) -> None:
        """Two Alice Thompsons on same phone → ask for email."""
        _dispatch_tool = self._import_dispatch()
        state = self._make_state(
            extra_fields={"first_name": "Alice", "last_name": "Thompson", "phone_number": "4165550201"}
        )
        reply, new_state, tools = _dispatch_tool(
            tool_name="lookup_patient",
            tool_input_data=dict(state.collected_fields),
            state=state,
            db=db,
            practice_id=PRACTICE_ID,
        )
        assert "email" in reply.lower() or "record" in reply.lower()
        assert new_state.step == "disambiguating"
        assert new_state.collected_fields.get("_lookup_retry") is True

    def test_not_found_clears_identity_fields(self, db: Session) -> None:
        """Unknown patient → identity fields cleared, step reset to collecting."""
        _dispatch_tool = self._import_dispatch()
        state = self._make_state(
            extra_fields={"first_name": "No", "last_name": "Such", "phone_number": "9999999999"}
        )
        reply, new_state, tools = _dispatch_tool(
            tool_name="lookup_patient",
            tool_input_data=dict(state.collected_fields),
            state=state,
            db=db,
            practice_id=PRACTICE_ID,
        )
        assert "wasn't able" in reply.lower() or "new patient" in reply.lower()
        assert "first_name" not in new_state.collected_fields
        assert "last_name" not in new_state.collected_fields
        assert "phone_number" not in new_state.collected_fields
        assert new_state.step == "collecting"
        assert new_state.collected_fields.get("_lookup_failed_offer_registration") is True

    def test_not_found_after_retry_gives_specific_message(self, db: Session) -> None:
        """Second failure (_lookup_retry=True) → 'still wasn't able' message."""
        _dispatch_tool = self._import_dispatch()
        state = self._make_state(
            extra_fields={
                "first_name": "No", "last_name": "Such", "phone_number": "9999999999",
                "_lookup_retry": True,
            }
        )
        reply, new_state, tools = _dispatch_tool(
            tool_name="lookup_patient",
            tool_input_data=dict(state.collected_fields),
            state=state,
            db=db,
            practice_id=PRACTICE_ID,
        )
        assert "still wasn't able" in reply.lower() or "call" in reply.lower()

    def test_verified_no_pending_workflow_gives_generic_welcome(self, db: Session) -> None:
        """Verified patient with no _pending_workflow → generic welcome, no slot search."""
        _dispatch_tool = self._import_dispatch()
        from schemas.chat import Workflow, WorkflowState

        state = WorkflowState(
            workflow=Workflow.EXISTING_PATIENT_VERIFICATION,
            step="collecting",
            collected_fields={
                "first_name": "Carol",
                "last_name": "Williams",
                "phone_number": "4165550203",
            },
        )
        reply, new_state, tools = _dispatch_tool(
            tool_name="lookup_patient",
            tool_input_data=dict(state.collected_fields),
            state=state,
            db=db,
            practice_id=PRACTICE_ID,
        )
        assert "welcome back" in reply.lower()
        assert new_state.step != "selecting_slot"
        assert new_state.patient_id == "pat3"
