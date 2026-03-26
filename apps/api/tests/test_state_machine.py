"""
State machine tests.

Exit criteria (per workflow):
  ✓ Machine reports correct missing fields on first turn
  ✓ Machine extracts fields from natural language and marks them collected
  ✓ Machine signals ready_to_call=True only when all required fields are present
  ✓ Machine knows which tool to call and returns tool_input_data
"""

from __future__ import annotations

import os
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from schemas.chat import Workflow, WorkflowState
from state_machine.definitions import WORKFLOWS
from state_machine.machine import WorkflowStateMachine, machine_status

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_state(workflow: Workflow = Workflow.GENERAL_INQUIRY, **kwargs) -> WorkflowState:
    return WorkflowState(workflow=workflow, **kwargs)


def run(state: WorkflowState, message: str):
    return WorkflowStateMachine(state).process(message)


# ---------------------------------------------------------------------------
# General inquiry
# ---------------------------------------------------------------------------


class TestGeneralInquiry:
    def test_ready_immediately_no_fields_needed(self):
        result = run(make_state(), "What are your hours?")
        assert result.ready_to_call is True
        assert result.tool_name == "get_clinic_info"

    def test_tool_input_data_returned(self):
        result = run(make_state(), "Do you accept Sun Life insurance?")
        assert result.tool_input_data is not None


# ---------------------------------------------------------------------------
# New patient registration
# ---------------------------------------------------------------------------


class TestNewPatientRegistration:
    def test_starts_workflow_on_first_turn(self):
        result = run(make_state(), "I'm a new patient and want to register")
        assert result.state.workflow == Workflow.NEW_PATIENT_REGISTRATION
        assert result.ready_to_call is False

    def test_missing_fields_all_required_at_start(self):
        result = run(make_state(), "I want to register as a new patient")
        wf_def = WORKFLOWS[Workflow.NEW_PATIENT_REGISTRATION]
        # Machine may opportunistically extract appointment_type from the message,
        # but must still have at least all other required fields missing.
        assert len(result.state.missing_fields) >= len(wf_def.required_fields) - 1
        # Core identity fields must always appear as missing
        assert "first_name" in result.state.missing_fields
        assert "phone_number" in result.state.missing_fields
        assert "date_of_birth" in result.state.missing_fields

    def test_extracts_full_name(self):
        state = make_state(workflow=Workflow.NEW_PATIENT_REGISTRATION, step="collecting")
        result = run(state, "My name is Sarah Johnson")
        assert result.state.collected_fields.get("first_name") == "Sarah"
        assert result.state.collected_fields.get("last_name") == "Johnson"

    def test_extracts_phone_number(self):
        state = make_state(
            workflow=Workflow.NEW_PATIENT_REGISTRATION,
            step="collecting",
            collected_fields={"first_name": "Sarah", "last_name": "Johnson"},
        )
        result = run(state, "You can reach me at (416) 555-7890")
        assert result.state.collected_fields.get("phone_number") == "(416) 555-7890"

    def test_extracts_date_of_birth(self):
        state = make_state(
            workflow=Workflow.NEW_PATIENT_REGISTRATION,
            step="collecting",
            collected_fields={"first_name": "Sarah", "last_name": "Johnson", "phone_number": "(416) 555-7890"},
        )
        result = run(state, "I was born on March 14, 1990")
        assert result.state.collected_fields.get("date_of_birth") == date(1990, 3, 14)

    def test_extracts_insurance_self_pay(self):
        state = make_state(
            workflow=Workflow.NEW_PATIENT_REGISTRATION,
            step="collecting",
            collected_fields={
                "first_name": "S",
                "last_name": "J",
                "phone_number": "4165551234",
                "date_of_birth": date(1990, 1, 1),
            },
        )
        result = run(state, "I don't have insurance, I'll be self pay")
        assert result.state.collected_fields.get("insurance_name") == "self_pay"

    def test_extracts_appointment_type_cleaning(self):
        state = make_state(
            workflow=Workflow.NEW_PATIENT_REGISTRATION,
            step="collecting",
            collected_fields={
                "first_name": "S",
                "last_name": "J",
                "phone_number": "4165551234",
                "date_of_birth": date(1990, 1, 1),
                "insurance_name": "self_pay",
            },
        )
        result = run(state, "I'd like a cleaning")
        assert result.state.collected_fields.get("appointment_type") == "cleaning"

    def test_not_ready_until_preferred_date_collected(self):
        state = make_state(
            workflow=Workflow.NEW_PATIENT_REGISTRATION,
            step="collecting",
            collected_fields={
                "first_name": "S",
                "last_name": "J",
                "phone_number": "4165551234",
                "date_of_birth": date(1990, 1, 1),
                "insurance_name": "self_pay",
                "appointment_type": "cleaning",
            },
        )
        result = run(state, "hello")
        assert result.ready_to_call is False
        assert "preferred_date_from" in result.state.missing_fields

    def test_ready_when_all_required_fields_present(self):
        all_fields = {
            "first_name": "Sarah",
            "last_name": "Johnson",
            "phone_number": "(416) 555-7890",
            "date_of_birth": date(1990, 3, 14),
            "insurance_name": "self_pay",
            "appointment_type": "cleaning",
            "preferred_date_from": date(2026, 4, 7),
        }
        state = make_state(
            workflow=Workflow.NEW_PATIENT_REGISTRATION,
            step="collecting",
            collected_fields=all_fields,
        )
        result = run(state, "yes that all looks right")
        # requires_confirmation=True → first hit shows summary; after confirm → ready
        # Confirm the machine at least moved to awaiting_confirmation or ready
        assert result.ready_to_call is True or result.state.step in ("awaiting_confirmation", "ready")

    def test_tool_name_is_create_patient(self):
        assert WORKFLOWS[Workflow.NEW_PATIENT_REGISTRATION].tool_name == "create_patient"

    def test_multiple_fields_extracted_in_one_message(self):
        state = make_state(workflow=Workflow.NEW_PATIENT_REGISTRATION, step="collecting")
        result = run(state, "My name is Alice Chen, born January 5 1988, phone 647-555-3322")
        cf = result.state.collected_fields
        assert cf.get("first_name") == "Alice"
        assert cf.get("last_name") == "Chen"
        assert cf.get("date_of_birth") == date(1988, 1, 5)
        assert cf.get("phone_number") == "647-555-3322"


