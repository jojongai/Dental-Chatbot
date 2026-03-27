"""
Dedicated multi-step controller for FAMILY_BOOKING.

See module docstring in machine — collects headcount, per-member details, then group scheduling.
"""

from __future__ import annotations

from datetime import date
import re
from typing import Any

from schemas.chat import ActionType, ChatAction, Workflow
from state_machine.definitions import WORKFLOWS, WorkflowDef
from state_machine.machine import MachineResult


def run_family_booking_turn(
    machine: Any,
    message: str,
    wf_def: WorkflowDef,
    is_first_turn: bool,
    interp: Any,
) -> MachineResult | None:
    state = machine.state
    wf = WORKFLOWS[Workflow.FAMILY_BOOKING]

    # After we proposed concrete times — user must confirm before we book.
    if state.step == "awaiting_family_slot_confirmation":
        from state_machine.extractors import extract_confirmation

        # Interpreter first (LLM when USE_LLM) — handles open-ended agreement / pushback.
        confirmed = interp.extracted_fields.get("confirmation")
        if confirmed is None:
            confirmed = extract_confirmation(message)

        if confirmed is True:
            tool_data = {k: v for k, v in state.collected_fields.items() if not k.startswith("_")}
            return MachineResult(
                state=state.model_copy(update={"step": "ready"}),
                reply=wf.ready_message or "One moment…",
                ready_to_call=True,
                tool_name="book_family_appointments",
                tool_input_data=tool_data,
                actions=[],
                debug=machine._debug_snapshot(wf_def),
            )

        if confirmed is False:
            cf = dict(state.collected_fields)
            cf.pop("_family_proposed_slot_ids", None)
            return MachineResult(
                state=state.model_copy(
                    update={"step": "family:scheduling:preference", "collected_fields": cf}
                ),
                reply="No problem — let's adjust. Same question as before: would you like visits back-to-back, or is same day fine?",
                ready_to_call=False,
                actions=[],
                debug=machine._debug_snapshot(wf_def),
            )

        return MachineResult(
            state=state,
            reply=(
                "I wasn’t sure from that — do you want me to book the times I listed, "
                "or change something first?"
            ),
            ready_to_call=False,
            actions=[],
            debug=machine._debug_snapshot(wf_def),
        )

    if state.step in ("awaiting_confirmation", "ready"):
        return None

    cf = dict(state.collected_fields)
    step = state.step

    # ── 1) Headcount ───────────────────────────────────────────────────────
    if cf.get("family_count") is None:
        n = _parse_count(message)
        if n is None:
            n = _parse_count_from_interp(interp)
        if n is not None and 2 <= n <= 15:
            cf["family_count"] = n
            cf["family_members"] = []
            return _prompt_member_field(machine, wf_def, cf, 0, "name", wf)

        greeting = wf.greeting or "I can help book your family."
        reply = f"{greeting}\n\nOf course — how many people are we booking for?"
        return MachineResult(
            state=state.model_copy(update={"step": "family:count", "collected_fields": cf}),
            reply=reply,
            actions=[ChatAction(type=ActionType.REQUEST_INFO, payload={"field": "family_count"})],
            next_field="family_count",
            debug=machine._debug_snapshot(wf_def),
        )

    total = int(cf["family_count"])
    members = list(cf.get("family_members") or [])

    # ── 2) Scheduling phases (after all members filled) ────────────────────
    if step == "family:scheduling:preference":
        return _handle_scheduling_preference(machine, wf_def, message, interp, cf, wf)

    if step == "family:scheduling:date":
        return _handle_scheduling_date(machine, wf_def, message, interp, cf, wf)

    if step == "family:scheduling:time":
        return _handle_scheduling_time(machine, wf_def, message, cf, wf)

    # ── 3) Per-member fields ────────────────────────────────────────────────
    m = re.match(r"^family:member:(\d+):(name|relation|status|appointment|dob)$", step)
    if not m:
        # Recover: incomplete member list
        if len(members) < total:
            return _prompt_member_field(machine, wf_def, cf, len(members), "name", wf)
        if len(members) == total and _members_complete(members, total):
            return _start_scheduling(machine, wf_def, cf, wf)
        return None

    idx = int(m.group(1))
    sub = m.group(2)

    ok, err_reply, members = _apply_member_substep(message, idx, sub, members, total, interp)
    cf["family_members"] = members

    if not ok:
        return MachineResult(
            state=state.model_copy(update={"collected_fields": cf}),
            reply=err_reply or "Could you clarify that?",
            actions=[],
            debug=machine._debug_snapshot(wf_def),
        )

    # Advance
    row = members[idx]
    if sub == "name":
        return _prompt_member_field(machine, wf_def, cf, idx, "relation", wf)
    if sub == "relation":
        return _prompt_member_field(machine, wf_def, cf, idx, "status", wf)
    if sub == "status":
        return _prompt_member_field(machine, wf_def, cf, idx, "appointment", wf)
    if sub == "appointment":
        if row.get("patient_status") == "new" and not row.get("date_of_birth"):
            return _prompt_member_field(machine, wf_def, cf, idx, "dob", wf)
        if idx + 1 < total:
            return _prompt_member_field(machine, wf_def, cf, idx + 1, "name", wf)
        return _start_scheduling(machine, wf_def, cf, wf)
    if sub == "dob":
        if idx + 1 < total:
            return _prompt_member_field(machine, wf_def, cf, idx + 1, "name", wf)
        return _start_scheduling(machine, wf_def, cf, wf)

    return None


