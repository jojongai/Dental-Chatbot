"""
POST /chat  — primary chatbot entry point.

Flow per turn
-------------
1. Resume or start WorkflowState from request body.
2. Run WorkflowStateMachine.process(message).
3. If result.ready_to_call: attempt to call the named tool stub.
   - general_inquiry  → get_clinic_info (DB) → Gemini receptionist (live)
   - all others       → deterministic stubs (raise NotImplementedError until implemented)
4. Append tool reply to the response message if available.
5. Return ChatResponse with updated state, reply, and actions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from schemas.chat import (
    CallerContext,
    CallerStatus,
    ChatRequest,
    ChatResponse,
    WorkflowState,
)
from state_machine.machine import WorkflowStateMachine, machine_status

router = APIRouter(prefix="/chat", tags=["chat"])

# First outbound SMS after a missed call (prototype — static copy only, no DB / lookup).
OPENING_SMS_TEXT = (
    "So sorry we missed your call. This is Maya from Bright Smile Dental. "
    "Are you a new patient or an existing patient?"
)


@router.post("", response_model=ChatResponse, summary="Send a chat message")
async def post_chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
) -> ChatResponse:
    """
    Primary chatbot endpoint.

    The state machine tracks exactly what information has been collected and
    what is still needed for each workflow. It signals `ready_to_call=True`
    when all required fields are present, at which point the router calls the
    corresponding deterministic tool.

    For general_inquiry the tool result is passed through the Gemini-powered
    receptionist to produce a warm, natural-language answer.

    The `state` field in the response must be echoed back by the client on
    every subsequent request so the server can resume the workflow.

    Session opening (`is_session_opening=true`): first outbound SMS after a missed
    call — returns static `OPENING_SMS_TEXT` only (no DB, no caller lookup).
    """
    practice_id = _default_practice_id(db)

    # --- First SMS only: static opening line (prototype — no dynamic handling) ---
    if body.is_session_opening:
        return ChatResponse(
            reply=OPENING_SMS_TEXT,
            state=WorkflowState(),
            caller_context=None,
            tools_called=[],
        )

    is_first_turn = body.state is None
    current_state = body.state or WorkflowState()

    # Pre-populate phone from caller ID so the bot never has to ask for it.
    if body.caller_phone and "phone_number" not in current_state.collected_fields:
        current_state = current_state.model_copy(
            update={"collected_fields": {**current_state.collected_fields, "phone_number": body.caller_phone}}
        )

    # Match caller_phone to a patient record once (before workflows that need patient_id).
    caller_context: CallerContext | None = None
    if body.caller_phone and not current_state.patient_id:
        caller_context, pid = _caller_lookup(db, body.caller_phone, practice_id)
        if pid:
            current_state = current_state.model_copy(update={"patient_id": pid})

    # --- run the state machine ---
    result = _run_machine(current_state, body.message)

    reply = result.reply

    # --- attempt tool call if machine says it's ready ---
    if result.ready_to_call and result.tool_name:
        tool_reply = _call_tool(
            result.tool_name,
            result.tool_input_data,
            db,
            original_message=body.message,
            is_first_message=is_first_turn,
            practice_id=practice_id,
        )
        if tool_reply:
            reply = tool_reply

    return ChatResponse(
        reply=reply,
        state=result.state,
        actions=result.actions,
        tools_called=[result.tool_name] if (result.ready_to_call and result.tool_name) else [],
        caller_context=caller_context,
    )


@router.get("/status", summary="Debug: current machine status")
async def chat_status(
    workflow: str = "general_inquiry",
    step: str = "start",
) -> dict:
    """
    Return what the state machine knows and still needs for a given workflow.
    Useful for staff dashboard and integration testing.
    """
    from schemas.chat import Workflow

    try:
        wf = Workflow(workflow)
    except ValueError:
        return {"error": f"Unknown workflow: {workflow}"}

    dummy_state = WorkflowState(workflow=wf, step=step)
    return machine_status(dummy_state)


# ---------------------------------------------------------------------------
# Machine runner (synchronous wrapper — state machine has no I/O)
# ---------------------------------------------------------------------------


def _run_machine(state: WorkflowState, message: str):
    """Run the state machine and return a MachineResult."""
    return WorkflowStateMachine(state).process(message)


# ---------------------------------------------------------------------------
# Tool dispatcher (calls stub functions; logs graceful fallback on NotImplementedError)
# ---------------------------------------------------------------------------


def _call_tool(
    tool_name: str,
    data: dict,
    db: Session,
    original_message: str = "",
    is_first_message: bool = False,
    practice_id: str = "",
) -> str | None:
    """
    Call the named tool.  Returns a human-readable string to use as the
    chatbot reply, or None if the tool is not yet implemented / failed.

    For get_clinic_info the raw DB result is passed through the Gemini-powered
    receptionist to generate a warm, natural-language answer.
    """
    try:
        match tool_name:
            case "get_clinic_info":
                from schemas.tools import GetClinicInfoInput
                from tools.clinic_tools import get_clinic_info, get_pricing_options

                # Determine the best category to query based on the user's message
                category = _infer_clinic_category(original_message)
                result = get_clinic_info(
                    db,
                    GetClinicInfoInput(category=category, question_hint=original_message),
                    practice_id=practice_id,
                )

                # Fetch pricing options for payment/insurance/no-insurance questions
                pricing: list = []
                if category in ("payment", "insurance") or _is_payment_question(original_message):
                    pricing = get_pricing_options(db, practice_id=practice_id)

                from llm.receptionist import answer_general_inquiry

                return answer_general_inquiry(original_message, result, pricing or None, is_first_message=is_first_message)

            case "lookup_patient":
                from schemas.tools import LookupPatientInput
                from tools.patient_tools import lookup_patient

                lookup_fields = ["phone_number", "last_name", "date_of_birth"]
                result = lookup_patient(
                    db,
                    LookupPatientInput(**_safe_input(data, lookup_fields)),
                    practice_id=practice_id,
                )
                if result.found and result.patient:
                    return f"I found your record — welcome back, {result.patient.first_name}!"
                return (
                    "I wasn't able to find a matching record. "
                    "Please double-check your details or register as a new patient."
                )

            case "create_patient":
                from schemas.tools import CreatePatientInput
                from tools.patient_tools import create_patient

                result = create_patient(db, CreatePatientInput(**data), practice_id=practice_id)
                if result.success and result.patient:
                    return (
                        f"You've been registered! Your patient ID is {result.patient.id}. "
                        "Let me now find available slots."
                    )
                return f"Registration failed: {result.error}"

            case "search_slots":
                from datetime import date as _date
                from datetime import timedelta

                from schemas.tools import SearchSlotsInput
                from tools.scheduling_tools import search_slots

                date_from = data.get("preferred_date_from") or _date.today()
                date_to = date_from + timedelta(days=14)
                result = search_slots(
                    db,
                    SearchSlotsInput(
                        appointment_type_code=data.get("appointment_type", "cleaning"),
                        date_from=date_from,
                        date_to=date_to,
                        preferred_time_of_day=data.get("preferred_time_of_day", "any"),
                    ),
                )
                if result.slots:
                    slot_lines = "\n".join(
                        f"  {i + 1}. {s.date_label} at {s.time_label}" for i, s in enumerate(result.slots[:5])
                    )
                    return f"Here are the next available slots:\n{slot_lines}\n\nWhich works best for you?"
                return "No available slots found for that period. Would you like to try different dates?"

            case "book_appointment":
                from schemas.tools import BookAppointmentInput
                from tools.scheduling_tools import book_appointment

                result = book_appointment(db, BookAppointmentInput(**data))
                if result.success and result.appointment:
                    a = result.appointment
                    provider = a.provider_display_name or "our team"
                    return f"Booked! Your appointment is on {a.date_label} at {a.time_label} with {provider}."
                return f"Booking failed: {result.error}"

            case "reschedule_appointment":
                from schemas.tools import RescheduleAppointmentInput
                from tools.scheduling_tools import reschedule_appointment

                result = reschedule_appointment(db, RescheduleAppointmentInput(**data))
                if result.success and result.new_appointment:
                    a = result.new_appointment
                    return f"Rescheduled! Your new appointment is on {a.date_label} at {a.time_label}."
                return f"Rescheduling failed: {result.error}"

            case "cancel_appointment":
                from schemas.tools import CancelAppointmentInput
                from tools.scheduling_tools import cancel_appointment

                result = cancel_appointment(db, CancelAppointmentInput(**data))
                if result.success:
                    return "Your appointment has been cancelled. We hope to see you again soon."
                return f"Cancellation failed: {result.error}"

            case "book_family_appointments":
                from schemas.tools import BookFamilyAppointmentsInput
                from tools.scheduling_tools import book_family_appointments

                result = book_family_appointments(db, BookFamilyAppointmentsInput(**data))
                if result.all_booked:
                    return f"All {len(result.appointments)} appointments have been booked!"
                failed = ", ".join(result.partial_failures)
                return f"{len(result.appointments)} appointment(s) booked. Could not confirm: {failed}"

            case "create_staff_notification":
                from schemas.tools import CreateStaffNotificationInput
                from tools.notification_tools import create_staff_notification

                result = create_staff_notification(db, CreateStaffNotificationInput(**data), practice_id=practice_id)
                return None  # reply already set by machine (staff notified message)

            case _:
                return None

    except NotImplementedError:
        # Tool stub not yet implemented — silently continue with machine's reply
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "hours": ["hour", "open", "close", "schedule", "when", "time", "saturday", "sunday", "weekend"],
    "location": ["where", "address", "located", "location", "parking", "direction", "find you"],
    "insurance": ["insurance", "coverage", "plan", "benefit", "covered", "accept", "sun life", "manulife"],
    "payment": ["payment", "pay", "no insurance", "uninsured", "self pay", "self-pay", "financing", "membership", "afford"],
}


def _infer_clinic_category(message: str) -> str | None:
    """Map the user's message to the most relevant FAQ category."""
    lower = message.lower()
    best: str | None = None
    best_hits = 0
    for category, keywords in _CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in lower)
        if hits > best_hits:
            best_hits = hits
            best = category
    return best  # None → all categories returned


