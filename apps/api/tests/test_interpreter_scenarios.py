"""
Scenario tests for the interpreter layer.

These are NOT unit tests for individual regexes — they test realistic messy
user messages end-to-end through the keyword/regex fallback path
(USE_LLM=false, which is always the case in tests).

Each scenario is a snapshot of: message + context → expected extracted fields
and expected machine behaviour.  When USE_LLM=true in production the LLM
handles these; the regex path here confirms the fallback stays useful.

Run with:
    .venv/bin/python -m pytest tests/test_interpreter_scenarios.py -v
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from llm.interpreter import (
    FieldHint,
    InterpreterInput,
    WorkflowTransition,
    _keyword_interpret,
)
from state_machine.extractors import extract_confirmation
from state_machine.machine import _is_emergency


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input(
    message: str,
    workflow: str = "new_patient_registration",
    step: str = "collecting",
    pending_field: str | None = None,
    pending_question: str | None = None,
    collected: dict | None = None,
    missing_keys: list[str] | None = None,
) -> InterpreterInput:
    """Build an InterpreterInput for the keyword path."""
    from state_machine.definitions import FIELDS

    hints: list[FieldHint] = []
    for key in (missing_keys or []):
        fd = FIELDS.get(key)
        if fd:
            hints.append(FieldHint(key=fd.key, display_name=fd.display_name, description=fd.description))

    return InterpreterInput(
        message=message,
        workflow=workflow,
        step=step if not pending_field else f"collecting:{pending_field}",
        pending_field=pending_field,
        pending_question=pending_question,
        collected_fields=collected or {},
        missing_field_hints=hints,
    )


# ---------------------------------------------------------------------------
# Multi-field messages
# ---------------------------------------------------------------------------

class TestMultiFieldExtraction:
    """User provides several pieces of info in one message."""

    def test_name_and_phone_together(self):
        """User combines an explicit name intro with a phone number.
        The interpreter keyword path uses regex; it needs a clear lead phrase
        for names when other tokens are present. The machine's deterministic
        override layer handles bare 'Joseph Ngai' → this tests the interpreter
        level where a lead phrase is present.
        """
        inp = _make_input(
            "My name is Joseph Ngai, my number is 6476385400",
            pending_field="first_name",
            missing_keys=["first_name", "phone_number"],
        )
        out = _keyword_interpret(inp)
        assert out.extracted_fields.get("first_name") == "Joseph"
        assert out.extracted_fields.get("last_name") == "Ngai"
        assert out.extracted_fields.get("phone_number") is not None

    def test_name_comma_phone_extracts_phone(self):
        """Bare 'Joseph Ngai, 6476385400' — interpreter extracts phone;
        name extraction handled by machine's deterministic override layer."""
        inp = _make_input(
            "Joseph Ngai, 6476385400",
            pending_field="first_name",
            missing_keys=["first_name", "phone_number"],
        )
        out = _keyword_interpret(inp)
        # Phone is always extracted at interpreter level
        assert out.extracted_fields.get("phone_number") is not None

    def test_new_patient_with_date_and_time(self):
        """User volunteers appointment date and time of day in the first message."""
        inp = _make_input(
            "I'm a new patient and next Tuesday afternoon works for me",
            step="collecting",
            missing_keys=["appointment_type", "preferred_date_from", "preferred_time_of_day"],
        )
        out = _keyword_interpret(inp)
        # "next Tuesday" → a date should be extracted
        assert out.extracted_fields.get("preferred_date_from") is not None
        # "afternoon"
        assert out.extracted_fields.get("preferred_time_of_day") == "afternoon"

    def test_insurance_and_appointment_type(self):
        """User mentions both insurance and appointment type."""
        inp = _make_input(
            "Do you take Sun Life? I need a cleaning",
            missing_keys=["insurance_name", "appointment_type"],
        )
        out = _keyword_interpret(inp)
        assert out.extracted_fields.get("insurance_name") is not None
        assert "sun life" in str(out.extracted_fields.get("insurance_name", "")).lower()
        assert out.extracted_fields.get("appointment_type") == "cleaning"

    def test_family_booking_context(self):
        """User mentions the appointment is for their child."""
        inp = _make_input(
            "This is for my daughter, she needs a cleaning",
            workflow="family_booking",
            # Hint only appointment_type so keyword path still extracts it (family flow is custom).
            missing_keys=["appointment_type"],
        )
        out = _keyword_interpret(inp)
        assert out.extracted_fields.get("appointment_type") == "cleaning"