def _members_complete(members: list[dict[str, Any]], total: int) -> bool:
    if len(members) != total:
        return False
    for m in members:
        if not all(k in m for k in ("first_name", "last_name", "relation", "patient_status", "appointment_type")):
            return False
        if m.get("patient_status") == "new" and not m.get("date_of_birth"):
            return False
    return True


def _parse_count(message: str) -> int | None:
    from state_machine.extractors import extract_family_count

    return extract_family_count(message)


def _parse_count_from_interp(interp: Any) -> int | None:
    if not interp or not getattr(interp, "extracted_fields", None):
        return None
    v = interp.extracted_fields.get("family_count")
    if v is None:
        return None
    try:
        n = int(v)
        return n if 2 <= n <= 15 else None
    except (TypeError, ValueError):
        return None


def _prompt_member_field(
    machine: Any,
    wf_def: WorkflowDef,
    cf: dict[str, Any],
    member_index: int,
    substep: str,
    wf: Any,
) -> MachineResult:
    total = int(cf["family_count"])
    members = list(cf.get("family_members") or [])
    while len(members) <= member_index:
        members.append({})
    label = f"Family member {member_index + 1} of {total}"

    if substep == "name":
        q = f"Let’s start with {label}. What’s their full name?"
        st = f"family:member:{member_index}:name"
    elif substep == "relation":
        q = f"{label}: what’s their relation to you? (e.g. self, spouse, child)"
        st = f"family:member:{member_index}:relation"
    elif substep == "status":
        q = f"{label}: are they a new or an existing patient with us?"
        st = f"family:member:{member_index}:status"
    elif substep == "appointment":
        q = f"{label}: what kind of appointment do they need?"
        st = f"family:member:{member_index}:appointment"
    elif substep == "dob":
        q = f"{label}: what’s their date of birth? (needed for a new patient chart)"
        st = f"family:member:{member_index}:dob"
    else:
        q = "Please continue."
        st = "collecting"

    return MachineResult(
        state=machine.state.model_copy(
            update={"step": st, "collected_fields": {**cf, "family_members": members}}
        ),
        reply=q,
        actions=[
            ChatAction(
                type=ActionType.REQUEST_INFO,
                payload={"member_index": member_index, "substep": substep},
            )
        ],
        next_field=f"family_member_{member_index}_{substep}",
        debug=machine._debug_snapshot(wf_def),
    )


def _start_scheduling(machine: Any, wf_def: WorkflowDef, cf: dict[str, Any], wf: Any) -> MachineResult:
    return MachineResult(
        state=machine.state.model_copy(
            update={
                "step": "family:scheduling:preference",
                "collected_fields": cf,
            }
        ),
        reply=(
            "Great — a few questions about scheduling.\n\n"
            "Do you prefer back-to-back appointments, the same day, the same provider, "
            "or are you flexible?"
        ),
        actions=[ChatAction(type=ActionType.REQUEST_INFO, payload={"field": "group_preference"})],
        next_field="group_preference",
        debug=machine._debug_snapshot(wf_def),
    )


def _handle_scheduling_preference(
    machine: Any, wf_def: WorkflowDef, message: str, interp: Any, cf: dict[str, Any], wf: Any
) -> MachineResult:
    from state_machine.extractors import extract_group_preference

    pref = extract_group_preference(message)
    if pref is None and interp and getattr(interp, "extracted_fields", None):
        pref = interp.extracted_fields.get("group_preference")
    if pref is None:
        return MachineResult(
            state=machine.state,
            reply=(
                "Do you prefer back-to-back appointments, the same day, the same provider, "
                "or are you flexible?"
            ),
            actions=[],
            debug=machine._debug_snapshot(wf_def),
        )
    gp = dict(cf.get("group_preferences") or {})
    gp["group_preference"] = pref
    cf["group_preferences"] = gp
    return MachineResult(
        state=machine.state.model_copy(
            update={"step": "family:scheduling:date", "collected_fields": cf}
        ),
        reply="What date or rough timeframe works best (e.g. next week, March 15)?",
        actions=[ChatAction(type=ActionType.REQUEST_INFO, payload={"field": "preferred_date_from"})],
        next_field="preferred_date_from",
        debug=machine._debug_snapshot(wf_def),
    )


