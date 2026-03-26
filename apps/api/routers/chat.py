"""
POST /chat  — primary chatbot entry point.

Flow
----
1. Resume or create a Conversation row from session_token.
2. Persist the user message to conversation_messages.
3. Dispatch to the appropriate workflow handler based on current state.
4. Each handler may call one or more tool stubs (patient_tools, scheduling_tools, …).
5. Return ChatResponse with updated WorkflowState and optional UI Actions.

All workflow dispatch logic lives here as stubs; replace with LLM orchestration
(e.g. function-calling / tool-use) in the next implementation phase.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from schemas.chat import (
    ActionType,
    ChatAction,
    ChatRequest,
    ChatResponse,
    Workflow,
    WorkflowState,
)

router = APIRouter(prefix="/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# Helper: intent detection stub
# ---------------------------------------------------------------------------


def _detect_workflow(message: str, current: WorkflowState) -> Workflow:
    """
    Naive keyword-based intent detection — replaced by LLM classification later.

    Keyword map (case-insensitive):
    - 'new patient', 'register', 'first time'  → new_patient_registration
    - 'emergency', 'pain', 'broken', 'swollen' → emergency_triage
    - 'reschedule', 'move', 'change appointment'→ reschedule_appointment
    - 'cancel'                                  → cancel_appointment
    - 'family', 'kids', 'children', 'spouse'   → family_booking
    - 'book', 'schedule', 'appointment',
      'cleaning', 'checkup', 'check-up'        → book_appointment
    - anything else                             → general_inquiry
    """
    if current.workflow != Workflow.GENERAL_INQUIRY:
        return current.workflow

    lower = message.lower()
    if any(k in lower for k in ("new patient", "register", "first time", "first visit")):
        return Workflow.NEW_PATIENT_REGISTRATION
    if any(k in lower for k in ("emergency", "severe pain", "broken tooth", "swollen")):
        return Workflow.EMERGENCY_TRIAGE
    if any(k in lower for k in ("reschedule", "move my", "change my appointment")):
        return Workflow.RESCHEDULE_APPOINTMENT
    if "cancel" in lower:
        return Workflow.CANCEL_APPOINTMENT
    if any(k in lower for k in ("family", "kids", "children", "my kid", "spouse", "husband", "wife")):
        return Workflow.FAMILY_BOOKING
    if any(k in lower for k in ("book", "schedule", "appointment", "cleaning", "checkup", "check-up", "exam")):
        return Workflow.BOOK_APPOINTMENT
    return Workflow.GENERAL_INQUIRY


# ---------------------------------------------------------------------------
# Workflow stub handlers
# ---------------------------------------------------------------------------


def _handle_general_inquiry(message: str, state: WorkflowState) -> ChatResponse:
    """
    TODO: call get_clinic_info tool, pass result to LLM for answer generation.
    """
    return ChatResponse(
        reply=(
            "I can help with information about our services, insurance, hours, and location. "
            "What would you like to know?"
        ),
        state=state,
        tools_called=["get_clinic_info"],
    )


def _handle_new_patient_registration(message: str, state: WorkflowState) -> ChatResponse:
    """
    Collect: first_name, last_name, phone_number, date_of_birth, insurance_name.
    Then: appointment_type + slot search.

    TODO: replace stub with LLM slot-filling + create_patient tool call.
    """
    return ChatResponse(
        reply=("Welcome! I'd love to get you registered. Could I start with your full name and date of birth?"),
        state=WorkflowState(
            **{**state.model_dump(), "workflow": Workflow.NEW_PATIENT_REGISTRATION, "step": "collect_name"}
        ),
        actions=[
            ChatAction(
                type=ActionType.REQUEST_INFO,
                payload={"fields": ["first_name", "last_name", "date_of_birth"]},
            )
        ],
        tools_called=[],
    )


def _handle_existing_patient_verification(message: str, state: WorkflowState) -> ChatResponse:
    """
    Collect: last_name + date_of_birth (+ optionally phone_number).
    Call lookup_patient; on match → proceed to booking workflow.

    TODO: replace stub with lookup_patient tool call.
    """
    return ChatResponse(
        reply="To verify your identity, could you please provide your last name and date of birth?",
        state=WorkflowState(
            **{**state.model_dump(), "workflow": Workflow.EXISTING_PATIENT_VERIFICATION, "step": "collect_identity"}
        ),
        actions=[ChatAction(type=ActionType.REQUEST_INFO, payload={"fields": ["last_name", "date_of_birth"]})],
        tools_called=[],
    )


def _handle_book_appointment(message: str, state: WorkflowState) -> ChatResponse:
    """
    Required fields: patient_id, appointment_type, preferred_date_from.
    Steps: verify patient identity → search_slots → present options → book_appointment.

    TODO: replace stub with full tool chain.
    """
    if not state.patient_id:
        return _handle_existing_patient_verification(message, state)

    return ChatResponse(
        reply=(
            "I can help you book an appointment. "
            "What type of appointment would you like — cleaning, general check-up, or something else?"
        ),
        state=WorkflowState(
            **{**state.model_dump(), "workflow": Workflow.BOOK_APPOINTMENT, "step": "collect_appointment_type"}
        ),
        actions=[
            ChatAction(
                type=ActionType.REQUEST_INFO,
                payload={"fields": ["appointment_type", "preferred_date_from", "preferred_time_of_day"]},
            )
        ],
        tools_called=[],
    )


def _handle_emergency_triage(message: str, state: WorkflowState) -> ChatResponse:
    """
    Collect: emergency_summary, patient contact.
    Call: book_appointment(is_emergency=True) + create_staff_notification(type='emergency').
    Inform patient that staff have been notified.

    TODO: replace stub with tool chain + staff notification.
    """
    return ChatResponse(
        reply=(
            "I'm sorry to hear you're in pain. I'm flagging this as an emergency right now — "
            "our dental team will be notified immediately.\n\n"
            "Could you briefly describe what's happening? For example: where is the pain, "
            "how severe is it (1–10), and when did it start?"
        ),
        state=WorkflowState(
            **{**state.model_dump(), "workflow": Workflow.EMERGENCY_TRIAGE, "step": "collect_emergency_summary"}
        ),
        actions=[
            ChatAction(type=ActionType.ESCALATE_TO_STAFF, payload={"reason": "emergency_flagged"}),
            ChatAction(type=ActionType.REQUEST_INFO, payload={"fields": ["emergency_summary", "patient_contact"]}),
        ],
        tools_called=["create_staff_notification"],
    )


def _handle_reschedule_appointment(message: str, state: WorkflowState) -> ChatResponse:
    """
    Collect: appointment_id (or identify from patient record), new date preference.
    Call: search_slots → reschedule_appointment.

    TODO: replace stub.
    """
    return ChatResponse(
        reply="I can help you reschedule. Could you confirm your name and the appointment you'd like to move?",
        state=WorkflowState(
            **{**state.model_dump(), "workflow": Workflow.RESCHEDULE_APPOINTMENT, "step": "identify_appointment"}
        ),
        actions=[ChatAction(type=ActionType.REQUEST_INFO, payload={"fields": ["last_name", "date_of_birth"]})],
        tools_called=[],
    )


def _handle_cancel_appointment(message: str, state: WorkflowState) -> ChatResponse:
    """
    Collect: appointment_id, cancel_reason.
    Call: cancel_appointment.

    TODO: replace stub.
    """
    return ChatResponse(
        reply="I can cancel your appointment. Could you confirm your name and the date of the appointment you'd like to cancel?",  # noqa: E501
        state=WorkflowState(
            **{**state.model_dump(), "workflow": Workflow.CANCEL_APPOINTMENT, "step": "identify_appointment"}
        ),
        actions=[ChatAction(type=ActionType.CONFIRM_CANCEL, payload={})],
        tools_called=[],
    )


def _handle_family_booking(message: str, state: WorkflowState) -> ChatResponse:
    """
    Collect: list of family members (patient_id or inline create) + appointment types.
    Call: book_family_appointments with group_preference='back_to_back'.

    TODO: replace stub.
    """
    return ChatResponse(
        reply=(
            "Happy to book for your whole family! "
            "How many people need appointments, and what type of appointment does each person need? "
            "(e.g. 'My daughter needs a cleaning and I need a check-up')"
        ),
        state=WorkflowState(
            **{**state.model_dump(), "workflow": Workflow.FAMILY_BOOKING, "step": "collect_family_members"}
        ),
        actions=[
            ChatAction(
                type=ActionType.REQUEST_INFO,
                payload={"fields": ["family_member_list", "group_preference"]},
            )
        ],
        tools_called=[],
    )


# ---------------------------------------------------------------------------
# Workflow dispatch table
# ---------------------------------------------------------------------------

_WORKFLOW_HANDLERS = {
    Workflow.GENERAL_INQUIRY: _handle_general_inquiry,
    Workflow.NEW_PATIENT_REGISTRATION: _handle_new_patient_registration,
    Workflow.EXISTING_PATIENT_VERIFICATION: _handle_existing_patient_verification,
    Workflow.BOOK_APPOINTMENT: _handle_book_appointment,
    Workflow.EMERGENCY_TRIAGE: _handle_emergency_triage,
    Workflow.RESCHEDULE_APPOINTMENT: _handle_reschedule_appointment,
    Workflow.CANCEL_APPOINTMENT: _handle_cancel_appointment,
    Workflow.FAMILY_BOOKING: _handle_family_booking,
}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("", response_model=ChatResponse, summary="Send a chat message")
async def post_chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
) -> ChatResponse:
    """
    Primary chatbot endpoint.

    1. Detects or resumes workflow from `body.state`.
    2. Dispatches to the appropriate workflow handler stub.
    3. Returns a structured reply with updated state and UI actions.

    **Not yet connected to an LLM** — handlers return deterministic stub replies.
    Replace handler bodies with LLM tool-use calls in Phase 1 implementation.
    """
    current_state = body.state or WorkflowState()
    workflow = _detect_workflow(body.message, current_state)
    current_state = WorkflowState(**{**current_state.model_dump(), "workflow": workflow})

    handler = _WORKFLOW_HANDLERS.get(workflow, _handle_general_inquiry)
    return handler(body.message, current_state)
