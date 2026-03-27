"""
Intent detection tests — always run against the keyword fallback (USE_LLM=false).

Two categories:
  1. Keyword path — exact matches the old _INTENT_MAP would catch.
  2. Natural language — phrases that would have missed with keywords but the
     LLM prompt is designed to catch. These run against keyword fallback here
     and serve as a contract: if/when you run with USE_LLM=true these should
     all pass with the LLM classifier.
"""
from __future__ import annotations

import os

import pytest

os.environ["USE_LLM"] = "false"

from schemas.chat import Workflow, WorkflowState
from llm.intent import classify_intent, _keyword_fallback


def intent(message: str) -> Workflow:
    """Run keyword-based classification (USE_LLM=false is set above)."""
    return classify_intent(message)


def detect(message: str) -> Workflow:
    """Full detect_intent path — includes mid-workflow guard."""
    from state_machine.machine import detect_intent
    return detect_intent(message, WorkflowState())


# ---------------------------------------------------------------------------
# Keyword path — existing exact-match coverage
# ---------------------------------------------------------------------------


class TestKeywordIntentMap:
    def test_new_patient_explicit(self):
        # "new patient" alone is a patient-type signal, not a workflow intent.
        # The LLM (or receptionist fallback) will ask "How can I help you?" in response.
        assert intent("I'm a new patient") == Workflow.GENERAL_INQUIRY

    def test_new_patient_first_time(self):
        # "First time visiting" has a clear action component → new patient registration.
        assert intent("First time visiting") == Workflow.NEW_PATIENT_REGISTRATION

    def test_new_patient_wants_to_register(self):
        # Explicit registration intent → routes directly.
        assert intent("I want to register as a new patient") == Workflow.NEW_PATIENT_REGISTRATION

    def test_existing_patient_explicit(self):
        # "existing patient" alone is a patient-type signal with no stated intent.
        # Receptionist will ask "How can I help you?" in response.
        assert intent("I'm an existing patient") == Workflow.GENERAL_INQUIRY

    def test_existing_patient_been_before(self):
        # Same — just identifies as existing, no action stated.
        assert intent("I've been a patient there before") == Workflow.GENERAL_INQUIRY

    def test_existing_patient_wants_to_book(self):
        # When they also state a booking intent, it routes correctly.
        assert intent("I'm an existing patient and want to book an appointment") == Workflow.BOOK_APPOINTMENT

    def test_book_appointment_cleaning(self):
        assert intent("I need a cleaning") == Workflow.BOOK_APPOINTMENT

    def test_book_appointment_checkup(self):
        assert intent("I want to schedule a checkup") == Workflow.BOOK_APPOINTMENT

    def test_reschedule(self):
        assert intent("I need to reschedule") == Workflow.RESCHEDULE_APPOINTMENT

    def test_cancel(self):
        assert intent("I want to cancel my appointment") == Workflow.CANCEL_APPOINTMENT

    def test_emergency_toothache(self):
        assert intent("I have a toothache") == Workflow.EMERGENCY_TRIAGE

    def test_emergency_broken_tooth(self):
        assert intent("I broke a tooth") == Workflow.EMERGENCY_TRIAGE

    def test_family_kids(self):
        assert intent("Appointments for my kids") == Workflow.FAMILY_BOOKING

    def test_family_spouse(self):
        assert intent("My husband and I need cleanings") == Workflow.FAMILY_BOOKING

    def test_handoff_speak_to(self):
        assert intent("I'd like to speak to someone") == Workflow.HANDOFF

    def test_handoff_call_me(self):
        assert intent("Can you call me back?") == Workflow.HANDOFF

    def test_general_hours(self):
        assert intent("What are your hours?") == Workflow.GENERAL_INQUIRY

    def test_general_insurance(self):
        assert intent("Do you take Sun Life?") == Workflow.GENERAL_INQUIRY

    def test_general_fallback(self):
        assert intent("Hello") == Workflow.GENERAL_INQUIRY


# ---------------------------------------------------------------------------
# Natural language — phrases the keyword map would have missed.
# These document the LLM classifier's contract; keyword path returns
# GENERAL_INQUIRY for them which is the safe fallback.
# ---------------------------------------------------------------------------


