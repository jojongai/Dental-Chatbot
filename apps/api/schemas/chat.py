"""
Chat request / response models and workflow state.

WorkflowState is carried client→server on every turn so the backend can be
(mostly) stateless between turns. Persisted snapshots live in
conversation_state_snapshots for audit and recovery.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

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


# Each workflow has a defined set of fields that must be collected.
# The chatbot uses this map to track progress and know what to ask next.
WORKFLOW_REQUIRED_FIELDS: dict[str, list[str]] = {
    Workflow.NEW_PATIENT_REGISTRATION: [
        "first_name",
        "last_name",
        "phone_number",
        "date_of_birth",
        "appointment_type",
    ],
    Workflow.EXISTING_PATIENT_VERIFICATION: [
        "last_name",
        "date_of_birth",
    ],
    Workflow.BOOK_APPOINTMENT: [
        "patient_id",
        "appointment_type",
        "preferred_date_from",
    ],
    Workflow.RESCHEDULE_APPOINTMENT: [
        "appointment_id",
        "preferred_date_from",
    ],
    Workflow.CANCEL_APPOINTMENT: [
        "appointment_id",
        "cancel_reason",
    ],
    Workflow.FAMILY_BOOKING: [
        "family_member_list",  # [{patient_id, appointment_type}]
        "group_preference",
    ],
    Workflow.EMERGENCY_TRIAGE: [
        "emergency_summary",
        "patient_contact",  # phone or patient_id
    ],
    Workflow.GENERAL_INQUIRY: [],  # no required fields; open-ended
}


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
        The user's raw text.
    state
        The WorkflowState from the previous response, echoed back so the server
        can resume mid-workflow without a DB read on every turn.
    caller_phone
        The patient's phone number as captured from caller ID by the SMS gateway.
        When present on the first turn the server pre-populates the phone field so
        the chatbot never has to ask for it again.
    """

    session_id: str = Field(..., examples=["abc123"])
    message: str = Field(..., examples=["I want to book a cleaning next week"])
    state: WorkflowState | None = None
    caller_phone: str | None = Field(
        None,
        description="Phone number from caller ID. Injected by the SMS gateway on the first turn.",
        examples=["+14165550100"],
    )


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