def _handle_scheduling_date(
    machine: Any, wf_def: WorkflowDef, message: str, interp: Any, cf: dict[str, Any], wf: Any
) -> MachineResult:
    from state_machine.extractors import extract_preferred_date

    d = extract_preferred_date(message)
    if d is None and interp and getattr(interp, "extracted_fields", None):
        pdf = interp.extracted_fields.get("preferred_date_from")
        if isinstance(pdf, date):
            d = pdf
        elif isinstance(pdf, str):
            d = extract_preferred_date(pdf)
    if d is None:
        return MachineResult(
            state=machine.state,
            reply="I couldn’t read that date — try next Tuesday, March 20, or April 5.",
            actions=[],
            debug=machine._debug_snapshot(wf_def),
        )
    gp = dict(cf.get("group_preferences") or {})
    gp["preferred_date_from"] = d
    cf["group_preferences"] = gp
    return MachineResult(
        state=machine.state.model_copy(
            update={"step": "family:scheduling:time", "collected_fields": cf}
        ),
        reply="Any preference for time of day — morning, afternoon, evening, or no preference?",
        actions=[ChatAction(type=ActionType.REQUEST_INFO, payload={"field": "preferred_time_of_day"})],
        next_field="preferred_time_of_day",
        debug=machine._debug_snapshot(wf_def),
    )


def _handle_scheduling_time(
    machine: Any, wf_def: WorkflowDef, message: str, cf: dict[str, Any], wf: Any
) -> MachineResult:
    from state_machine.extractors import extract_time_of_day

    tod = extract_time_of_day(message) or "any"
    low = message.strip().lower()
    if low in ("any", "no preference", "either", "doesn't matter", "dont care", "don't care", "flexible"):
        tod = "any"
    gp = dict(cf.get("group_preferences") or {})
    gp["preferred_time_of_day"] = tod
    cf["group_preferences"] = gp
    cf["_family_booking_complete"] = True
    summary = machine._build_family_booking_summary()
    reply = f"{wf.ready_message}\n\n{summary}\n\nDoes everything look correct?"
    return MachineResult(
        state=machine.state.model_copy(
            update={"step": "awaiting_confirmation", "collected_fields": {**cf, "group_preferences": gp}}
        ),
        reply=reply,
        actions=[ChatAction(type=ActionType.CONFIRM_BOOKING, payload={"summary": summary})],
        next_field="confirmation",
        debug=machine._debug_snapshot(wf_def),
    )


def _apply_member_substep(
    message: str,
    idx: int,
    sub: str,
    members: list[dict[str, Any]],
    total: int,
    interp: Any,
) -> tuple[bool, str | None, list[dict[str, Any]]]:
    from state_machine.extractors import (
        extract_appointment_type,
        extract_dob_lenient,
        extract_full_name,
        extract_relation_to_contact,
        parse_family_member_patient_status,
    )

    members = [dict(m) for m in members]
    while len(members) <= idx:
        members.append({})
    row = dict(members[idx])

    if sub == "name":
        name = extract_full_name(message)
        if name is None:
            return False, "I need a first and last name (e.g. Jordan Lee).", members
        row["first_name"] = name["first_name"]
        row["last_name"] = name["last_name"]
        members[idx] = row
        return True, None, members

    if sub == "relation":
        rel = extract_relation_to_contact(message)
        if rel is None:
            return False, "What’s their relation to you in a few words?", members
        row["relation"] = rel
        members[idx] = row
        return True, None, members

    if sub == "status":
        st = parse_family_member_patient_status(message)
        if st is None:
            return False, "Are they a new patient or an existing patient here?", members
        row["patient_status"] = st
        members[idx] = row
        return True, None, members

    if sub == "appointment":
        at = extract_appointment_type(message)
        if at is None and interp and getattr(interp, "extracted_fields", None):
            at = interp.extracted_fields.get("appointment_type")
        if at is None:
            return False, "What type of visit — cleaning, check-up, exam, or something else?", members
        row["appointment_type"] = at
        members[idx] = row
        return True, None, members

    if sub == "dob":
        d = extract_dob_lenient(message)
        if d is None:
            return False, "Please share their date of birth (e.g. May 3, 2014).", members
        row["date_of_birth"] = d
        members[idx] = row
        return True, None, members

    return False, None, members


def family_booking_summary_markdown(cf: dict[str, Any]) -> str:
    lines: list[str] = []
    members = cf.get("family_members") or []
    gp = cf.get("group_preferences") or {}
    for i, m in enumerate(members):
        name = f"{m.get('first_name', '')} {m.get('last_name', '')}".strip()
        lines.append(f"**Member {i + 1}** — {name}")
        lines.append(f"  • Relation: {m.get('relation', '')}")
        lines.append(f"  • Patient status: {m.get('patient_status', '')}")
        lines.append(f"  • Visit type: {m.get('appointment_type', '')}")
        dob = m.get("date_of_birth")
        if isinstance(dob, date):
            lines.append(f"  • DOB: {dob.isoformat()}")
        lines.append("")
    lines.append("**Scheduling**")
    lines.append(f"  • Group preference: {gp.get('group_preference', '')}")
    pd = gp.get("preferred_date_from")
    if isinstance(pd, date):
        lines.append(f"  • Preferred date: {pd.isoformat()}")
    else:
        lines.append(f"  • Preferred date: {pd}")
    lines.append(f"  • Time of day: {gp.get('preferred_time_of_day', 'any')}")
    return "\n".join(lines).strip()
