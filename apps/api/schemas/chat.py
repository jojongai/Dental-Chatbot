"""
Chat request / response models and workflow state.

WorkflowState is carried client→server on every turn so the backend can be
(mostly) stateless between turns. Persisted snapshots live in
conversation_state_snapshots for audit and recovery.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Workflow and step enumerations
# ---------------------------------------------------------------------------


class Workflow(StrEnum):
    GENERAL_INQUIRY = "general_inquiry"
    NEW_PATIENT_REGISTRATION = "new_patient_registration"
    EXISTING_PATIENT_VERIFICATION = "existing_patient_verification"
    BOOK_APPOINTMENT = "book_appointment"
    RESCHEDULE_APPOINTMENT = "reschedule_appointment"
    CANCEL_APPOINTMENT = "cancel_appointment"
    FAMILY_BOOKING = "family_booking"
    EMERGENCY_TRIAGE = "emergency_triage"
    HANDOFF = "handoff"


# Required fields per workflow are defined in state_machine/definitions.py (WORKFLOWS map).
# That is the single source of truth — do not duplicate them here.

# ---------------------------------------------------------------------------
# Action types the backend can instruct the frontend to render
# ---------------------------------------------------------------------------


class ActionType(StrEnum):
    SHOW_SLOTS = "show_slots"  # display a time-slot picker
    CONFIRM_BOOKING = "confirm_booking"  # show booking summary for confirmation
    CONFIRM_CANCEL = "confirm_cancel"  # confirm before cancelling
    ESCALATE_TO_STAFF = "escalate_to_staff"  # hand off to human
    REQUEST_INFO = "request_info"  # ask user for specific fields
    SHOW_APPOINTMENT_SUMMARY = "show_appointment_summary"


class ChatAction(BaseModel):
    """A structured hint to the frontend about what UI to render next."""

    type: ActionType
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Workflow state (round-tripped between client and server)
# ---------------------------------------------------------------------------



# Fields safe to carry from a verified patient record or prior identity step into a
# **new** SMS thread. Never carry workflow intent, scheduling, or emergency text here.
IDENTITY_FIELD_KEYS: frozenset[str] = frozenset({
    "first_name",
    "last_name",
    "phone_number",
    "date_of_birth",
    "email",
    "insurance_name",
    # Optional trusted label from chart / lookup (never inferred booking intent)
    "patient_status",
    # Full name from DB after successful lookup_patient (cancel/reschedule confirmations)
    "_verified_patient_name",
})

# Machine / router steps that mean "the last workflow finished; next message is a new request."
THREAD_TERMINAL_STEPS: frozenset[str] = frozenset({"confirmed", "done"})

# Appended to terminal completion replies so the thread closes clearly before state reset.
# (No signature here — Maya signs only on interactive closings; see gratitude reply in chat router.)
MAYA_THREAD_CLOSURE_SIGNOFF = "If you need anything else, just let me know."


def _identity_reset_state(state: WorkflowState | None, *, step: str) -> WorkflowState:
    """
    Drop workflow-specific fields; keep identity + patient linkage.
    ``step`` is ``start`` (ready for the next intent) or ``done`` (terminal reply — client echoes
    this so the next POST hits ``THREAD_TERMINAL_STEPS`` and resets again to ``start``).
    """
    if state is None:
        return WorkflowState()
    old_cf = state.collected_fields or {}
    identity = {k: v for k, v in old_cf.items() if k in IDENTITY_FIELD_KEYS}
    return WorkflowState(
        workflow=Workflow.GENERAL_INQUIRY,
        step=step,
        collected_fields=identity,
        missing_fields=[],
        patient_id=state.patient_id,
        conversation_id=state.conversation_id,
        appointment_id=None,
        appointment_request_id=None,
        family_group_id=None,
        last_clinic_category=None,
        slot_options=[],
        selected_slot_id=None,
        appointment_options=[],
    )


def workflow_state_after_completed_flow(state: WorkflowState | None) -> WorkflowState:
    """
    Reset used when the client sends ``step='done'`` (terminal echo) or ``new_conversation``:
    identity only + ``step=start`` for the state machine.
    """
    return _identity_reset_state(state, step="start")


def workflow_state_terminal_reply(state: WorkflowState | None) -> WorkflowState:
    """
    Outbound state after a completed booking/cancel/reschedule/etc.
    Use ``step='done'`` so the client echoes it; ``post_chat`` then applies
    ``workflow_state_after_completed_flow`` and the next turn starts clean (fixes stale workflow).
    """
    return _identity_reset_state(state, step="done")


def workflow_state_for_new_conversation(state: WorkflowState | None) -> WorkflowState:
    """
    Same as ``workflow_state_after_completed_flow`` — client flag ``new_conversation``
    and server-side terminal completion both use one carry-forward policy.
    """
    return workflow_state_after_completed_flow(state)


class WorkflowState(BaseModel):
    """
    Carries all slot-filling progress across turns.
    The frontend echoes this back in ChatRequest.state on every subsequent turn.
    """

    workflow: Workflow = Workflow.GENERAL_INQUIRY
    step: str = "start"  # free-form step label within the workflow

    # Fields collected so far in this workflow turn
    collected_fields: dict[str, Any] = Field(default_factory=dict)

    # Fields still needed before the workflow can proceed
    missing_fields: list[str] = Field(default_factory=list)

    # IDs set as the workflow progresses
    conversation_id: str | None = None
    patient_id: str | None = None
    appointment_request_id: str | None = None
    appointment_id: str | None = None  # for reschedule / cancel flows
    family_group_id: str | None = None

    # Last get_clinic_info category (hours, location, insurance, payment, …) for
    # resolving short follow-ups like "yes" / "no" after Maya offered more detail.
    last_clinic_category: str | None = None

    # Slot selection state — populated after search_slots returns options.
    # List of {"id": slot_id, "label": "Tuesday April 8, 10:00 AM - 11:00 AM"}
    slot_options: list[dict] = Field(default_factory=list)
    # Set after user picks a slot (before book_appointment is called)
    selected_slot_id: str | None = None

    # Appointment selection state — populated when listing a patient's upcoming appointments
    # so they can choose which one to reschedule or cancel.
    # List of {"id": appointment_id, "label": "Cleaning — Mon Apr 14, 10:00 AM"}
    appointment_options: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Chat request / response
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """
    Sent by the frontend / SMS gateway on every user message.

    Fields
    ------
    session_id
        Stable session token (browser or SMS thread ID).
    message
        The user's raw text. Omit or leave empty when is_session_opening is True.
    state
        The WorkflowState from the previous response, echoed back so the server
        can resume mid-workflow without a DB read on every turn.
    is_session_opening
        When True, simulates the first outbound SMS after a missed call: runs
        caller lookup by phone, returns Maya's opening line, and skips the state
        machine until the patient sends a real message.
    """

    session_id: str = Field(..., examples=["abc123"])
    message: str = Field(default="", examples=["I want to book a cleaning next week"])
    state: WorkflowState | None = None
    is_session_opening: bool = Field(
        False,
        description="First SMS after missed call — opening message + caller identification only.",
    )
    new_conversation: bool = Field(
        False,
        description=(
            "When True, treat this as a new thread: strip workflow-specific state "
            "(intent, slots, pending workflows) and keep only identity fields + patient_id. "
            "Use when the same patient starts a new SMS session so prior chat goals are not reused."
        ),
    )

    @model_validator(mode="after")
    def _message_required_unless_opening(self) -> ChatRequest:
        if not self.is_session_opening and not (self.message or "").strip():
            raise ValueError("message is required unless is_session_opening is True")
        return self


class ChatResponse(BaseModel):
    """
    Returned by POST /chat.

    Fields
    ------
    reply
        The assistant's text response shown to the user.
    state
        Updated workflow state — the frontend must echo this back next turn.
    actions
        Structured UI hints (e.g. show a slot picker, confirm booking).
    tools_called
        Names of tools invoked this turn (transparency / debug).
    """

    reply: str
    state: WorkflowState
    actions: list[ChatAction] = Field(default_factory=list)
    tools_called: list[str] = Field(default_factory=list)