class TestNaturalLanguagePhrases:
    """
    These phrases should ideally map to a specific workflow when USE_LLM=true.
    The keyword fallback correctly returns GENERAL_INQUIRY (safe default).
    Tests here assert the fallback, not the LLM output.
    """

    def test_never_been_before_falls_back(self):
        # LLM should → new_patient_registration; keyword → general_inquiry
        result = intent("I've never been there before")
        assert result in (Workflow.NEW_PATIENT_REGISTRATION, Workflow.GENERAL_INQUIRY)

    def test_need_to_see_dentist_falls_back(self):
        # LLM should → book_appointment
        result = intent("I need to see the dentist")
        assert result in (Workflow.BOOK_APPOINTMENT, Workflow.GENERAL_INQUIRY)

    def test_pain_no_keyword_falls_back(self):
        # "it hurts so bad" — LLM should → emergency_triage
        result = intent("it hurts so bad I can't sleep")
        assert result in (Workflow.EMERGENCY_TRIAGE, Workflow.GENERAL_INQUIRY)

    def test_cant_make_it_falls_back(self):
        # LLM should → reschedule or cancel
        result = intent("I can't make it on Thursday")
        assert result in (
            Workflow.RESCHEDULE_APPOINTMENT,
            Workflow.CANCEL_APPOINTMENT,
            Workflow.GENERAL_INQUIRY,
        )

    def test_whole_family_falls_back(self):
        # LLM should → family_booking
        result = intent("We all need to come in together")
        assert result in (Workflow.FAMILY_BOOKING, Workflow.GENERAL_INQUIRY)


# ---------------------------------------------------------------------------
# Mid-workflow guard — stays in workflow regardless of message content
# ---------------------------------------------------------------------------


class TestMidWorkflowGuard:
    def test_stays_in_new_patient_workflow(self):
        from state_machine.machine import detect_intent
        state = WorkflowState(workflow=Workflow.NEW_PATIENT_REGISTRATION, step="collecting")
        # Even a message that looks like booking doesn't pivot the workflow
        result = detect_intent("I want to book an appointment actually", state)
        assert result == Workflow.NEW_PATIENT_REGISTRATION

    def test_stays_in_booking_workflow(self):
        from state_machine.machine import detect_intent
        state = WorkflowState(workflow=Workflow.BOOK_APPOINTMENT, step="collecting")
        result = detect_intent("cleaning please", state)
        assert result == Workflow.BOOK_APPOINTMENT

    def test_start_over_resets_to_general(self):
        from state_machine.machine import detect_intent
        state = WorkflowState(workflow=Workflow.BOOK_APPOINTMENT, step="collecting")
        result = detect_intent("start over", state)
        assert result == Workflow.GENERAL_INQUIRY

    def test_cancel_everything_resets(self):
        from state_machine.machine import detect_intent
        state = WorkflowState(workflow=Workflow.NEW_PATIENT_REGISTRATION, step="collecting")
        result = detect_intent("cancel everything", state)
        assert result == Workflow.GENERAL_INQUIRY

    def test_emergency_escapes_mid_flow(self):
        from state_machine.machine import detect_intent
        state = WorkflowState(workflow=Workflow.BOOK_APPOINTMENT, step="collecting")
        result = detect_intent("I have severe pain, this is an emergency", state)
        assert result == Workflow.EMERGENCY_TRIAGE

    def test_actually_cancel_escapes(self):
        from state_machine.machine import detect_intent
        state = WorkflowState(workflow=Workflow.BOOK_APPOINTMENT, step="collecting")
        result = detect_intent("actually i want to cancel my appointment", state)
        assert result == Workflow.CANCEL_APPOINTMENT

    def test_speak_to_someone_escapes(self):
        from state_machine.machine import detect_intent
        state = WorkflowState(workflow=Workflow.BOOK_APPOINTMENT, step="collecting")
        result = detect_intent("speak to someone", state)
        assert result == Workflow.HANDOFF

    def test_failed_lookup_yes_routes_to_registration(self):
        from state_machine.machine import detect_intent
        state = WorkflowState(
            workflow=Workflow.EXISTING_PATIENT_VERIFICATION,
            step="collecting",
            collected_fields={"_lookup_failed_offer_registration": True},
        )
        result = detect_intent("yes please", state)
        assert result == Workflow.NEW_PATIENT_REGISTRATION

    def test_failed_lookup_register_routes_to_registration(self):
        from state_machine.machine import detect_intent
        state = WorkflowState(
            workflow=Workflow.EXISTING_PATIENT_VERIFICATION,
            step="collecting",
            collected_fields={"_lookup_failed_offer_registration": True},
        )
        result = detect_intent("I'd like to register as a new patient", state)
        assert result == Workflow.NEW_PATIENT_REGISTRATION

    def test_no_registration_escape_without_flag(self):
        from state_machine.machine import detect_intent
        state = WorkflowState(
            workflow=Workflow.EXISTING_PATIENT_VERIFICATION,
            step="collecting",
        )
        result = detect_intent("yes please", state)
        assert result == Workflow.EXISTING_PATIENT_VERIFICATION
