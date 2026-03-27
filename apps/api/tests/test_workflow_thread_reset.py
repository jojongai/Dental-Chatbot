"""Tests for terminal-flow state reset (identity preserved, workflow cleared)."""

from __future__ import annotations

from schemas.chat import (
    IDENTITY_FIELD_KEYS,
    THREAD_TERMINAL_STEPS,
    Workflow,
    WorkflowState,
    workflow_state_after_completed_flow,
    workflow_state_terminal_reply,
)


def test_workflow_state_after_completed_flow_keeps_identity_only() -> None:
    s = WorkflowState(
        workflow=Workflow.CANCEL_APPOINTMENT,
        step="collecting",
        patient_id="pat-1",
        conversation_id="sess-1",
        appointment_id="appt-1",
        collected_fields={
            "first_name": "Jo",
            "last_name": "Ngai",
            "phone_number": "6475550100",
            "appointment_type": "cleaning",
            "cancel_reason": "conflict",
            "preferred_date_from": "2025-04-01",
            "_pending_workflow": "cancel_appointment",
        },
        slot_options=[{"id": "s1", "label": "slot"}],
        selected_slot_id="s1",
        appointment_options=[{"id": "a1", "label": "Appt"}],
        last_clinic_category="hours",
    )
    out = workflow_state_after_completed_flow(s)
    assert out.workflow == Workflow.GENERAL_INQUIRY
    assert out.step == "start"
    assert out.patient_id == "pat-1"
    assert out.conversation_id == "sess-1"
    assert out.appointment_id is None
    assert out.slot_options == []
    assert out.selected_slot_id is None
    assert out.appointment_options == []
    assert out.last_clinic_category is None
    assert set(out.collected_fields.keys()) <= IDENTITY_FIELD_KEYS
    assert out.collected_fields.get("first_name") == "Jo"
    assert "cancel_reason" not in out.collected_fields


def test_thread_terminal_steps_includes_confirmed_and_done() -> None:
    assert "confirmed" in THREAD_TERMINAL_STEPS
    assert "done" in THREAD_TERMINAL_STEPS


def test_workflow_state_terminal_reply_signals_client_echo_with_done() -> None:
    s = WorkflowState(
        workflow=Workflow.CANCEL_APPOINTMENT,
        step="awaiting_confirmation",
        patient_id="pat-1",
        collected_fields={"cancel_reason": "test", "first_name": "Jo"},
    )
    out = workflow_state_terminal_reply(s)
    assert out.step == "done"
    assert out.workflow == Workflow.GENERAL_INQUIRY
    assert "cancel_reason" not in out.collected_fields
