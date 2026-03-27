"""Tests for short thanks-only replies after completed flows."""

from __future__ import annotations

from schemas.chat import Workflow, WorkflowState
from routers.chat import (
    GRATITUDE_IDLE_REPLY,
    _has_prior_identity_or_patient,
    _is_idle_for_gratitude_reply,
    _looks_like_gratitude_only_closure,
)


def test_gratitude_detection() -> None:
    assert _looks_like_gratitude_only_closure("Nothing else thanks a lot")
    assert _looks_like_gratitude_only_closure("Thanks!")
    assert _looks_like_gratitude_only_closure("That's all, appreciate it")
    assert not _looks_like_gratitude_only_closure("I want to book a cleaning")
    assert not _looks_like_gratitude_only_closure("Thanks, can I reschedule?")


def test_idle_state_after_terminal_reset() -> None:
    s = WorkflowState(
        workflow=Workflow.GENERAL_INQUIRY,
        step="start",
        patient_id="p1",
        collected_fields={"first_name": "Jo"},
    )
    assert _is_idle_for_gratitude_reply(s)
    assert _has_prior_identity_or_patient(s)


def test_not_idle_when_selecting_slot() -> None:
    s = WorkflowState(
        workflow=Workflow.GENERAL_INQUIRY,
        step="selecting_slot",
        patient_id="p1",
        slot_options=[{"id": "s1", "label": "x"}],
    )
    assert not _is_idle_for_gratitude_reply(s)


def test_gratitude_reply_constant_has_maya_signature() -> None:
    assert "- Maya" in GRATITUDE_IDLE_REPLY