# ---------------------------------------------------------------------------
# Existing patient verification
# ---------------------------------------------------------------------------


class TestExistingPatientVerification:
    def test_required_fields_are_name_and_phone(self):
        """Verification now uses first_name + last_name + phone_number as the lookup key."""
        wf = WORKFLOWS[Workflow.EXISTING_PATIENT_VERIFICATION]
        assert "first_name" in wf.required_fields
        assert "last_name" in wf.required_fields
        assert "phone_number" in wf.required_fields
        assert "date_of_birth" not in wf.required_fields  # no longer required

    def test_missing_fields_initially(self):
        state = make_state(workflow=Workflow.EXISTING_PATIENT_VERIFICATION, step="collecting")
        result = run(state, "I want to check in")
        assert len(result.state.missing_fields) > 0
        assert result.ready_to_call is False

    def test_extracts_full_name(self):
        """Full-name extractor populates both first_name and last_name."""
        state = make_state(workflow=Workflow.EXISTING_PATIENT_VERIFICATION, step="collecting")
        result = run(state, "My name is Alice Thompson")
        assert result.state.collected_fields.get("first_name") == "Alice"
        assert result.state.collected_fields.get("last_name") == "Thompson"

    def test_extracts_phone(self):
        state = make_state(
            workflow=Workflow.EXISTING_PATIENT_VERIFICATION,
            step="collecting",
            collected_fields={"first_name": "Alice", "last_name": "Thompson"},
        )
        result = run(state, "My number is (416) 555-0201")
        assert result.state.collected_fields.get("phone_number") == "(416) 555-0201"

    def test_ready_when_all_three_present(self):
        state = make_state(
            workflow=Workflow.EXISTING_PATIENT_VERIFICATION,
            step="collecting",
            collected_fields={
                "first_name": "Alice",
                "last_name": "Thompson",
                "phone_number": "(416) 555-0201",
            },
        )
        result = run(state, "that's right")
        assert result.ready_to_call is True
        assert result.tool_name == "lookup_patient"

    def test_tool_input_data_contains_lookup_fields(self):
        state = make_state(
            workflow=Workflow.EXISTING_PATIENT_VERIFICATION,
            step="collecting",
            collected_fields={
                "first_name": "Alice",
                "last_name": "Thompson",
                "phone_number": "(416) 555-0201",
            },
        )
        result = run(state, "yes")
        assert result.tool_input_data.get("first_name") == "Alice"
        assert result.tool_input_data.get("last_name") == "Thompson"
        assert result.tool_input_data.get("phone_number") == "(416) 555-0201"


# ---------------------------------------------------------------------------
# Book appointment (existing patient — needs patient_id first)
# ---------------------------------------------------------------------------


