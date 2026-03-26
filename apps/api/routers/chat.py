"""
POST /chat  — primary chatbot entry point.

Flow per turn
-------------
1. Resume or start WorkflowState from request body.
2. Run WorkflowStateMachine.process(message).
3. If result.ready_to_call: attempt to call the named tool stub.
   (Stubs raise NotImplementedError → graceful fallback until implemented.)
4. Append tool reply to the response message if available.
5. Return ChatResponse with updated state, reply, and actions.

The state machine handles all slot-filling logic deterministically.
LLM orchestration (replacing tool stubs) is a Phase 1 enhancement.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from schemas.chat import ChatRequest, ChatResponse, WorkflowState
from state_machine.machine import WorkflowStateMachine, machine_status

router = APIRouter(prefix="/chat", tags=["chat"])


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
    corresponding deterministic tool (currently stubs — returns 501 until
    the tool bodies are implemented).

    The `state` field in the response must be echoed back by the client on
    every subsequent request so the server can resume the workflow.
    """
    current_state = body.state or WorkflowState()

    # --- run the state machine ---
    result = _run_machine(current_state, body.message)

    reply = result.reply

    # --- attempt tool call if machine says it's ready ---
    if result.ready_to_call and result.tool_name:
        tool_reply = _call_tool(result.tool_name, result.tool_input_data, db)
        if tool_reply:
            reply = f"{reply}\n\n{tool_reply}"

    return ChatResponse(
        reply=reply,
        state=result.state,
        actions=result.actions,
        tools_called=[result.tool_name] if (result.ready_to_call and result.tool_name) else [],
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


def _call_tool(tool_name: str, data: dict, db: Session) -> str | None:
    """
    Call the named tool stub.  Returns a human-readable string appended to
    the chatbot reply, or None if the tool is not yet implemented.
    """
    try:
        match tool_name:
            case "get_clinic_info":
                from schemas.tools import GetClinicInfoInput
                from tools.clinic_tools import get_clinic_info

                result = get_clinic_info(db, GetClinicInfoInput(**data), practice_id="")
                return _format_clinic_info(result)

            case "lookup_patient":
                from schemas.tools import LookupPatientInput
                from tools.patient_tools import lookup_patient

                lookup_fields = ["phone_number", "last_name", "date_of_birth"]
                result = lookup_patient(db, LookupPatientInput(**_safe_input(data, lookup_fields)))
                if result.found and result.patient:
                    return f"I found your record — welcome back, {result.patient.first_name}!"
                return (
                    "I wasn't able to find a matching record. "
                    "Please double-check your details or register as a new patient."
                )

            case "create_patient":
                from schemas.tools import CreatePatientInput
                from tools.patient_tools import create_patient

                result = create_patient(db, CreatePatientInput(**data), practice_id="")
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

                result = create_staff_notification(db, CreateStaffNotificationInput(**data), practice_id="")
                return None  # reply already set by machine (staff notified message)

            case _:
                return None

    except NotImplementedError:
        # Tool stub not yet implemented — silently continue with machine's reply
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _format_clinic_info(result) -> str:
    parts: list[str] = []
    if result.settings:
        s = result.settings
        parts.append(f"**{s.location_name}**\n{s.address}\nHours: {s.hours_summary}")
        insurance_line = "We accept all major dental insurance plans"
        if s.self_pay_available:
            insurance_line += ", and offer self-pay options"
        if s.membership_available:
            insurance_line += ", membership plans"
        if s.financing_available:
            insurance_line += ", and flexible financing"
        parts.append(insurance_line + ".")
    if result.faq_entries:
        for faq in result.faq_entries[:3]:
            parts.append(f"**Q: {faq.question}**\n{faq.answer}")
    return "\n\n".join(parts) if parts else "I'm happy to answer any questions about our practice."


def _safe_input(data: dict, keys: list[str]) -> dict:
    """Return only the specified keys from data (for building tool inputs)."""
    return {k: v for k, v in data.items() if k in keys and v is not None}