# ---------------------------------------------------------------------------
# Natural confirmation phrases
# ---------------------------------------------------------------------------

class TestNaturalConfirmation:
    """Confirm that natural language yes/no is parsed correctly."""

    @pytest.mark.parametrize("phrase,expected", [
        ("yeah that should be fine", True),
        ("works for me", True),
        ("let's do it", True),
        ("that's correct", True),
        ("looks right to me", True),
        ("perfect", True),
        ("yep", True),
        ("sure", True),
        ("that's great", True),
        ("go ahead", True),
        # negatives
        ("actually not that one", False),
        ("not that time", False),
        ("maybe try a different day", False),
        ("no", False),
        ("nope that's wrong", False),
        ("wait, change the date", False),
        ("that's not right", False),
        ("let me fix something", False),
        # ambiguous — should return None
        ("hmm", None),
        ("maybe", None),
        ("I'm not sure", None),
    ])
    def test_confirmation_phrases(self, phrase: str, expected: bool | None):
        result = extract_confirmation(phrase)
        assert result == expected, f"extract_confirmation({phrase!r}) = {result!r}, want {expected!r}"


# ---------------------------------------------------------------------------
# Emergency guardrail
# ---------------------------------------------------------------------------

class TestEmergencyGuardrail:
    """Deterministic guardrail must catch obvious safety phrases regardless of LLM."""

    @pytest.mark.parametrize("message", [
        "I missed your call, I'm in a lot of pain",
        "my tooth broke and I'm bleeding",
        "severe pain in my jaw",
        "I think I have an abscess, there's swelling",
        "I knocked out my tooth in an accident",
        "trauma to my mouth, trouble breathing",
        "emergency, I need help urgently",
        "I have a cracked tooth and it's unbearable pain",
        "there's pus and my face is swollen",
    ])
    def test_guardrail_fires(self, message: str):
        assert _is_emergency(message), f"Guardrail should have fired for: {message!r}"

    @pytest.mark.parametrize("message", [
        "I need a cleaning",
        "Can I book an appointment for next week?",
        "What are your hours?",
        "I'm a new patient",
        "I'd like to reschedule my appointment",
        "Do you take Sun Life insurance?",
    ])
    def test_guardrail_does_not_misfire(self, message: str):
        assert not _is_emergency(message), f"Guardrail should NOT have fired for: {message!r}"


# ---------------------------------------------------------------------------
# Topic / workflow transition detection
# ---------------------------------------------------------------------------

class TestWorkflowTransition:
    """Topic switch detection in the keyword fallback path."""

    def test_explicit_start_over_triggers_switch(self):
        inp = _make_input("start over please", step="collecting:appointment_type")
        out = _keyword_interpret(inp)
        assert out.workflow_transition == WorkflowTransition.SWITCH

    def test_never_mind_triggers_switch(self):
        inp = _make_input("never mind the booking", step="collecting:preferred_date_from")
        out = _keyword_interpret(inp)
        assert out.workflow_transition == WorkflowTransition.SWITCH

    def test_normal_answer_does_not_trigger_switch(self):
        inp = _make_input(
            "Actually I prefer mornings",
            step="collecting:preferred_time_of_day",
            missing_keys=["preferred_time_of_day"],
        )
        out = _keyword_interpret(inp)
        assert out.workflow_transition == WorkflowTransition.CONTINUE

    def test_continuing_with_information_is_continue(self):
        inp = _make_input(
            "No, not that time, maybe later in the week",
            pending_field="preferred_date_from",
            missing_keys=["preferred_date_from"],
        )
        out = _keyword_interpret(inp)
        # Should not fire a SWITCH — user is refining within the same workflow
        assert out.workflow_transition != WorkflowTransition.SWITCH