class TestBookAppointment:
    def test_redirects_to_verification_when_no_patient_id(self):
        state = make_state(workflow=Workflow.BOOK_APPOINTMENT, step="start")
        result = run(state, "I want to book a cleaning")
        # Machine should pivot to verification sub-workflow
        assert result.state.workflow == Workflow.EXISTING_PATIENT_VERIFICATION

    def test_ready_when_patient_id_and_fields_present(self):
        state = make_state(
            workflow=Workflow.BOOK_APPOINTMENT,
            step="collecting",
            patient_id="patient-uuid-001",
            collected_fields={
                "appointment_type": "cleaning",
                "preferred_date_from": date(2026, 4, 7),
            },
        )
        result = run(state, "morning please")
        assert result.ready_to_call is True
        assert result.tool_name == "search_slots"

    def test_extracts_appointment_type_from_message(self):
        state = make_state(
            workflow=Workflow.BOOK_APPOINTMENT,
            step="collecting",
            patient_id="patient-uuid-001",
        )
        result = run(state, "I need a general check-up")
        assert result.state.collected_fields.get("appointment_type") == "general_checkup"

    def test_not_ready_without_date(self):
        state = make_state(
            workflow=Workflow.BOOK_APPOINTMENT,
            step="collecting",
            patient_id="patient-uuid-001",
            collected_fields={"appointment_type": "cleaning"},
        )
        result = run(state, "hi")
        assert result.ready_to_call is False
        assert "preferred_date_from" in result.state.missing_fields


# ---------------------------------------------------------------------------
# Reschedule appointment
# ---------------------------------------------------------------------------


class TestRescheduleAppointment:
    def test_requires_verification_when_no_patient_id(self):
        state = make_state(workflow=Workflow.RESCHEDULE_APPOINTMENT, step="start")
        result = run(state, "I want to reschedule")
        assert result.state.workflow == Workflow.EXISTING_PATIENT_VERIFICATION

    def test_ready_when_date_present_with_patient_id(self):
        state = make_state(
            workflow=Workflow.RESCHEDULE_APPOINTMENT,
            step="collecting",
            patient_id="patient-uuid-001",
            collected_fields={
                "appointment_id": "appt-uuid-001",
                "preferred_date_from": date(2026, 4, 14),
            },
        )
        result = run(state, "morning if possible")
        assert result.ready_to_call is True
        assert result.tool_name == "search_slots"

    def test_tool_name_is_search_slots(self):
        assert WORKFLOWS[Workflow.RESCHEDULE_APPOINTMENT].tool_name == "search_slots"


# ---------------------------------------------------------------------------
# Cancel appointment
# ---------------------------------------------------------------------------


class TestCancelAppointment:
    def test_requires_verification_when_no_patient_id(self):
        state = make_state(workflow=Workflow.CANCEL_APPOINTMENT, step="start")
        result = run(state, "cancel my appointment")
        assert result.state.workflow == Workflow.EXISTING_PATIENT_VERIFICATION

    def test_requires_cancel_reason(self):
        wf = WORKFLOWS[Workflow.CANCEL_APPOINTMENT]
        assert "cancel_reason" in wf.required_fields

    def test_extracts_cancel_reason(self):
        state = make_state(
            workflow=Workflow.CANCEL_APPOINTMENT,
            step="collecting",
            patient_id="patient-uuid-001",
            collected_fields={"appointment_id": "appt-uuid-001"},
        )
        result = run(state, "I have a schedule conflict that day")
        assert result.state.collected_fields.get("cancel_reason") == "I have a schedule conflict that day"

    def test_ready_when_reason_present(self):
        state = make_state(
            workflow=Workflow.CANCEL_APPOINTMENT,
            step="collecting",
            patient_id="patient-uuid-001",
            collected_fields={
                "appointment_id": "appt-uuid-001",
                "cancel_reason": "schedule conflict",
            },
        )
        result = run(state, "yes please cancel it")
        # requires_confirmation=True → awaiting confirmation or ready
        assert result.ready_to_call or result.state.step in ("awaiting_confirmation", "ready")

    def test_tool_name_is_cancel_appointment(self):
        assert WORKFLOWS[Workflow.CANCEL_APPOINTMENT].tool_name == "cancel_appointment"


# ---------------------------------------------------------------------------
# Emergency triage
# ---------------------------------------------------------------------------


