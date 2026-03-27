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
    Workflow,
    WorkflowState,
    workflow_state_for_new_conversation,
)
from state_machine.machine import WorkflowStateMachine, machine_status

router = APIRouter(prefix="/chat", tags=["chat"])

# First outbound SMS after a missed call (prototype — static copy only, no DB / lookup).
OPENING_SMS_TEXT = (
    "So sorry we missed your call! This is Maya from Bright Smile Dental. "
    "How can I help you today?"
)


def _is_first_substantive_turn(state: WorkflowState) -> bool:
    """
    True when the client has not yet advanced past the initial post-opening state:
    general inquiry, step start, and only identity pre-fill (or empty collected_fields).
    Used so the first user message after the opening SMS still gets receptionist
    first-turn behaviour even though state is non-null.
    """
    from schemas.chat import IDENTITY_FIELD_KEYS

    if state.workflow != Workflow.GENERAL_INQUIRY or state.step != "start":
        return False
    cf = state.collected_fields or {}
    return all(k in IDENTITY_FIELD_KEYS for k in cf)


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

    current_state = body.state or WorkflowState()
    if body.new_conversation:
        current_state = workflow_state_for_new_conversation(body.state)

    # First "real" user turn for receptionist copy: after opening, state is often
    # empty GENERAL_INQUIRY/start — still the patient's first substantive message.
    is_first_turn = body.state is None or _is_first_substantive_turn(current_state)

    # --- appointment selection turn (reschedule/cancel: patient picks which appointment) ---
    if current_state.step == "selecting_appointment" and current_state.appointment_options:
        return _handle_appointment_selection(body.message, current_state, db)

    # --- slot selection turn (user chose from presented options) ---
    if current_state.step == "selecting_slot" and current_state.slot_options:
        return _handle_slot_selection(body.message, current_state, db, practice_id)

    # --- no-slots retry: user wants to try a different date after search returned empty ---
    if current_state.step == "no_slots_retry":
        return _handle_no_slots_retry(body.message, current_state, db, practice_id)

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

                category, followup = _resolve_clinic_category_and_followup(
                    original_message, state
                )
                question_hint = _build_clinic_question_hint(
                    original_message, category, followup
                )

                result = get_clinic_info(
                    db,
                    GetClinicInfoInput(category=category, question_hint=question_hint),
                    practice_id=practice_id,
                )
                pricing: list = []
                if category in ("payment", "insurance") or _is_payment_question(
                    original_message
                ):
                    pricing = get_pricing_options(db, practice_id=practice_id)

                from llm.receptionist import answer_general_inquiry

                reply = answer_general_inquiry(
                    original_message,
                    result,
                    pricing or None,
                    is_first_message=is_first_message,
                    inquiry_followup=followup,
                    inquiry_category=category,
                )
                new_state = state.model_copy(update={"last_clinic_category": category})
                return reply, new_state, ["get_clinic_info"]

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
                # Clear identity fields so the user can re-enter them;
                # set flag so detect_intent allows routing to NEW_PATIENT_REGISTRATION.
                retry_collected = {
                    k: v
                    for k, v in state.collected_fields.items()
                    if not k.startswith("_")
                    and k not in ("first_name", "last_name", "phone_number", "email")
                }
                retry_collected["_lookup_failed_offer_registration"] = True
                retry_state = state.model_copy(
                    update={
                        "step": "collecting",
                        "collected_fields": retry_collected,
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
                    already_exists = result.error and "already exists" in result.error.lower()
                    if already_exists:
                        from schemas.tools import LookupPatientInput
                        from tools.patient_tools import lookup_patient

                        lookup_fields = ["first_name", "last_name", "phone_number"]
                        lookup_result = lookup_patient(
                            db,
                            LookupPatientInput(**_safe_input(tool_input_data, lookup_fields)),
                            practice_id=practice_id,
                        )
                        if lookup_result.found and lookup_result.patient:
                            p = lookup_result.patient
                            verified_state = state.model_copy(update={"patient_id": p.id})
                            reply, vs, resume_tools = _resume_pending_workflow(
                                verified_state, db, p.first_name, tool_input_data
                            )
                            all_tools = list(dict.fromkeys(
                                ["create_patient", "lookup_patient"] + resume_tools
                            ))
                            return (
                                f"It looks like you're already in our system, {p.first_name}! "
                                f"{reply}",
                                vs,
                                all_tools,
                            )
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
            # Cancel appointment — direct tool call (no slot search needed)
            # ------------------------------------------------------------------
            case "cancel_appointment":
                from schemas.tools import CancelAppointmentInput
                from tools.scheduling_tools import cancel_appointment

                if not state.appointment_id:
                    return (
                        "I lost track of which appointment to cancel — could you let me know the date?",
                        state,
                        [],
                    )
                result = cancel_appointment(
                    db,
                    CancelAppointmentInput(
                        appointment_id=state.appointment_id,
                        cancel_reason=tool_input_data.get("cancel_reason") or "Patient request",
                    ),
                )
                if not result.success or not result.cancelled_appointment:
                    return (
                        f"I wasn't able to cancel that appointment: {result.error or 'unknown error'}. "
                        "Please call us at (416) 555-0100 and we can sort it out.",
                        state,
                        ["cancel_appointment"],
                    )
                a = result.cancelled_appointment
                reply = (
                    f"Done — your {a.appointment_type_display} on {a.date_label} at {a.time_label} "
                    "has been cancelled. If you ever want to rebook, just text us anytime. - Maya"
                )
                new_state = state.model_copy(update={"step": "confirmed"})
                return reply, new_state, ["cancel_appointment"]

            # ------------------------------------------------------------------
            # Family booking
            # ------------------------------------------------------------------
            case "book_family_appointments":
                return _dispatch_family_booking(tool_input_data, state, db, practice_id)

            case "create_staff_notification":
                return _dispatch_emergency_notification(
                    tool_input_data, state, db, practice_id
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
        from state_machine.definitions import WORKFLOWS, FIELDS
        bk_def = WORKFLOWS[Workflow.BOOK_APPOINTMENT]
        new_state = state.model_copy(
            update={
                "workflow": Workflow.BOOK_APPOINTMENT,
                "step": "collecting",
                "collected_fields": {
                    k: v for k, v in state.collected_fields.items()
                    if not k.startswith("_")
                },
                "missing_fields": list(bk_def.required_fields),
            }
        )
        first_field = bk_def.required_fields[0]
        fd = FIELDS.get(first_field)
        prompt = fd.prompt if fd else f"Could you provide your {first_field.replace('_', ' ')}?"
        return (
            f"Got it, welcome back {first_name}! {prompt}",
            new_state,
            ["lookup_patient"],
        )

    if pending in ("reschedule_appointment", "cancel_appointment"):
        reply, new_state = _list_and_present_appointments(state, db, first_name)
        return reply, new_state, ["lookup_patient", "list_patient_appointments"]

    if pending == "family_booking":
        new_state = state.model_copy(update={"workflow": "family_booking", "step": "collecting"})
        return (
            f"Got it, welcome back {first_name}! "
            "Let's get everyone booked — how many people are we scheduling?",
            new_state,
            ["lookup_patient"],
        )

    # Verified but no specific pending workflow (standalone verification)
    return (
        f"Got it, welcome back {first_name}! How can I help you today?",
        state,
        ["lookup_patient"],
    )


# ---------------------------------------------------------------------------
# Appointment listing helper — fetch upcoming appts and present as a pick-list
# ---------------------------------------------------------------------------


def _list_and_present_appointments(
    state: WorkflowState,
    db: Session,
    first_name: str,
) -> tuple[str, WorkflowState]:
    """
    List a verified patient's upcoming appointments and ask them to pick one.
    Returns (reply, updated_state) where state.step = 'selecting_appointment'.
    """
    from schemas.tools import ListPatientAppointmentsInput
    from tools.scheduling_tools import list_patient_appointments

    result = list_patient_appointments(
        db, ListPatientAppointmentsInput(patient_id=state.patient_id)
    )

    if not result.appointments:
        pending = state.collected_fields.get("_pending_workflow", "")
        action = "reschedule" if pending == "reschedule_appointment" else "cancel"
        reply = (
            f"I looked up your file, {first_name}, but I don't see any upcoming appointments. "
            f"Nothing to {action} right now! Is there anything else I can help you with?"
        )
        new_state = state.model_copy(update={"step": "done"})
        return reply, new_state

    pending = state.collected_fields.get("_pending_workflow", "")
    verb = "reschedule" if pending == "reschedule_appointment" else "cancel"
    lines = "\n".join(
        f"{i + 1}. {a.appointment_type_display} — {a.date_label}, {a.time_label}"
        for i, a in enumerate(result.appointments)
    )
    appt_options = [
        {"id": a.id, "label": f"{a.appointment_type_display} — {a.date_label}, {a.time_label}"}
        for a in result.appointments
    ]
    reply = (
        f"Hey {first_name}! Here are your upcoming appointments:\n\n"
        f"{lines}\n\n"
        f"Which one would you like to {verb}? Reply with the number."
    )
    new_state = state.model_copy(
        update={"step": "selecting_appointment", "appointment_options": appt_options}
    )
    return reply, new_state


# ---------------------------------------------------------------------------
# Appointment selection handler — called when step == 'selecting_appointment'
# ---------------------------------------------------------------------------


def _handle_appointment_selection(
    message: str,
    state: WorkflowState,
    db: Session,
) -> ChatResponse:
    """
    Parse the patient's appointment choice, store appointment_id, then
    prompt for the next piece of info (new date for reschedule; reason for cancel).
    """
    from state_machine.extractors import extract_slot_choice  # same ordinal logic

    choice = extract_slot_choice(message)

    if choice is None or choice < 1 or choice > len(state.appointment_options):
        available = len(state.appointment_options)
        return ChatResponse(
            reply=f"Please reply with a number between 1 and {available} to choose an appointment.",
            state=state,
        )

    chosen = state.appointment_options[choice - 1]
    appointment_id = chosen["id"]
    label = chosen["label"]

    pending = state.collected_fields.get("_pending_workflow", "")

    # Store appointment_id and reset to collecting so the machine can gather the
    # remaining required fields (preferred_date_from for reschedule, cancel_reason for cancel).
    new_state = state.model_copy(
        update={
            "appointment_id": appointment_id,
            "step": "collecting",
            "appointment_options": [],
            # Clear any stale date fields so the machine prompts fresh
            "collected_fields": {
                k: v
                for k, v in state.collected_fields.items()
                if k not in ("preferred_date_from", "preferred_time_of_day", "cancel_reason")
            },
        }
    )

    if pending == "reschedule_appointment":
        reply = f"Got it — I'll move your {label}. What dates work better for you?"
    else:
        reply = f"Got it — I'll cancel your {label}. Mind sharing the reason? (totally fine if it's just scheduling)"

    return ChatResponse(reply=reply, state=new_state)


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
        retry_state = state.model_copy(update={"step": "no_slots_retry"})
        return reply.strip(), retry_state, ["search_slots"]

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
# No-slots retry handler — user wants to try different dates after empty search
# ---------------------------------------------------------------------------


def _handle_no_slots_retry(
    message: str,
    state: WorkflowState,
    db: Session,
    practice_id: str,
) -> ChatResponse:
    """
    Extract a new date/time preference from the user's reply and re-search.
    If no new date is found, widen the search window automatically.
    """
    from state_machine.extractors import extract_preferred_date, extract_time_of_day

    search_data = dict(state.collected_fields)
    new_date = extract_preferred_date(message)
    if new_date:
        search_data["preferred_date_from"] = new_date
    new_time = extract_time_of_day(message)
    if new_time:
        search_data["preferred_time_of_day"] = new_time

    preamble = ""
    if not new_date and not new_time:
        from datetime import date as _date, timedelta
        search_data["preferred_date_from"] = _date.today() + timedelta(days=1)
        search_data.pop("preferred_time_of_day", None)
        preamble = "Let me check what's available."

    reply, new_state, tools = _search_and_present_slots(
        search_data, state, db, preamble=preamble
    )
    return ChatResponse(reply=reply, state=new_state, tools_called=tools)


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

    is_reschedule = state.workflow == "reschedule_appointment"

    if is_reschedule:
        from schemas.tools import RescheduleAppointmentInput
        from tools.scheduling_tools import reschedule_appointment

        result = reschedule_appointment(
            db,
            RescheduleAppointmentInput(
                appointment_id=state.appointment_id,
                new_slot_id=slot_id,
            ),
        )
        success = result.success
        appointment = result.new_appointment
        error = result.error
        tool_used = "reschedule_appointment"
    else:
        result = book_appointment(
            db,
            BookAppointmentInput(
                patient_id=state.patient_id,
                slot_id=slot_id,
                appointment_type_code=appt_code,
                booked_via="chatbot",
            ),
        )
        success = result.success
        appointment = result.appointment
        error = result.error
        tool_used = "book_appointment"

    if not success or not appointment:
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

    a = appointment
    provider = f" with {a.provider_display_name}" if a.provider_display_name else ""
    if is_reschedule:
        confirm_reply = (
            f"Done! Your {a.appointment_type_display} has been rescheduled:\n\n"
            f"New Date: {a.date_label}\n"
            f"New Time: {a.time_label}{provider}\n"
            f"Location: {a.location_name}\n\n"
            "We'll see you then! Reply anytime if you need anything else. - Maya"
        )
    else:
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
        tools_called=[tool_used],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "hours": ["hour", "open", "close", "schedule", "when", "time", "saturday", "sunday", "weekend"],
    "location": ["where", "address", "located", "location", "parking", "direction", "find you"],
    "insurance": ["insurance", "coverage", "plan", "benefit", "covered", "accept", "sun life", "manulife"],
    "payment": ["payment", "pay", "no insurance", "uninsured", "self pay", "self-pay", "financing", "membership", "afford"],
    "new_patient": [
        "new patient",
        "register",
        "registration",
        "first visit",
        "first time",
        "sign up",
        "how do i register",
        "become a patient",
    ],
}


def _resolve_clinic_category_and_followup(
    message: str,
    state: WorkflowState,
) -> tuple[str | None, str | None]:
    """
    Infer FAQ category from the message, or treat short yes/no as follow-ups to
    ``state.last_clinic_category`` (e.g. after \"Would you like more details?\").
    Returns (category, followup) where followup is \"affirm\", \"negate\", or None.
    """
    from state_machine.extractors import extract_confirmation

    category = _infer_clinic_category(message)
    if category is not None:
        return category, None

    last = state.last_clinic_category
    if not last:
        return None, None

    conf = extract_confirmation(message)
    if conf is True:
        return last, "affirm"
    if conf is False:
        return last, "negate"
    return None, None


def _build_clinic_question_hint(
    message: str,
    category: str | None,
    followup: str | None,
) -> str:
    """Richer hint for FAQ ranking + receptionist when the user affirms/declines more detail."""
    if not followup or not category:
        return message
    if followup == "affirm":
        return (
            f"{message} [Context: patient agreed they want more detail on {category} "
            "(e.g. after being offered more details).]"
        )
    return (
        f"{message} [Context: patient declined more detail on {category}. "
        "Acknowledge and pivot; do not push.]"
    )


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


# ---------------------------------------------------------------------------
# Emergency notification dispatch + urgent slot search
# ---------------------------------------------------------------------------


def _dispatch_emergency_notification(
    tool_input_data: dict,
    state: WorkflowState,
    db: Session,
    practice_id: str,
) -> tuple[str, WorkflowState, list[str]]:
    """
    1. Create a StaffNotification (+ WorkQueueItem for escalations).
    2. Search for the earliest urgent / emergency slot in the next 2 days.
    3. If slots are available: present them so the patient can book immediately.
    4. If no urgent slots: confirm callback / manual-review and notify staff.
    """
    from schemas.tools import CreateStaffNotificationInput, SearchSlotsInput
    from tools.notification_tools import create_staff_notification
    from tools.scheduling_tools import search_slots
    from datetime import date as _date, timedelta

    first_name = tool_input_data.get("first_name", "")
    emergency_summary = (
        tool_input_data.get("emergency_summary")
        or "Patient requested urgent assistance via SMS chatbot."
    )

    # Build notification body
    name_part = f"Patient: {first_name} {tool_input_data.get('last_name', '')}".strip()
    phone_part = f"Phone: {tool_input_data.get('phone_number', 'not provided')}"
    body = f"{name_part}. {phone_part}. Summary: {emergency_summary}"

    notif_result = create_staff_notification(
        db,
        CreateStaffNotificationInput(
            notification_type="emergency",
            priority="urgent",
            title="Urgent patient — emergency SMS",
            body=body,
            patient_id=state.patient_id,
            practice_id=practice_id,
        ),
        practice_id=practice_id,
    )

    tools_called = ["create_staff_notification"]
    notif_ok = notif_result.success

    # Search for the earliest emergency/urgent slot in the next 48 hours
    today = _date.today()
    urgent_result = search_slots(
        db,
        SearchSlotsInput(
            appointment_type_code="emergency",
            date_from=today,
            date_to=today + timedelta(days=2),
            preferred_time_of_day="any",
        ),
    )

    if urgent_result.slots:
        tools_called.append("search_slots")
        options = urgent_result.slots[:3]
        slot_options = [{"id": s.id, "label": f"{s.date_label}, {s.time_label}"} for s in options]
        lines = "\n".join(f"{i + 1}. {s.date_label}, {s.time_label}" for i, s in enumerate(options))

        notif_line = (
            "I've already sent an alert to our team — they know you need urgent help."
            if notif_ok else
            "I'm flagging this for our team right now."
        )
        reply = (
            f"{notif_line}\n\n"
            "We have these urgent slots available:\n\n"
            f"{lines}\n\n"
            "Which one works for you? Reply with 1, 2, or 3. "
            "If none work, just say so and we'll have someone call you as soon as possible."
        )
        new_state = state.model_copy(
            update={
                "step": "selecting_slot",
                "slot_options": slot_options,
                # Keep emergency flag so book_appointment stores is_emergency=True
                "collected_fields": {
                    **state.collected_fields,
                    "_is_emergency": True,
                    "appointment_type": "emergency",
                },
            }
        )
        return reply, new_state, tools_called

    # No urgent slots — escalate to callback / manual review
    callback_notif = create_staff_notification(
        db,
        CreateStaffNotificationInput(
            notification_type="callback_request",
            priority="urgent",
            title="Emergency callback needed — no urgent slots available",
            body=body,
            patient_id=state.patient_id,
            practice_id=practice_id,
        ),
        practice_id=practice_id,
    )
    if callback_notif.success:
        tools_called.append("create_staff_notification:callback")

    reply = (
        "I've notified our team and they'll call you back as soon as possible — "
        "this has been flagged as urgent. Please don't wait if you're in severe pain; "
        "go to your nearest emergency dental clinic or call 911 if it's a medical emergency."
    )
    new_state = state.model_copy(update={"step": "confirmed"})
    return reply, new_state, tools_called


# ---------------------------------------------------------------------------
# Family booking dispatch
# ---------------------------------------------------------------------------


def _dispatch_family_booking(
    tool_input_data: dict,
    state: WorkflowState,
    db: Session,
    practice_id: str,
) -> tuple[str, WorkflowState, list[str]]:
    """
    Book one appointment per resolved family member, preferring consecutive slots
    per group_preference. Uses per-member appointment types from the structured
    family_members list. Unresolved patient IDs trigger staff notification.
    """
    from datetime import date as _date, timedelta

    from models.patient import Patient
    from schemas.appointment import FamilyBookingMemberIn
    from schemas.tools import BookFamilyAppointmentsInput, CreatePatientInput, CreateStaffNotificationInput, LookupPatientInput
    from tools.patient_tools import create_patient, lookup_patient
    from tools.scheduling_tools import (
        assign_family_appointment_slots,
        book_family_appointments,
        book_family_appointments_from_proposed_slots,
    )
    from tools.notification_tools import create_staff_notification
    from tools.validators import fmt_date, fmt_time_range, normalize_appointment_type
    from zoneinfo import ZoneInfo

    _TZ = ZoneInfo("America/Toronto")

    if not state.patient_id:
        return (
            "I need to verify your identity first before I can book for the whole family.",
            state,
            [],
        )

    raw_members = tool_input_data.get("family_members") or []
    gp = tool_input_data.get("group_preferences") or {}
    if not raw_members:
        return (
            "I’m missing the family member details — please start the family booking again.",
            state,
            [],
        )

    primary = db.get(Patient, state.patient_id)
    primary_phone = primary.phone_number if primary else ""

    preferred_time_global = gp.get("preferred_time_of_day") or tool_input_data.get("preferred_time_of_day") or "any"
    group_pref = gp.get("group_preference") or tool_input_data.get("group_preference") or "back_to_back"

    date_from = gp.get("preferred_date_from") or tool_input_data.get("preferred_date_from") or _date.today() + timedelta(days=1)
    if isinstance(date_from, str):
        try:
            date_from = _date.fromisoformat(date_from)
        except ValueError:
            date_from = _date.today() + timedelta(days=1)
    date_to = date_from + timedelta(days=14)

    # Resolve each member → patient_id (primary for self; lookup; create for new when possible)
    booking_members: list[FamilyBookingMemberIn] = []
    unresolved: list[str] = []

    for i, m in enumerate(raw_members):
        fn = (m.get("first_name") or "").strip()
        ln = (m.get("last_name") or "").strip()
        rel = (m.get("relation") or "").strip().lower()
        status = (m.get("patient_status") or "").strip().lower()
        display_name = f"{fn} {ln}".strip() or f"member_{i + 1}"

        try:
            appt_code = normalize_appointment_type(str(m.get("appointment_type") or "cleaning"))
        except ValueError:
            appt_code = "cleaning"

        tod = preferred_time_global
        pid: str | None = None

        if rel == "self" or rel in ("me", "myself", "i"):
            pid = state.patient_id
        else:
            lu = lookup_patient(
                db,
                LookupPatientInput(first_name=fn, last_name=ln, phone_number=primary_phone),
                practice_id=practice_id,
            )
            if lu.found and lu.patient:
                pid = lu.patient.id
            elif status == "new" and m.get("date_of_birth"):
                dob = m["date_of_birth"]
                if isinstance(dob, str):
                    try:
                        dob = _date.fromisoformat(dob)
                    except ValueError:
                        dob = None
                if dob is not None:
                    cp = create_patient(
                        db,
                        CreatePatientInput(
                            first_name=fn or "Family",
                            last_name=ln or "Member",
                            phone_number=primary_phone,
                            date_of_birth=dob,
                        ),
                        practice_id=practice_id,
                    )
                    if cp.success and cp.patient:
                        pid = cp.patient.id

        if pid is None:
            unresolved.append(display_name)
            continue

        booking_members.append(
            FamilyBookingMemberIn(
                patient_id=pid,
                appointment_type_code=appt_code,
                preferred_time_of_day=tod,
                display_name=display_name,
                relation=m.get("relation"),
                special_instructions=f"Family booking — {m.get('relation', '')}",
            )
        )

    if unresolved:
        body = (
            f"Family booking (primary patient_id={state.patient_id}) needs manual patient matching for: "
            f"{', '.join(unresolved)}. Raw request: {raw_members!r}. Group prefs: {gp!r}."
        )
        create_staff_notification(
            db,
            CreateStaffNotificationInput(
                notification_type="family_scheduling_complexity",
                priority="normal",
                title="Family booking — unresolved family members",
                body=body,
                patient_id=state.patient_id,
                practice_id=practice_id,
            ),
            practice_id=practice_id,
        )

    if len(booking_members) < 2:
        reply = (
            "I need at least two people with chart IDs I can book into before I can reserve slots together. "
            "I've sent your family details to our team — someone will call to finish setting everyone up."
        )
        new_state = state.model_copy(update={"step": "confirmed"})
        return reply, new_state, ["create_staff_notification"]

    payload = BookFamilyAppointmentsInput(
        members=booking_members,
        group_preference=group_pref,
        date_from=date_from,
        date_to=date_to,
        conversation_id=state.conversation_id,
    )

    proposed_ids = state.collected_fields.get("_family_proposed_slot_ids")

    # Second step: user already saw exact times and confirmed — book those slots.
    if proposed_ids and isinstance(proposed_ids, list) and len(proposed_ids) == len(booking_members):
        result = book_family_appointments_from_proposed_slots(db, payload, proposed_ids)
        tools_called = ["book_family_appointments"]
        new_cf = {k: v for k, v in state.collected_fields.items() if k != "_family_proposed_slot_ids"}

        if result.all_booked:
            appt_lines = "\n".join(
                f"{i + 1}. {a.patient_name} — {a.appointment_type_display} — {a.date_label}, {a.time_label}"
                for i, a in enumerate(result.appointments)
            )
            reply = (
                f"All set — here's one appointment per person:\n\n{appt_lines}\n\n"
                "You'll get a confirmation for each. See you all soon!"
            )
            new_state = state.model_copy(update={"step": "confirmed", "collected_fields": new_cf})
            return reply, new_state, tools_called

        booked_count = len(result.appointments)
        failed_count = len(result.partial_failures)
        create_staff_notification(
            db,
            CreateStaffNotificationInput(
                notification_type="family_scheduling_complexity",
                priority="normal",
                title="Family booking requires manual coordination",
                body=(
                    f"Proposal confirm failed: {booked_count} ok, {failed_count} failed. "
                    f"primary={state.patient_id}, prefs={gp!r}"
                ),
                patient_id=state.patient_id,
                practice_id=practice_id,
            ),
            practice_id=practice_id,
        )
        tools_called.append("create_staff_notification")

        if booked_count == 0:
            reply = (
                "Those times are no longer available. I've flagged our team — they'll call to coordinate."
            )
        else:
            booked_lines = "\n".join(
                f"{i + 1}. {a.patient_name} — {a.appointment_type_display} — {a.date_label}, {a.time_label}"
                for i, a in enumerate(result.appointments)
            )
            reply = (
                f"I booked {booked_count} appointment(s):\n\n{booked_lines}\n\n"
                f"I couldn't confirm the remaining slot(s) — they may have been taken. "
                "Our team will follow up."
            )

        new_state = state.model_copy(update={"step": "confirmed", "collected_fields": new_cf})
        return reply, new_state, tools_called

    # First step: find slots and show exact times — book only after a second yes.
    assigned, _ = assign_family_appointment_slots(db, payload)
    tools_called = ["propose_family_slots"]

    if len(assigned) == len(payload.members):
        slot_ids = [s.id for s, _, _ in assigned]
        proposal_lines = []
        for i, (slot, appt_type, member) in enumerate(assigned):
            starts = slot.starts_at.astimezone(_TZ)
            ends = slot.ends_at.astimezone(_TZ)
            label = member.display_name or "Patient"
            proposal_lines.append(
                f"{i + 1}. {label} — {appt_type.display_name} — {fmt_date(starts)}, {fmt_time_range(starts, ends)}"
            )
        lines_txt = "\n".join(proposal_lines)
        reply = (
            "Here are the exact times I can reserve for everyone:\n\n"
            f"{lines_txt}\n\n"
            "Let me know if you’d like me to book these — or tell me what you’d like to change "
            "(day, time of day, back-to-back vs same day, etc.)."
        )
        new_cf = {**state.collected_fields, "_family_proposed_slot_ids": slot_ids}
        new_state = state.model_copy(
            update={"step": "awaiting_family_slot_confirmation", "collected_fields": new_cf}
        )
        return reply, new_state, tools_called

    # Could not assign everyone — same messaging as before, without booking.
    create_staff_notification(
        db,
        CreateStaffNotificationInput(
            notification_type="family_scheduling_complexity",
            priority="normal",
            title="Family booking requires manual coordination",
            body=(
                f"No full assignment for family booking. primary={state.patient_id}, prefs={gp!r}"
            ),
            patient_id=state.patient_id,
            practice_id=practice_id,
        ),
        practice_id=practice_id,
    )
    tools_called.append("create_staff_notification")

    reply = (
        "I couldn't find grouped slots that work for everyone in that window. "
        "I've flagged our team — they'll call to coordinate times."
    )
    new_state = state.model_copy(update={"step": "confirmed"})
    return reply, new_state, tools_called
