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
            tools_called=[],
        )

    is_first_turn = body.state is None
    current_state = body.state or WorkflowState()

    # --- slot selection turn (user chose from presented options) ---
    if current_state.step == "selecting_slot" and current_state.slot_options:
        return _handle_slot_selection(body.message, current_state, db, practice_id)

    # --- disambiguation retry: two records matched → user replied with email ---
    if current_state.step == "disambiguating":
        current_state = _apply_verification_retry(current_state, body.message)

    # --- run the state machine ---
    result = _run_machine(current_state, body.message)

    reply = result.reply
    updated_state = result.state
    tools_called: list[str] = []

    # --- attempt tool call if machine says it's ready ---
    if result.ready_to_call and result.tool_name:
        reply, updated_state, tools_called = _dispatch_tool(
            tool_name=result.tool_name,
            tool_input_data=result.tool_input_data,
            state=updated_state,
            db=db,
            original_message=body.message,
            is_first_message=is_first_turn,
            practice_id=practice_id,
        )

    return ChatResponse(
        reply=reply,
        state=updated_state,
        actions=result.actions,
        tools_called=tools_called,
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


def _apply_verification_retry(state: WorkflowState, message: str) -> WorkflowState:
    """
    Called when step == 'disambiguating' (two records matched name+phone).
    Extract the email from the user's reply and reset step to 'collecting' so
    the state machine sees all required fields present and fires lookup_patient again.
    """
    from state_machine.extractors import extract_email

    collected = dict(state.collected_fields)
    if "email" not in collected:
        email = extract_email(message)
        if email:
            collected["email"] = email

    return state.model_copy(
        update={
            "step": "collecting",
            "collected_fields": collected,
            "missing_fields": [],
        }
    )


def _run_machine(state: WorkflowState, message: str):
    """Run the state machine and return a MachineResult."""
    return WorkflowStateMachine(state).process(message)


# ---------------------------------------------------------------------------
# Multi-step tool dispatcher
# Returns (reply, updated_state, tools_called)
# ---------------------------------------------------------------------------


def _dispatch_tool(
    tool_name: str,
    tool_input_data: dict,
    state: WorkflowState,
    db: Session,
    original_message: str = "",
    is_first_message: bool = False,
    practice_id: str = "",
) -> tuple[str, WorkflowState, list[str]]:
    """
    Call the appropriate tool and return (reply, updated_state, tools_called).

    NEW PATIENT BOOKING multi-step:
      create_patient → auto search_slots → present options → user picks → book_appointment
    """
    try:
        match tool_name:

            # ------------------------------------------------------------------
            # General inquiry — DB + Gemini receptionist
            # ------------------------------------------------------------------
            case "get_clinic_info":
                from schemas.tools import GetClinicInfoInput
                from tools.clinic_tools import get_clinic_info, get_pricing_options

                category = _infer_clinic_category(original_message)
                result = get_clinic_info(
                    db,
                    GetClinicInfoInput(category=category, question_hint=original_message),
                    practice_id=practice_id,
                )
                pricing: list = []
                if category in ("payment", "insurance") or _is_payment_question(original_message):
                    pricing = get_pricing_options(db, practice_id=practice_id)

                from llm.receptionist import answer_general_inquiry

                reply = answer_general_inquiry(
                    original_message, result, pricing or None, is_first_message=is_first_message
                )
                return reply, state, ["get_clinic_info"]

            # ------------------------------------------------------------------
            # Patient lookup (existing-patient verification)
            # Lookup key: first_name + last_name + phone  (should be unique).
            # Edge case: two records share all three → ask for email once.
            # ------------------------------------------------------------------
            case "lookup_patient":
                from schemas.tools import LookupPatientInput
                from tools.patient_tools import lookup_patient

                lookup_fields = ["first_name", "last_name", "phone_number", "email"]
                result = lookup_patient(
                    db,
                    LookupPatientInput(**_safe_input(tool_input_data, lookup_fields)),
                    practice_id=practice_id,
                )

                # ── Verified ─────────────────────────────────────────────────
                if result.found and result.patient:
                    p = result.patient
                    verified_state = state.model_copy(update={"patient_id": p.id})
                    return _resume_pending_workflow(verified_state, db, p.first_name, tool_input_data)

                # ── Duplicate records — ask for email as tiebreaker ──────────
                if result.multiple_matches:
                    # Don't clear other fields; next turn's _apply_verification_retry
                    # will extract email and retry lookup automatically.
                    new_state = state.model_copy(
                        update={
                            "step": "disambiguating",
                            "collected_fields": {**state.collected_fields, "_lookup_retry": True},
                        }
                    )
                    return (
                        "I found more than one record matching that name and number. "
                        "Could you share your email address so I can find the right file?",
                        new_state,
                        ["lookup_patient"],
                    )

                # ── Not found ────────────────────────────────────────────────
                was_retry = state.collected_fields.get("_lookup_retry", False)
                not_found_msg = (
                    "I still wasn't able to match those details to a patient record. "
                    "Please call (416) 555-0100 and we can sort it out, "
                    "or would you like to register as a new patient?"
                    if was_retry else
                    "I wasn't able to find a record with that name and number. "
                    "Could you double-check, or would you like to register as a new patient?"
                )
                # Clear identity fields so the user can re-enter them
                retry_state = state.model_copy(
                    update={
                        "step": "collecting",
                        "collected_fields": {
                            k: v
                            for k, v in state.collected_fields.items()
                            if not k.startswith("_")
                            and k not in ("first_name", "last_name", "phone_number", "email")
                        },
                        "missing_fields": ["first_name", "last_name", "phone_number"],
                    }
                )
                return not_found_msg, retry_state, ["lookup_patient"]

            # ------------------------------------------------------------------
            # New patient registration → immediately search slots on success
            # ------------------------------------------------------------------
            case "create_patient":
                from schemas.tools import CreatePatientInput
                from tools.patient_tools import create_patient

                result = create_patient(db, CreatePatientInput(**tool_input_data), practice_id=practice_id)
                if not result.success or not result.patient:
                    return f"I couldn't register you: {result.error}", state, ["create_patient"]

                # Store patient_id, then immediately search slots
                new_state = state.model_copy(update={"patient_id": result.patient.id})
                reply, new_state, slot_tools = _search_and_present_slots(
                    tool_input_data, new_state, db,
                    preamble=f"Welcome {result.patient.first_name}! You're all registered."
                )
                return reply, new_state, ["create_patient"] + slot_tools

            # ------------------------------------------------------------------
            # Slot search (existing patient booking)
            # ------------------------------------------------------------------
            case "search_slots":
                reply, new_state, tools = _search_and_present_slots(tool_input_data, state, db)
                return reply, new_state, tools

            # ------------------------------------------------------------------
            # Stubs for flows not yet implemented
            # ------------------------------------------------------------------
            case "reschedule_appointment" | "cancel_appointment" | "book_family_appointments":
                return (
                    "That feature is coming soon. Please call us at (416) 555-0100 and we will be happy to help.",
                    state,
                    [],
                )

            case "create_staff_notification":
                return (
                    "I've notified our team. A staff member will be in touch with you shortly.",
                    state,
                    ["create_staff_notification"],
                )

            case _:
                return state.workflow + " — coming soon.", state, []

    except NotImplementedError:
        return (
            "That feature is not yet available. Please call us at (416) 555-0100.",
            state,
            [],
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Tool dispatch error: %s", exc)
        return (
            "Something went wrong on our end. Please try again or call us at (416) 555-0100.",
            state,
            [],
        )


# ---------------------------------------------------------------------------
# Post-verification router — resumes the workflow that triggered verification
# ---------------------------------------------------------------------------


def _resume_pending_workflow(
    state: WorkflowState,
    db: Session,
    first_name: str,
    tool_input_data: dict,
) -> tuple[str, WorkflowState, list[str]]:
    """
    After a successful patient lookup, resume the workflow that was pending.

    Possible pending workflows:
      - book_appointment  → search slots for the verified patient
      - reschedule_appointment → (stub for now)
      - cancel_appointment     → (stub for now)
      - None / general     → generic welcome-back reply
    """
    pending = state.collected_fields.get("_pending_workflow", "")

    if pending == "book_appointment":
        reply, new_state, tools = _search_and_present_slots(
            tool_input_data,
            state,
            db,
            preamble=f"Got it, welcome back {first_name}!",
        )
        return reply, new_state, ["lookup_patient"] + tools

    if pending in ("reschedule_appointment", "cancel_appointment"):
        return (
            f"Welcome back {first_name}! That feature is coming soon — "
            "please call us at (416) 555-0100 and we'll be happy to help.",
            state,
            ["lookup_patient"],
        )

    # Verified but no specific pending workflow (standalone verification)
    return (
        f"Got it, welcome back {first_name}! How can I help you today?",
        state,
        ["lookup_patient"],
    )


# ---------------------------------------------------------------------------
# Slot search helper — used by create_patient and search_slots branches
# ---------------------------------------------------------------------------


def _search_and_present_slots(
    data: dict,
    state: WorkflowState,
    db: Session,
    preamble: str = "",
) -> tuple[str, WorkflowState, list[str]]:
    """
    Run search_slots, format options 1-3, set state.step='selecting_slot'.
    Returns (reply, updated_state, tools_called).
    """
    from datetime import date as _date, timedelta
    from schemas.tools import SearchSlotsInput
    from tools.scheduling_tools import search_slots
    from tools.validators import normalize_appointment_type

    raw_type = data.get("appointment_type") or data.get("appointment_type_code") or "cleaning"
    try:
        appt_code = normalize_appointment_type(str(raw_type))
    except ValueError:
        appt_code = "cleaning"

    date_from = data.get("preferred_date_from") or _date.today() + timedelta(days=1)
    if isinstance(date_from, str):
        try:
            from datetime import date as _d
            date_from = _d.fromisoformat(date_from)
        except ValueError:
            date_from = _date.today() + timedelta(days=1)

    date_to = date_from + timedelta(days=14)

    result = search_slots(
        db,
        SearchSlotsInput(
            appointment_type_code=appt_code,
            date_from=date_from,
            date_to=date_to,
            preferred_time_of_day=data.get("preferred_time_of_day") or "any",
        ),
    )

    if not result.slots:
        reply = (
            f"{preamble}\n\n" if preamble else ""
        ) + (
            "I couldn't find any available slots in that period. "
            "Would you like to try a different date or time of day?"
        )
        return reply.strip(), state, ["search_slots"]

    options = result.slots[:3]
    slot_options = [{"id": s.id, "label": f"{s.date_label}, {s.time_label}"} for s in options]
    lines = "\n".join(f"{i + 1}. {s.date_label}, {s.time_label}" for i, s in enumerate(options))

    reply = (f"{preamble}\n\n" if preamble else "") + (
        f"Here are the next available slots for your {options[0].appointment_type_display}:\n\n"
        f"{lines}\n\n"
        "Which one works best for you? Reply with 1, 2, or 3."
    )

    new_state = state.model_copy(update={"step": "selecting_slot", "slot_options": slot_options})
    return reply.strip(), new_state, ["search_slots"]


# ---------------------------------------------------------------------------
# Slot selection handler — called when step == 'selecting_slot'
# ---------------------------------------------------------------------------


def _handle_slot_selection(
    message: str,
    state: WorkflowState,
    db: Session,
    practice_id: str,
) -> ChatResponse:
    """
    Parse the user's slot choice, book it, return confirmation.
    """
    from schemas.tools import BookAppointmentInput
    from state_machine.extractors import extract_slot_choice
    from tools.scheduling_tools import book_appointment
    from tools.validators import normalize_appointment_type

    choice = extract_slot_choice(message)

    if choice is None or choice < 1 or choice > len(state.slot_options):
        # Patient may be asking for a different date rather than picking a slot.
        # Try to extract a new date preference from the message and re-search.
        from state_machine.extractors import extract_preferred_date, extract_time_of_day

        new_date = extract_preferred_date(message)
        if new_date is not None or _is_slot_rejection(message):
            search_data = dict(state.collected_fields)
            if new_date:
                search_data["preferred_date_from"] = new_date
            new_time = extract_time_of_day(message)
            if new_time:
                search_data["preferred_time_of_day"] = new_time

            reply, new_state, _ = _search_and_present_slots(
                search_data,
                state,
                db,
                preamble="No problem — let me check other times." if not new_date else "",
            )
            return ChatResponse(reply=reply, state=new_state)

        available = len(state.slot_options)
        return ChatResponse(
            reply=f"Please reply with a number between 1 and {available} to choose a slot.",
            state=state,
        )

    chosen = state.slot_options[choice - 1]
    slot_id = chosen["id"]

    raw_type = state.collected_fields.get("appointment_type") or "cleaning"
    try:
        appt_code = normalize_appointment_type(str(raw_type))
    except ValueError:
        appt_code = "cleaning"

    result = book_appointment(
        db,
        BookAppointmentInput(
            patient_id=state.patient_id,
            slot_id=slot_id,
            appointment_type_code=appt_code,
            booked_via="chatbot",
        ),
    )

    if not result.success or not result.appointment:
        # Slot was taken — re-present remaining options
        remaining = [o for i, o in enumerate(state.slot_options) if i + 1 != choice]
        if remaining:
            lines = "\n".join(f"{i + 1}. {o['label']}" for i, o in enumerate(remaining))
            new_state = state.model_copy(update={"slot_options": remaining})
            return ChatResponse(
                reply=(
                    f"Sorry, that slot just got taken. Here are the remaining options:\n\n{lines}\n\n"
                    "Reply with 1 or 2 to choose."
                ),
                state=new_state,
            )
        return ChatResponse(
            reply=(
                "That slot is no longer available and I'm out of options for that window. "
                "Want me to search a different date or time?"
            ),
            state=state.model_copy(update={"step": "collecting", "slot_options": []}),
        )

    a = result.appointment
    provider = f" with {a.provider_display_name}" if a.provider_display_name else ""
    confirm_reply = (
        f"You're all set! Your {a.appointment_type_display} is confirmed:\n\n"
        f"Date: {a.date_label}\n"
        f"Time: {a.time_label}{provider}\n"
        f"Location: {a.location_name}\n\n"
        "We'll see you then! Reply anytime if you need to make changes. - Maya"
    )

    new_state = state.model_copy(
        update={
            "step": "confirmed",
            "appointment_id": a.id,
            "slot_options": [],
            "selected_slot_id": slot_id,
        }
    )
    return ChatResponse(
        reply=confirm_reply,
        state=new_state,
        actions=[],
        tools_called=["book_appointment"],
    )


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


def _is_slot_rejection(message: str) -> bool:
    """Return True if the patient is declining the presented slots."""
    lower = message.lower()
    rejection_phrases = [
        "none of those", "none of them", "don't work", "doesn't work",
        "can't do", "cannot do", "not available", "other options",
        "different", "something else", "other time", "other day",
        "no thanks", "not those", "any other",
    ]
    return any(p in lower for p in rejection_phrases)


def _is_payment_question(message: str) -> bool:
    payment_words = ["payment", "pay", "no insurance", "uninsured", "self pay", "self-pay", "financing", "membership", "afford", "cost", "price", "fee"]
    lower = message.lower()
    return any(w in lower for w in payment_words)



def _default_practice_id(db: Session) -> str:
    """Return the first practice_id in the DB (single-practice deployment)."""
    from models.practice import Practice
    from sqlalchemy import select

    row = db.execute(select(Practice.id).limit(1)).scalar_one_or_none()
    return row or ""


def _safe_input(data: dict, keys: list[str]) -> dict:
    """Return only the specified keys from data (for building tool inputs)."""
    return {k: v for k, v in data.items() if k in keys and v is not None}