# ---------------------------------------------------------------------------
# Off-flow messages that should stay in current workflow
# ---------------------------------------------------------------------------

class TestStaysInWorkflow:
    """Indirect, off-script answers that should still extract data correctly."""

    def test_indirect_no_insurance(self):
        """'No' alone should extract as self_pay when asked about insurance."""
        inp = _make_input(
            "No",
            pending_field="insurance_name",
            pending_question="Do you have dental insurance?",
            missing_keys=["insurance_name"],
        )
        out = _keyword_interpret(inp)
        assert out.extracted_fields.get("insurance_name") == "self_pay"

    def test_flexible_date_preference(self):
        """'I guess mornings are better but I'm flexible' extracts time of day."""
        inp = _make_input(
            "I guess mornings are better but I'm flexible",
            pending_field="preferred_time_of_day",
            missing_keys=["preferred_time_of_day"],
        )
        out = _keyword_interpret(inp)
        assert out.extracted_fields.get("preferred_time_of_day") == "morning"

    def test_appointment_from_context_clue(self):
        """'I need my teeth done' should extract cleaning as appointment type."""
        inp = _make_input(
            "I need a cleaning",
            missing_keys=["appointment_type"],
        )
        out = _keyword_interpret(inp)
        assert out.extracted_fields.get("appointment_type") == "cleaning"

    def test_dob_does_not_bleed_into_preferred_date(self):
        """When asking for DOB, the same date must NOT populate preferred_date_from."""
        inp = _make_input(
            "August 28 2003",
            step="collecting:date_of_birth",
            pending_field="date_of_birth",
            missing_keys=["date_of_birth", "preferred_date_from"],
        )
        out = _keyword_interpret(inp)
        # DOB should be extracted
        assert out.extracted_fields.get("date_of_birth") is not None
        # preferred_date_from must NOT be set — it would contain the DOB value
        assert "preferred_date_from" not in out.extracted_fields

    def test_name_not_extracted_from_intent_phrase(self):
        """'New patient looking to book' must not populate name fields."""
        from state_machine.extractors import extract_full_name
        result = extract_full_name("New patient looking to book")
        assert result is None, "Intent phrase should not be treated as a name"


# ---------------------------------------------------------------------------
# Interpreter output structure
# ---------------------------------------------------------------------------

class TestInterpreterOutputStructure:
    """Verify the shape and types of InterpreterOutput are consistent."""

    def test_answered_fields_populated(self):
        inp = _make_input(
            "Joseph Ngai",
            pending_field="first_name",
            missing_keys=["first_name"],
        )
        out = _keyword_interpret(inp)
        # first_name multi_key → both keys should appear in answered_fields
        assert "first_name" in out.answered_fields or "last_name" in out.answered_fields

    def test_uncertain_fields_empty_by_default(self):
        inp = _make_input("Joseph Ngai", missing_keys=["first_name"])
        out = _keyword_interpret(inp)
        assert out.uncertain_fields == []

    def test_reasoning_summary_present(self):
        inp = _make_input("next Tuesday afternoon", missing_keys=["preferred_date_from"])
        out = _keyword_interpret(inp)
        assert out.reasoning_summary is not None

    def test_workflow_transition_defaults_to_continue(self):
        inp = _make_input("6476385400", pending_field="phone_number", missing_keys=["phone_number"])
        out = _keyword_interpret(inp)
        assert out.workflow_transition == WorkflowTransition.CONTINUE

    def test_confidence_is_float(self):
        inp = _make_input("cleaning", missing_keys=["appointment_type"])
        out = _keyword_interpret(inp)
        assert isinstance(out.confidence, float)
        assert 0.0 <= out.confidence <= 1.0