def _is_payment_question(message: str) -> bool:
    payment_words = ["payment", "pay", "no insurance", "uninsured", "self pay", "self-pay", "financing", "membership", "afford", "cost", "price", "fee"]
    lower = message.lower()
    return any(w in lower for w in payment_words)


def _caller_lookup(db: Session, phone: str, practice_id: str) -> tuple[CallerContext, str | None]:
    """
    Match caller ID to patients.phone_number (normalized). Used before booking flows.
    Returns (CallerContext, patient_id or None).
    """
    from schemas.tools import LookupPatientInput
    from tools.patient_tools import lookup_patient

    lo = lookup_patient(db, LookupPatientInput(phone_number=phone), practice_id)
    if lo.found and lo.patient:
        p = lo.patient
        return (
            CallerContext(
                status=CallerStatus.EXISTING,
                patient_id=p.id,
                first_name=p.first_name,
                last_name=p.last_name,
                is_existing_patient=p.is_existing_patient,
                match_confidence=lo.match_confidence,
            ),
            p.id,
        )
    return (CallerContext(status=CallerStatus.UNKNOWN, match_confidence=0.0), None)


def _default_practice_id(db: Session) -> str:
    """Return the first practice_id in the DB (single-practice deployment)."""
    from models.practice import Practice
    from sqlalchemy import select

    row = db.execute(select(Practice.id).limit(1)).scalar_one_or_none()
    return row or ""


def _safe_input(data: dict, keys: list[str]) -> dict:
    """Return only the specified keys from data (for building tool inputs)."""
    return {k: v for k, v in data.items() if k in keys and v is not None}
