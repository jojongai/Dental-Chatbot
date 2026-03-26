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


class CallerStatus(StrEnum):
    """Result of matching caller_phone to a patient record before booking flows."""

    EXISTING = "existing"  # Found in DB — may book / reschedule with verification as needed
    UNKNOWN = "unknown"  # No match — treat as new caller until registered


class CallerContext(BaseModel):
    """
    Returned on session open and echoed for UI (badge: returning vs new).
    Populated when caller_phone is provided and a practice is known.
    """

    status: CallerStatus
    patient_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_existing_patient: bool | None = None
    match_confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="1.0 when phone + name/DOB align; 0.8 phone-only match",
    )


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
        The user's raw text. Omit or leave empty when is_session_opening is True.
    state
        The WorkflowState from the previous response, echoed back so the server
        can resume mid-workflow without a DB read on every turn.
    caller_phone
        The patient's phone number as captured from caller ID by the SMS gateway.
        When present on the first turn the server pre-populates the phone field so
        the chatbot never has to ask for it again.
    is_session_opening
        When True, simulates the first outbound SMS after a missed call: runs
        caller lookup by phone, returns Maya's opening line, and skips the state
        machine until the patient sends a real message.
    """

    session_id: str = Field(..., examples=["abc123"])
    message: str = Field(default="", examples=["I want to book a cleaning next week"])
    state: WorkflowState | None = None
    caller_phone: str | None = Field(
        None,
        description="Phone number from caller ID. Injected by the SMS gateway on the first turn.",
        examples=["+14165550100"],
    )
    is_session_opening: bool = Field(
        False,
        description="First SMS after missed call — opening message + caller identification only.",
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
    caller_context
        Set when caller_phone was used for identification (session open or first turn).
    """

    reply: str
    state: WorkflowState
    actions: list[ChatAction] = Field(default_factory=list)
    tools_called: list[str] = Field(default_factory=list)
    caller_context: CallerContext | None = None