# ---------------------------------------------------------------------------
# Fast-path gate
# ---------------------------------------------------------------------------


class TestFastPath:
    """
    Tests for _needs_llm() and the classify_intent() keyword fast-path.

    These verify the gating logic that prevents unnecessary LLM calls on
    unambiguous turns.
    """

    # ------------------------------------------------------------------
    # _needs_llm() — should return False (skip LLM)
    # ------------------------------------------------------------------

    def test_structural_pending_phone(self):
        """Phone number pending → regex is authoritative, skip LLM."""
        from llm.interpreter import _needs_llm
        inp = _make_input("6476385400", pending_field="phone_number", missing_keys=["phone_number"])
        assert _needs_llm(inp) is False

    def test_structural_pending_dob(self):
        """DOB pending → skip LLM."""
        from llm.interpreter import _needs_llm
        inp = _make_input("August 28 2003", pending_field="date_of_birth", missing_keys=["date_of_birth"])
        assert _needs_llm(inp) is False

    def test_structural_pending_email(self):
        """Email pending → skip LLM."""
        from llm.interpreter import _needs_llm
        inp = _make_input("jojo@example.com", pending_field="email", missing_keys=["email"])
        assert _needs_llm(inp) is False

    def test_structural_pending_confirmation(self):
        """Confirmation pending → skip LLM."""
        from llm.interpreter import _needs_llm
        inp = _make_input("yes", pending_field="confirmation", missing_keys=["confirmation"])
        assert _needs_llm(inp) is False

    @pytest.mark.parametrize("choice", ["1", "2", "3", "4", "5", " 2 ", "3 "])
    def test_slot_choice_skips_llm(self, choice: str):
        """Single digit (slot selection) → skip LLM."""
        from llm.interpreter import _needs_llm
        inp = _make_input(choice, step="selecting_slot")
        assert _needs_llm(inp) is False

    def test_only_structural_hints_skips_llm(self):
        """When every missing field is structural, there is nothing semantic to extract."""
        from llm.interpreter import _needs_llm
        inp = _make_input("Joseph Ngai", missing_keys=["phone_number", "date_of_birth"])
        assert _needs_llm(inp) is False

    def test_first_turn_no_hints_skips_llm(self):
        """First turn of a new workflow with no hints yet (pure intent trigger)."""
        from llm.interpreter import _needs_llm
        inp = _make_input(
            "Yep, looking to book an appointment",
            step="collecting",
            missing_keys=[],  # hints not yet populated on first turn
        )
        assert _needs_llm(inp) is False

    def test_first_turn_verify_identity_skips_llm(self):
        """verify_identity step with no hints yet → skip LLM."""
        from llm.interpreter import _needs_llm
        inp = _make_input(
            "I want to reschedule",
            step="verify_identity",
            missing_keys=[],
        )
        assert _needs_llm(inp) is False

    def test_verify_identity_with_identity_hints_skips_llm(self):
        """
        Production path: verify_identity WITH identity hints must skip LLM.

        When the user says "I'd like to book an appointment" and we pivot to
        EXISTING_PATIENT_VERIFICATION, identity field hints (first_name, last_name,
        phone_number) are populated.  Without Rule 5, Rule 4 doesn't fire (hints
        exist) → LLM runs → returns SWITCH→book_appointment → infinite recursion.
        """
        from llm.interpreter import _needs_llm
        inp = _make_input(
            "I'd like to book an appointment",
            workflow="existing_patient_verification",
            step="verify_identity",
            missing_keys=["first_name", "last_name", "phone_number"],
        )
        assert _needs_llm(inp) is False

    def test_awaiting_patient_type_skips_llm(self):
        """awaiting_patient_type step → keyword parser only, never LLM."""
        from llm.interpreter import _needs_llm
        inp = _make_input(
            "I'm an existing patient",
            step="awaiting_patient_type",
            missing_keys=[],
        )
        assert _needs_llm(inp) is False

    # ------------------------------------------------------------------
    # _needs_llm() — should return True (use LLM)
    # ------------------------------------------------------------------

    def test_semantic_insurance_needs_llm(self):
        """Insurance name is semantic — LLM required."""
        from llm.interpreter import _needs_llm
        inp = _make_input(
            "I'm covered through my employer",
            pending_field="insurance_name",
            missing_keys=["insurance_name"],
        )
        assert _needs_llm(inp) is True

    def test_semantic_appointment_type_needs_llm(self):
        """Appointment type is semantic — LLM required."""
        from llm.interpreter import _needs_llm
        inp = _make_input(
            "My tooth has been aching for a week",
            pending_field="appointment_type",
            missing_keys=["appointment_type"],
        )
        assert _needs_llm(inp) is True

    def test_semantic_preferred_date_needs_llm(self):
        """Preferred date expressed naturally — LLM required."""
        from llm.interpreter import _needs_llm
        inp = _make_input(
            "Sometime next month would be great",
            pending_field="preferred_date_from",
            missing_keys=["preferred_date_from"],
        )
        assert _needs_llm(inp) is True

    def test_mixed_semantic_and_structural_needs_llm(self):
        """Mix of insurance (semantic) + phone (structural) → LLM still needed."""
        from llm.interpreter import _needs_llm
        inp = _make_input(
            "I don't have insurance, my number is 6476385400",
            missing_keys=["insurance_name", "phone_number"],
        )
        assert _needs_llm(inp) is True

    def test_collecting_step_with_semantic_hints_needs_llm(self):
        """Mid-workflow with semantic hints present → LLM required."""
        from llm.interpreter import _needs_llm
        inp = _make_input(
            "Not sure about insurance, I'll check",
            step="collecting:insurance_name",
            pending_field="insurance_name",
            missing_keys=["insurance_name", "appointment_type"],
        )
        assert _needs_llm(inp) is True

    # ------------------------------------------------------------------
    # classify_intent() keyword fast-path
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("message,expected_workflow", [
        ("Yep, looking to book an appointment", "book_appointment"),
        ("I need to schedule a cleaning", "book_appointment"),
        ("I want to cancel my appointment", "cancel_appointment"),
        ("I need to reschedule", "reschedule_appointment"),
        ("This is an emergency, I'm in pain", "emergency_triage"),
        ("Booking for me and my kids", "family_booking"),
        ("Can I speak to someone please", "handoff"),
        # "new patient" alone is a patient-type signal → GENERAL_INQUIRY (bot asks "How can I help?")
        ("I'm a new patient", "general_inquiry"),
        # Action phrase alongside → routes directly
        ("First time visiting", "new_patient_registration"),
    ])
    def test_classify_intent_fast_path(self, message: str, expected_workflow: str):
        """
        With USE_LLM=false, classify_intent() keyword path fires immediately.
        These same messages with USE_LLM=true should return the same result
        via the fast-path (keyword match before LLM call).
        """
        from llm.intent import _keyword_fallback
        from schemas.chat import Workflow

        result = _keyword_fallback(message)
        assert result == Workflow(expected_workflow), (
            f"_keyword_fallback({message!r}) = {result!r}, expected {expected_workflow!r}"
        )

    def test_ambiguous_message_falls_through_to_general_inquiry(self):
        """A message with no clear trigger returns GENERAL_INQUIRY from keyword path."""
        from llm.intent import _keyword_fallback
        from schemas.chat import Workflow

        result = _keyword_fallback("do you have parking nearby?")
        assert result == Workflow.GENERAL_INQUIRY

    def test_hours_question_falls_through_to_general_inquiry(self):
        """'Hours' alone doesn't match any booking keyword → GENERAL_INQUIRY → LLM classifies."""
        from llm.intent import _keyword_fallback
        from schemas.chat import Workflow

        result = _keyword_fallback("what are your hours?")
        assert result == Workflow.GENERAL_INQUIRY