class TestEmergencyTriage:
    def test_enters_emergency_on_pain_keyword(self):
        result = run(make_state(), "I have severe tooth pain, it's a dental emergency")
        assert result.state.workflow == Workflow.EMERGENCY_TRIAGE

    def test_required_fields_are_name_phone_summary(self):
        wf = WORKFLOWS[Workflow.EMERGENCY_TRIAGE]
        assert "first_name" in wf.required_fields
        assert "phone_number" in wf.required_fields
        assert "emergency_summary" in wf.required_fields

    def test_extracts_emergency_summary(self):
        state = make_state(
            workflow=Workflow.EMERGENCY_TRIAGE,
            step="collecting",
            collected_fields={"first_name": "Jake", "last_name": "Mills", "phone_number": "4165553344"},
        )
        result = run(state, "Cracked molar, severe pain right side, pain level 9 out of 10, started this morning")
        assert result.state.collected_fields.get("emergency_summary") is not None

    def test_ready_when_all_fields_present(self):
        state = make_state(
            workflow=Workflow.EMERGENCY_TRIAGE,
            step="collecting",
            collected_fields={
                "first_name": "Jake",
                "last_name": "Mills",
                "phone_number": "(416) 555-3344",
                "emergency_summary": "Cracked molar, pain 9/10, since this morning",
            },
        )
        result = run(state, "please help me")
        assert result.ready_to_call is True
        assert result.tool_name == "create_staff_notification"

    def test_ready_reply_mentions_staff_notified(self):
        state = make_state(
            workflow=Workflow.EMERGENCY_TRIAGE,
            step="collecting",
            collected_fields={
                "first_name": "Jake",
                "last_name": "Mills",
                "phone_number": "(416) 555-3344",
                "emergency_summary": "Severe pain since this morning",
            },
        )
        result = run(state, "ok")
        assert result.ready_to_call is True
        assert "notified" in result.reply.lower() or "team" in result.reply.lower()

    def test_does_not_require_confirmation(self):
        # Emergency should NOT add a confirmation step — notify staff immediately
        wf = WORKFLOWS[Workflow.EMERGENCY_TRIAGE]
        assert wf.requires_confirmation is False


# ---------------------------------------------------------------------------
# Family booking
# ---------------------------------------------------------------------------


class TestFamilyBooking:
    def test_enters_family_booking_on_keyword(self):
        # Family booking requires patient_id, so the machine correctly pivots to
        # EXISTING_PATIENT_VERIFICATION first, storing _pending_workflow=family_booking.
        result = run(make_state(), "I need to book appointments for me and my kids")
        assert result.state.workflow == Workflow.EXISTING_PATIENT_VERIFICATION
        assert result.state.collected_fields.get("_pending_workflow") == Workflow.FAMILY_BOOKING.value

    def test_required_fields(self):
        wf = WORKFLOWS[Workflow.FAMILY_BOOKING]
        assert "family_count" in wf.required_fields
        assert "appointment_type" in wf.required_fields
        assert "preferred_date_from" in wf.required_fields

    def test_extracts_family_count(self):
        state = make_state(workflow=Workflow.FAMILY_BOOKING, step="collecting", patient_id="p1")
        result = run(state, "There are three of us")
        assert result.state.collected_fields.get("family_count") == 3

    def test_tool_name_is_family_booking(self):
        assert WORKFLOWS[Workflow.FAMILY_BOOKING].tool_name == "book_family_appointments"


# ---------------------------------------------------------------------------
# machine_status helper
# ---------------------------------------------------------------------------


class TestMachineStatus:
    def test_status_shows_all_missing_at_start(self):
        state = make_state(workflow=Workflow.NEW_PATIENT_REGISTRATION, step="collecting")
        status = machine_status(state)
        assert status["workflow"] == Workflow.NEW_PATIENT_REGISTRATION
        assert status["ready_to_call_tool"] is False
        assert len(status["missing_fields"]) == len(WORKFLOWS[Workflow.NEW_PATIENT_REGISTRATION].required_fields)

    def test_status_ready_when_all_collected(self):
        state = make_state(
            workflow=Workflow.EXISTING_PATIENT_VERIFICATION,
            step="collecting",
            collected_fields={
                "first_name": "Alice",
                "last_name": "Smith",
                "phone_number": "(416) 555-0201",
            },
        )
        status = machine_status(state)
        assert status["ready_to_call_tool"] is True
        assert status["tool_name"] == "lookup_patient"


# ---------------------------------------------------------------------------
# Cross-cutting: workflow required fields are all defined in FIELDS
# ---------------------------------------------------------------------------


class TestDefinitionsConsistency:
    def test_all_required_fields_have_definitions(self):
        from state_machine.definitions import FIELDS

        for workflow, wf_def in WORKFLOWS.items():
            for field_key in wf_def.required_fields:
                assert field_key in FIELDS, (
                    f"Workflow {workflow.value} requires field '{field_key}' but it has no FieldDef in FIELDS"
                )

    def test_all_optional_fields_have_definitions(self):
        from state_machine.definitions import FIELDS

        for workflow, wf_def in WORKFLOWS.items():
            for field_key in wf_def.optional_fields:
                assert field_key in FIELDS, (
                    f"Workflow {workflow.value} has optional field '{field_key}' but it has no FieldDef in FIELDS"
                )
