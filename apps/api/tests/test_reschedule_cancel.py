"""
Tests for the reschedule and cancellation flows.

Covers:
Tool layer (scheduling_tools)
  - list_patient_appointments: returns upcoming non-cancelled appointments
  - reschedule_appointment: frees old slot, creates new appointment, marks old as 'rescheduled'
  - cancel_appointment: marks appointment cancelled, frees the slot
  - Error cases: appointment not found, already cancelled, slot unavailable

Router layer (routers/chat)
  - Reschedule intent → verification → list appointments → select → new date → slot search → pick → confirm
  - Cancel intent → verification → list appointments → select → reason → confirm cancel
  - Selecting an appointment with no upcoming appointments → graceful no-op message
  - Slot taken mid-reschedule → presents remaining options
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
from models.scheduling import Appointment, AppointmentSlot, AppointmentType
from models.staff import Provider
from schemas.chat import Workflow, WorkflowState
from schemas.tools import (
    CancelAppointmentInput,
    ListPatientAppointmentsInput,
    RescheduleAppointmentInput,
)
from tools.scheduling_tools import (
    cancel_appointment,
    list_patient_appointments,
    reschedule_appointment,
)

TZ = ZoneInfo("America/Toronto")


# ---------------------------------------------------------------------------
# DB fixture + seed
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

    # Patient with two future appointments + one past + one cancelled
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

    # Patient with no upcoming appointments
    db.add(
        Patient(
            id="pat2",
            practice_id=practice.id,
            first_name="Bob",
            last_name="Jones",
            phone_number="4165550202",
            date_of_birth=date(1990, 6, 1),
            status="active",
        )
    )

    db.flush()

    # Three available slots in the future
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

    # A future slot that is already booked — used to test "slot taken" case
    future_booked_day = date.today() + timedelta(days=14)
    starts_booked = datetime(
        future_booked_day.year, future_booked_day.month, future_booked_day.day, 14, 0, tzinfo=TZ
    )
    db.add(
        AppointmentSlot(
            id="slot_taken",
            location_id=location.id,
            provider_id=provider.id,
            appointment_type_id=at_cleaning.id,
            starts_at=starts_booked,
            ends_at=starts_booked + timedelta(hours=1),
            slot_status="booked",
        )
    )

    # Slot used by alice's existing appointment (booked)
    appt_day = date.today() + timedelta(days=3)
    appt_starts = datetime(appt_day.year, appt_day.month, appt_day.day, 9, 0, tzinfo=TZ)
    appt_ends = appt_starts + timedelta(hours=1)
    db.add(
        AppointmentSlot(
            id="slot_appt1",
            location_id=location.id,
            provider_id=provider.id,
            appointment_type_id=at_cleaning.id,
            starts_at=appt_starts,
            ends_at=appt_ends,
            slot_status="booked",
        )
    )
    db.add(
        Appointment(
            id="appt1",
            patient_id="pat1",
            slot_id="slot_appt1",
            location_id=location.id,
            provider_id=provider.id,
            appointment_type_id=at_cleaning.id,
            status="booked",
            booked_via="chatbot",
            scheduled_starts_at=appt_starts,
            scheduled_ends_at=appt_ends,
        )
    )

    # A second future appointment for Alice
    appt2_day = date.today() + timedelta(days=10)
    appt2_starts = datetime(appt2_day.year, appt2_day.month, appt2_day.day, 11, 0, tzinfo=TZ)
    appt2_ends = appt2_starts + timedelta(hours=1)
    db.add(
        AppointmentSlot(
            id="slot_appt2",
            location_id=location.id,
            provider_id=provider.id,
            appointment_type_id=at_cleaning.id,
            starts_at=appt2_starts,
            ends_at=appt2_ends,
            slot_status="booked",
        )
    )
    db.add(
        Appointment(
            id="appt2",
            patient_id="pat1",
            slot_id="slot_appt2",
            location_id=location.id,
            provider_id=provider.id,
            appointment_type_id=at_cleaning.id,
            status="booked",
            booked_via="chatbot",
            scheduled_starts_at=appt2_starts,
            scheduled_ends_at=appt2_ends,
        )
    )

    # A cancelled appointment — should NOT appear in list
    db.add(
        Appointment(
            id="appt_cancelled",
            patient_id="pat1",
            slot_id="slot1",
            location_id=location.id,
            provider_id=provider.id,
            appointment_type_id=at_cleaning.id,
            status="cancelled",
            booked_via="chatbot",
            scheduled_starts_at=appt_starts + timedelta(days=20),
            scheduled_ends_at=appt_ends + timedelta(days=20),
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

    db.commit()


# ---------------------------------------------------------------------------
# list_patient_appointments
# ---------------------------------------------------------------------------


class TestListPatientAppointments:
    def test_returns_upcoming_only(self, db: Session) -> None:
        result = list_patient_appointments(db, ListPatientAppointmentsInput(patient_id="pat1"))
        assert result.total == 2
        ids = [a.id for a in result.appointments]
        assert "appt1" in ids
        assert "appt2" in ids
        # cancelled appointment must not appear
        assert "appt_cancelled" not in ids

    def test_rescheduled_appointment_not_in_upcoming_list(self, db: Session) -> None:
        """After reschedule, the old row stays for audit but must not show as an upcoming visit."""
        r = reschedule_appointment(
            db, RescheduleAppointmentInput(appointment_id="appt1", new_slot_id="slot2")
        )
        assert r.success and r.new_appointment is not None
        result = list_patient_appointments(db, ListPatientAppointmentsInput(patient_id="pat1"))
        ids = [a.id for a in result.appointments]
        assert "appt1" not in ids
        assert r.new_appointment.id in ids
        assert "appt2" in ids

    def test_ordered_by_starts_at(self, db: Session) -> None:
        """Verify ASC ordering by checking that each entry's date-label appears in
        chronological order (not lexicographic — month names sort differently)."""
        result = list_patient_appointments(db, ListPatientAppointmentsInput(patient_id="pat1"))
        # appt1 is 3 days out, appt2 is 10 days out → appt1 must come first
        assert result.appointments[0].id == "appt1"
        assert result.appointments[1].id == "appt2"

    def test_no_appointments(self, db: Session) -> None:
        result = list_patient_appointments(db, ListPatientAppointmentsInput(patient_id="pat2"))
        assert result.total == 0
        assert result.appointments == []

    def test_unknown_patient(self, db: Session) -> None:
        result = list_patient_appointments(db, ListPatientAppointmentsInput(patient_id="nobody"))
        assert result.total == 0


# ---------------------------------------------------------------------------
# cancel_appointment
# ---------------------------------------------------------------------------


class TestCancelAppointment:
    def test_cancels_and_frees_slot(self, db: Session) -> None:
        result = cancel_appointment(
            db, CancelAppointmentInput(appointment_id="appt1", cancel_reason="Scheduling conflict")
        )
        assert result.success
        assert result.cancelled_appointment is not None
        assert result.cancelled_appointment.status == "cancelled"

        # Slot must be freed
        from models.scheduling import AppointmentSlot as Slot

        slot = db.get(Slot, "slot_appt1")
        assert slot is not None
        assert slot.slot_status == "available"

    def test_cancel_reason_stored(self, db: Session) -> None:
        cancel_appointment(
            db, CancelAppointmentInput(appointment_id="appt1", cancel_reason="Moved out of town")
        )
        appt = db.get(Appointment, "appt1")
        assert appt is not None
        assert "Moved out of town" in (appt.special_instructions or "")

    def test_not_found(self, db: Session) -> None:
        result = cancel_appointment(
            db, CancelAppointmentInput(appointment_id="ghost", cancel_reason="nope")
        )
        assert not result.success
        assert result.error is not None

    def test_already_cancelled(self, db: Session) -> None:
        # Cancel once
        cancel_appointment(db, CancelAppointmentInput(appointment_id="appt1", cancel_reason="r"))
        # Cancel again
        result = cancel_appointment(
            db, CancelAppointmentInput(appointment_id="appt1", cancel_reason="r")
        )
        assert not result.success
        assert "already" in (result.error or "").lower() or "cancelled" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# reschedule_appointment
# ---------------------------------------------------------------------------


class TestRescheduleAppointment:
    def test_reschedule_success(self, db: Session) -> None:
        # slot1 is already referenced by appt_cancelled (UNIQUE constraint); use slot2
        result = reschedule_appointment(
            db, RescheduleAppointmentInput(appointment_id="appt1", new_slot_id="slot2")
        )
        assert result.success
        assert result.new_appointment is not None
        assert result.old_appointment is not None
        assert result.old_appointment.status == "rescheduled"

        # Old slot freed
        old_slot = db.get(AppointmentSlot, "slot_appt1")
        assert old_slot is not None
        assert old_slot.slot_status == "available"

        # New slot booked
        new_slot = db.get(AppointmentSlot, "slot2")
        assert new_slot is not None
        assert new_slot.slot_status == "booked"

    def test_links_back_via_rescheduled_from(self, db: Session) -> None:
        result = reschedule_appointment(
            db, RescheduleAppointmentInput(appointment_id="appt1", new_slot_id="slot2")
        )
        new_appt = db.get(Appointment, result.new_appointment.id)  # type: ignore[union-attr]
        assert new_appt is not None
        assert new_appt.rescheduled_from_appointment_id == "appt1"

    def test_appointment_not_found(self, db: Session) -> None:
        result = reschedule_appointment(
            db, RescheduleAppointmentInput(appointment_id="ghost", new_slot_id="slot1")
        )
        assert not result.success
        assert result.error is not None

    def test_new_slot_not_found(self, db: Session) -> None:
        result = reschedule_appointment(
            db, RescheduleAppointmentInput(appointment_id="appt1", new_slot_id="nonexistent")
        )
        assert not result.success

    def test_new_slot_already_booked(self, db: Session) -> None:
        result = reschedule_appointment(
            db, RescheduleAppointmentInput(appointment_id="appt1", new_slot_id="slot_taken")
        )
        assert not result.success
        assert "taken" in (result.error or "").lower() or "available" in (result.error or "").lower()

    def test_cannot_reschedule_cancelled(self, db: Session) -> None:
        result = reschedule_appointment(
            db,
            RescheduleAppointmentInput(appointment_id="appt_cancelled", new_slot_id="slot1"),
        )
        assert not result.success


# ---------------------------------------------------------------------------
# Router-level tests — call dispatch/helper functions directly
# (same pattern as test_existing_patient_booking.py)
# ---------------------------------------------------------------------------

import sys as _sys
import os as _os

_os.chdir("/Users/jojongai/Desktop/code/Dental-Chatbot/apps/api")
if "/Users/jojongai/Desktop/code/Dental-Chatbot/apps/api" not in _sys.path:
    _sys.path.insert(0, "/Users/jojongai/Desktop/code/Dental-Chatbot/apps/api")


def _import_router():
    from routers.chat import (
        _dispatch_tool,
        _handle_appointment_selection,
        _list_and_present_appointments,
    )
    return _dispatch_tool, _handle_appointment_selection, _list_and_present_appointments


PRACTICE_ID = "p1"


class TestKnownPatientListInjection:
    """Reschedule/cancel with patient_id (post–terminal reset) must still list appointments first."""

    def test_reschedule_with_patient_id_gets_list_not_date_prompt(self, db: Session) -> None:
        from state_machine.machine import MachineResult

        from routers.chat import _list_appointments_if_known_patient_skipped_verification

        state = WorkflowState(
            workflow=Workflow.RESCHEDULE_APPOINTMENT,
            step="collecting:preferred_date_from",
            patient_id="pat1",
            collected_fields={"first_name": "Alice"},
        )
        result = MachineResult(
            state=state,
            reply="No problem, I can move that for you!",
            next_field="preferred_date_from",
        )
        out = _list_appointments_if_known_patient_skipped_verification(result, db)
        assert out is not None
        reply, new_state, tools = out
        assert "1." in reply and "2." in reply
        assert "reschedule" in reply.lower()
        assert new_state.step == "selecting_appointment"
        assert tools == ["list_patient_appointments"]

    def test_cancel_with_patient_id_gets_list_not_reason_prompt(self, db: Session) -> None:
        """Cancel with known patient_id must list appointments before asking for cancel reason."""
        from state_machine.machine import MachineResult

        from routers.chat import _list_appointments_if_known_patient_skipped_verification

        state = WorkflowState(
            workflow=Workflow.CANCEL_APPOINTMENT,
            step="collecting:cancel_reason",
            patient_id="pat1",
            collected_fields={"first_name": "Alice"},
        )
        result = MachineResult(
            state=state,
            reply="Got it, I can take care of that for you!",
            next_field="cancel_reason",
        )
        out = _list_appointments_if_known_patient_skipped_verification(result, db)
        assert out is not None
        reply, new_state, tools = out
        assert "1." in reply and "2." in reply
        assert "cancel" in reply.lower()
        assert new_state.step == "selecting_appointment"
        assert tools == ["list_patient_appointments"]

    def test_no_injection_when_appointment_already_selected(self, db: Session) -> None:
        from state_machine.machine import MachineResult

        from routers.chat import _list_appointments_if_known_patient_skipped_verification

        state = WorkflowState(
            workflow=Workflow.RESCHEDULE_APPOINTMENT,
            step="collecting:preferred_date_from",
            patient_id="pat1",
            appointment_id="appt1",
            collected_fields={"first_name": "Alice", "preferred_date_from": "2026-04-01"},
        )
        result = MachineResult(state=state, reply="x", next_field="preferred_date_from")
        assert _list_appointments_if_known_patient_skipped_verification(result, db) is None


class TestCancelFlow:
    def test_no_appointments_returns_graceful_message(self, db: Session) -> None:
        """Patient with no upcoming appointments gets a clear no-op message."""
        _, _, _list_and_present_appointments = _import_router()
        state = WorkflowState(
            workflow=Workflow.CANCEL_APPOINTMENT,
            step="collecting",
            patient_id="pat2",
            collected_fields={"_pending_workflow": "cancel_appointment"},
        )
        reply, new_state = _list_and_present_appointments(state, db, "Bob")
        assert "nothing to cancel" in reply.lower() or "don't see any" in reply.lower()
        assert new_state.workflow == Workflow.GENERAL_INQUIRY
        assert new_state.step == "start"

    def test_list_presents_numbered_appointments(self, db: Session) -> None:
        """Patient with two upcoming appointments sees a numbered list."""
        _, _, _list_and_present_appointments = _import_router()
        state = WorkflowState(
            workflow=Workflow.CANCEL_APPOINTMENT,
            step="collecting",
            patient_id="pat1",
            collected_fields={"_pending_workflow": "cancel_appointment"},
        )
        reply, new_state = _list_and_present_appointments(state, db, "Alice")
        assert "1." in reply and "2." in reply
        assert new_state.step == "selecting_appointment"
        assert len(new_state.appointment_options) == 2

    def test_appointment_selection_stores_id_and_prompts_reason(self, db: Session) -> None:
        """Picking appointment 1 sets appointment_id and asks for cancel reason."""
        _, _handle_appointment_selection, _ = _import_router()
        state = WorkflowState(
            workflow=Workflow.CANCEL_APPOINTMENT,
            step="selecting_appointment",
            patient_id="pat1",
            appointment_options=[
                {"id": "appt1", "label": "Teeth Cleaning — some date"},
                {"id": "appt2", "label": "Teeth Cleaning — later date"},
            ],
            collected_fields={"_pending_workflow": "cancel_appointment"},
        )
        response = _handle_appointment_selection("1", state, db)
        assert response.state.appointment_id == "appt1"
        assert response.state.workflow == Workflow.CANCEL_APPOINTMENT
        assert "_pending_workflow" not in response.state.collected_fields
        assert response.state.missing_fields == ["cancel_reason"]
        assert "cancel" in response.reply.lower() or "reason" in response.reply.lower()
        assert "preferred_date_from" not in response.state.collected_fields

    def test_selection_after_verification_list_leaves_cancel_workflow_not_lookup(
        self, db: Session
    ) -> None:
        """Listing runs under verification; picking an appointment must switch workflow so lookup does not repeat."""
        _, _handle_appointment_selection, _ = _import_router()
        state = WorkflowState(
            workflow=Workflow.EXISTING_PATIENT_VERIFICATION,
            step="selecting_appointment",
            patient_id="pat1",
            appointment_options=[{"id": "appt1", "label": "Teeth Cleaning — some date"}],
            collected_fields={
                "_pending_workflow": "cancel_appointment",
                "first_name": "Jo",
                "last_name": "Ngai",
                "phone_number": "6476385400",
            },
        )
        response = _handle_appointment_selection("1", state, db)
        assert response.state.workflow == Workflow.CANCEL_APPOINTMENT
        assert response.state.appointment_id == "appt1"
        assert "_pending_workflow" not in response.state.collected_fields

    def test_invalid_selection_asks_again(self, db: Session) -> None:
        """Non-numeric reply re-prompts for a valid choice."""
        _, _handle_appointment_selection, _ = _import_router()
        state = WorkflowState(
            workflow=Workflow.CANCEL_APPOINTMENT,
            step="selecting_appointment",
            patient_id="pat1",
            appointment_options=[{"id": "appt1", "label": "Teeth Cleaning — some date"}],
            collected_fields={"_pending_workflow": "cancel_appointment"},
        )
        response = _handle_appointment_selection("I want to cancel", state, db)
        assert "1" in response.reply or "number" in response.reply.lower()

    def test_dispatch_cancel_appointment_tool(self, db: Session) -> None:
        """Dispatching cancel_appointment calls the tool and returns confirmation."""
        _dispatch_tool, _, _ = _import_router()
        state = WorkflowState(
            workflow=Workflow.CANCEL_APPOINTMENT,
            step="collecting",
            patient_id="pat1",
            appointment_id="appt1",
            collected_fields={"cancel_reason": "Scheduling conflict"},
        )
        reply, new_state, tools = _dispatch_tool(
            tool_name="cancel_appointment",
            tool_input_data={"cancel_reason": "Scheduling conflict"},
            state=state,
            db=db,
            practice_id=PRACTICE_ID,
        )
        assert "cancel" in reply.lower() or "done" in reply.lower()
        assert "cancel_appointment" in tools
        assert new_state.workflow == Workflow.GENERAL_INQUIRY
        assert new_state.step == "start"
        assert new_state.appointment_id is None
        assert "cancel_reason" not in new_state.collected_fields

    def test_dispatch_cancel_without_appointment_id(self, db: Session) -> None:
        """Cancelling without an appointment_id returns a helpful error."""
        _dispatch_tool, _, _ = _import_router()
        state = WorkflowState(
            workflow=Workflow.CANCEL_APPOINTMENT,
            step="collecting",
            patient_id="pat1",
            collected_fields={"cancel_reason": "Testing"},
        )
        reply, new_state, tools = _dispatch_tool(
            tool_name="cancel_appointment",
            tool_input_data={"cancel_reason": "Testing"},
            state=state,
            db=db,
            practice_id=PRACTICE_ID,
        )
        assert "date" in reply.lower() or "cancel" in reply.lower()


class TestRescheduleFlow:
    def test_list_presents_reschedule_verb(self, db: Session) -> None:
        """Appointment list for reschedule uses the word 'reschedule'."""
        _, _, _list_and_present_appointments = _import_router()
        state = WorkflowState(
            workflow=Workflow.RESCHEDULE_APPOINTMENT,
            step="collecting",
            patient_id="pat1",
            collected_fields={"_pending_workflow": "reschedule_appointment"},
        )
        reply, new_state = _list_and_present_appointments(state, db, "Alice")
        assert "reschedule" in reply.lower()
        assert new_state.step == "selecting_appointment"

    def test_appointment_selection_stores_id_and_prompts_date(self, db: Session) -> None:
        """Picking appointment 1 sets appointment_id and asks for new date."""
        _, _handle_appointment_selection, _ = _import_router()
        state = WorkflowState(
            workflow=Workflow.RESCHEDULE_APPOINTMENT,
            step="selecting_appointment",
            patient_id="pat1",
            appointment_options=[{"id": "appt1", "label": "Teeth Cleaning — some date"}],
            collected_fields={"_pending_workflow": "reschedule_appointment"},
        )
        response = _handle_appointment_selection("1", state, db)
        assert response.state.appointment_id == "appt1"
        assert response.state.workflow == Workflow.RESCHEDULE_APPOINTMENT
        assert "_pending_workflow" not in response.state.collected_fields
        assert response.state.missing_fields == ["preferred_date_from"]
        reply = response.reply.lower()
        assert "date" in reply or "when" in reply or "move" in reply
        # preferred_date_from must not be pre-collected
        assert "preferred_date_from" not in response.state.collected_fields

    def test_dispatch_search_slots_in_reschedule_workflow(self, db: Session) -> None:
        """When workflow=reschedule, search_slots fires and returns slot options."""
        from datetime import date as _date

        _dispatch_tool, _, _ = _import_router()
        future = _date.today() + timedelta(days=7)
        state = WorkflowState(
            workflow=Workflow.RESCHEDULE_APPOINTMENT,
            step="collecting",
            patient_id="pat1",
            appointment_id="appt1",
            collected_fields={
                "_pending_workflow": "reschedule_appointment",
                "preferred_date_from": future.isoformat(),
            },
        )
        reply, new_state, tools = _dispatch_tool(
            tool_name="search_slots",
            tool_input_data={
                "appointment_type": "cleaning",
                "preferred_date_from": future.isoformat(),
            },
            state=state,
            db=db,
            practice_id=PRACTICE_ID,
        )
        assert "search_slots" in tools
        assert new_state.step == "selecting_slot"
        assert len(new_state.slot_options) > 0

    def test_dispatch_reschedule_appointment_tool(self, db: Session) -> None:
        """After slot selection, reschedule_appointment is called and returns confirmation."""
        _dispatch_tool, _, _ = _import_router()
        state = WorkflowState(
            workflow=Workflow.RESCHEDULE_APPOINTMENT,
            step="selecting_slot",
            patient_id="pat1",
            appointment_id="appt1",
            slot_options=[{"id": "slot2", "label": "Teeth Cleaning — future slot"}],
            collected_fields={
                "_pending_workflow": "reschedule_appointment",
                "preferred_date_from": (date.today() + timedelta(days=7)).isoformat(),
            },
        )
        # Simulate calling slot selection directly with "1"
        from routers.chat import _handle_slot_selection

        response = _handle_slot_selection("1", state, db, PRACTICE_ID)
        reply = response.reply.lower()
        assert "reschedule" in reply or "rescheduled" in reply or "new" in reply
        assert response.state.workflow == Workflow.GENERAL_INQUIRY
        assert response.state.step == "start"
        assert response.state.slot_options == []

    def test_reschedule_slot_taken_shows_remaining(self, db: Session) -> None:
        """If chosen slot is already booked, remaining slots are offered."""
        state = WorkflowState(
            workflow=Workflow.RESCHEDULE_APPOINTMENT,
            step="selecting_slot",
            patient_id="pat1",
            appointment_id="appt2",
            slot_options=[
                {"id": "slot_taken", "label": "Teeth Cleaning — taken slot"},
                {"id": "slot2", "label": "Teeth Cleaning — available slot"},
            ],
            collected_fields={
                "_pending_workflow": "reschedule_appointment",
                "preferred_date_from": (date.today() + timedelta(days=7)).isoformat(),
            },
        )
        from routers.chat import _handle_slot_selection

        response = _handle_slot_selection("1", state, db, PRACTICE_ID)
        reply = response.reply.lower()
        assert "taken" in reply or "available" in reply or "option" in reply
