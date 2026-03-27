"""
Field extractors — pure functions, no DB or LLM dependencies.

Each extractor receives a raw user message string and returns either:
  - None          → could not extract the value
  - A scalar      → single extracted value
  - A dict        → multiple fields extracted in one pass (e.g. full_name → first+last)

Taxonomy
--------
Deterministic extractors (referenced from definitions.FIELDS, always run):
  extract_full_name, extract_last_name, extract_phone, extract_email,
  extract_dob, extract_confirmation

Semantic fallback extractors (used ONLY by the interpreter's keyword/regex
fallback path when USE_LLM=false or the API is unavailable):
  extract_insurance, extract_appointment_type, extract_preferred_date,
  extract_time_of_day, extract_emergency_summary, extract_cancel_reason,
  extract_group_preference, extract_family_count

Semantic extractors are NOT referenced from definitions.FIELDS — the LLM
interpreter handles these fields in production. They exist here so that
the USE_LLM=false code path (tests, local dev without an API key) can
produce the same InterpreterOutput shape without hitting the API.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Name
# ---------------------------------------------------------------------------

_NAME_LEAD_PATTERNS = [
    r"(?:my name is|i'm|i am|this is|it's|it is|name's|name is)\s+([A-Za-z][a-zA-Z\-']+(?:\s+[A-Za-z][a-zA-Z\-']+)+)",
    # "i go by" is a deliberate name introduction; "patient" / "calling" removed —
    # they matched intent phrases like "new patient looking to book"
    r"(?:i go by)\s+([A-Za-z][a-zA-Z\-']+(?:\s+[A-Za-z][a-zA-Z\-']+)+)",
]


def extract_full_name(text: str) -> dict[str, str] | None:
    """
    Returns {'first_name': ..., 'last_name': ...} if a name is found, else None.
    Handles formats:
      - "My name is Alice Thompson"
      - "I'm John-Paul Smith"
      - "Alice Thompson" (standalone two-word capitalised input)
    """
    for pattern in _NAME_LEAD_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            parts = m.group(1).strip().split()
            if len(parts) >= 2:
                return {
                    "first_name": _title(parts[0]),
                    "last_name": _title(" ".join(parts[1:])),
                }

    # Fallback: message is entirely a name-like string (≤4 words, all title-case-ish)
    words = text.strip().split()
    if 2 <= len(words) <= 4 and all(re.match(r"^[A-Za-z\-']{2,}$", w) for w in words):
        return {
            "first_name": _title(words[0]),
            "last_name": _title(" ".join(words[1:])),
        }
    return None


def extract_last_name(text: str) -> str | None:
    """
    Extract just a last name.
    Handles:
      - "My last name is Thompson"
      - "last name: Thompson"
      - full-name patterns (returns the last portion)
      - bare single-word input like "Thompson"
    """
    # "my last name is X" / "last name is X" / "surname is X"
    m = re.search(
        r"(?:last\s+name|surname|family\s+name)\s+(?:is|:)?\s*([A-Za-z\-']{2,30})",
        text,
        re.IGNORECASE,
    )
    if m:
        return _title(m.group(1))

    result = extract_full_name(text)
    if result:
        return result.get("last_name")

    # Single word that looks like a name
    m = re.match(r"^\s*([A-Za-z\-']{2,30})\s*$", text)
    if m:
        return _title(m.group(1))
    return None


def _title(s: str) -> str:
    return " ".join(w.capitalize() for w in s.split())


# ---------------------------------------------------------------------------
# Phone number
# ---------------------------------------------------------------------------

_PHONE_RE = re.compile(r"(\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4})")


def extract_phone(text: str) -> str | None:
    m = _PHONE_RE.search(text)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Email address
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def extract_email(text: str) -> str | None:
    m = _EMAIL_RE.search(text)
    return m.group(0).lower() if m else None


# ---------------------------------------------------------------------------
# Date of birth
# ---------------------------------------------------------------------------

_MONTHS: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def extract_dob(text: str) -> date | None:
    """
    Handles:
      YYYY-MM-DD, YYYY/MM/DD
      MM/DD/YYYY, MM-DD-YYYY
      "March 14, 1985", "14 March 1985", "born March 14 1985"
    """
    # YYYY-[M]M-[D]D
    m = re.search(r"\b(19\d{2}|20[012]\d)[/\-](\d{1,2})[/\-](\d{1,2})\b", text)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # [M]M/[D]D/YYYY or [M]M-[D]D-YYYY
    m = re.search(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](19\d{2}|20[012]\d)\b", text)
    if m:
        return _safe_date(int(m.group(3)), int(m.group(1)), int(m.group(2)))

    # "March 14, 1985" or "born on March 14, 1985"
    m = re.search(r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(19\d{2}|20[012]\d)\b", text, re.IGNORECASE)
    if m and m.group(1).lower() in _MONTHS:
        return _safe_date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))

    # "14 March 1985"
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(19\d{2}|20[012]\d)\b", text, re.IGNORECASE)
    if m and m.group(2).lower() in _MONTHS:
        return _safe_date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))

    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Booking patient-type gate — "new or existing patient?"
# ---------------------------------------------------------------------------


def parse_booking_patient_type(text: str) -> str | None:
    """
    Classify user reply as 'new' or 'existing' when asked
    "Are you a new or existing patient?"

    Returns 'new', 'existing', or None (unclear).
    """
    lower = text.strip().lower()
    _new = [
        "new", "first time", "first visit", "never been", "never visited",
        "haven't been", "havent been", "register", "sign up", "not yet",
        "never before",
    ]
    _existing = [
        "existing", "returning", "been before", "been here before",
        "current patient", "already a patient", "come here",
        "i've been", "ive been", "been there", "have been",
        "yes i am", "yes i'm", "yes im",
    ]
    for phrase in _existing:
        if phrase in lower:
            return "existing"
    for phrase in _new:
        if phrase in lower:
            return "new"
    return None


# ===========================================================================
# SEMANTIC FALLBACK EXTRACTORS
#
# These are used ONLY by llm/interpreter.py's _keyword_interpret() path
# (when USE_LLM=false or the Gemini API is unavailable).
# They are NOT referenced from state_machine/definitions.py.
# In production, the LLM interpreter handles these fields directly.
# ===========================================================================

# ---------------------------------------------------------------------------
# Insurance
# ---------------------------------------------------------------------------

_NO_INSURANCE_RE = re.compile(
    r"\b(no insurance|self[\s\-]?pay|uninsured|don'?t have|do not have|none|no coverage|cash"
    r"|i don'?t|nope|nah|no$|not covered|no plan|without insurance|pay out of pocket)\b",
    re.IGNORECASE,
)

_KNOWN_CARRIERS: list[str] = [
    "sun life",
    "sunlife",
    "manulife",
    "green shield",
    "canada life",
    "great.west life",
    "medavie blue cross",
    "pacific blue cross",
    "desjardins",
    "rbc insurance",
    "rbc",
    "gms",
    "group medical services",
    "cdcp",
    "canadian dental care plan",
    "delta dental",
    "metlife",
    "cigna",
    "unitedhealthcare",
    "united healthcare",
    "guardian life",
    "guardian",
    "humana",
    "ameritas",
    "united concordia",
    "aetna",
    "aflac",
]


def extract_insurance(text: str) -> str | None:
    if _NO_INSURANCE_RE.search(text):
        return "self_pay"

    lower = text.lower()
    for carrier in _KNOWN_CARRIERS:
        if re.search(r"\b" + re.escape(carrier) + r"\b", lower):
            return carrier.replace(".", "-").title()

    # Generic "I have X insurance / X dental plan"
    m = re.search(
        r"(?:have|through|with|under|covered by)\s+([A-Za-z][a-zA-Z\s&]{2,40}?)"
        r"\s+(?:insurance|dental|plan|coverage|benefits)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip().title()

    return None


# ---------------------------------------------------------------------------
# Appointment type
# ---------------------------------------------------------------------------

_APT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "cleaning": ["cleaning", "clean", "polish", "hygiene", "scale"],
    "general_checkup": [
        "checkup",
        "check-up",
        "check up",
        "general",
        "exam",
        "examination",
        "routine",
        "regular visit",
    ],
    "emergency": [
        "emergency",
        "urgent",
        "severe pain",
        "broken tooth",
        "cracked",
        "abscess",
        "swollen",
        "bleeding",
        "knocked out",
        "toothache",
    ],
    "new_patient_exam": ["new patient", "first time", "first visit", "first appointment"],
}


def extract_appointment_type(text: str) -> str | None:
    lower = text.lower()
    for apt_type, keywords in _APT_TYPE_KEYWORDS.items():
        if any(k in lower for k in keywords):
            return apt_type
    return None


# ---------------------------------------------------------------------------
# Preferred date
# ---------------------------------------------------------------------------

_WEEKDAY_MAP: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def extract_preferred_date(text: str, today: date | None = None) -> date | None:
    """
    Handles relative expressions (tomorrow, next week, next Monday…)
    and explicit dates (April 5, 2026-04-05, etc.).
    """
    ref = today or date.today()
    lower = text.lower()

    if "today" in lower:
        return ref
    if "tomorrow" in lower:
        return ref + timedelta(days=1)
    if "next week" in lower:
        # Monday of next week
        days_until_next_mon = (7 - ref.weekday()) % 7 or 7
        return ref + timedelta(days=days_until_next_mon)
    if "this week" in lower:
        return ref
    # "first day of next month", "beginning of next month"
    if re.search(r"(first day|start|beginning)\s+of\s+next\s+month", lower):
        next_m = ref.month + 1 if ref.month < 12 else 1
        next_y = ref.year if ref.month < 12 else ref.year + 1
        return date(next_y, next_m, 1)
    # "end of next month", "last day of next month"
    if re.search(r"(end|last day)\s+of\s+next\s+month", lower):
        next_m = ref.month + 1 if ref.month < 12 else 1
        next_y = ref.year if ref.month < 12 else ref.year + 1
        after = next_m + 1 if next_m < 12 else 1
        after_y = next_y if next_m < 12 else next_y + 1
        return date(after_y, after, 1) - timedelta(days=1)
    # "first day of April", "beginning of May"
    m = re.search(r"(?:first day|start|beginning)\s+of\s+([A-Za-z]+)", lower)
    if m and m.group(1) in _MONTHS:
        month = _MONTHS[m.group(1)]
        candidate = date(ref.year, month, 1)
        return candidate if candidate >= ref else date(ref.year + 1, month, 1)
    # "end of April", "last day of March"
    m = re.search(r"(?:end|last day)\s+of\s+([A-Za-z]+)", lower)
    if m and m.group(1) in _MONTHS:
        month = _MONTHS[m.group(1)]
        next_m = month + 1 if month < 12 else 1
        next_y = ref.year if month < 12 else ref.year + 1
        candidate = date(next_y, next_m, 1) - timedelta(days=1)
        if candidate.month != month:
            candidate = date(ref.year, month, 1)
        return candidate if candidate >= ref else date(ref.year + 1, month, candidate.day)
    # "next month" (generic) → 1st of next month
    if "next month" in lower:
        next_m = ref.month + 1 if ref.month < 12 else 1
        next_y = ref.year if ref.month < 12 else ref.year + 1
        return date(next_y, next_m, 1)

    for day_name, day_num in _WEEKDAY_MAP.items():
        if re.search(r"\b" + day_name + r"\b", lower):
            days_ahead = (day_num - ref.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return ref + timedelta(days=days_ahead)

    # "March 27" / "April 5th" — month name + day without year → assume this/next year
    m = re.search(r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\b", lower)
    if m and m.group(1) in _MONTHS:
        month = _MONTHS[m.group(1)]
        day = int(m.group(2))
        candidate = _safe_date(ref.year, month, day)
        if candidate:
            return candidate if candidate >= ref else _safe_date(ref.year + 1, month, day) or candidate

    # "the 27th" / "on the 15th" — bare ordinal day → assume current month or next
    m = re.search(r"\b(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)\b", lower)
    if m:
        day = int(m.group(1))
        if 1 <= day <= 31:
            candidate = _safe_date(ref.year, ref.month, day)
            if candidate and candidate >= ref:
                return candidate
            next_m = ref.month + 1 if ref.month < 12 else 1
            next_y = ref.year if ref.month < 12 else ref.year + 1
            return _safe_date(next_y, next_m, day) or candidate

    # Explicit date with year (re-use DOB parser — same date formats)
    return extract_dob(text)


# ---------------------------------------------------------------------------
# Preferred time of day
# ---------------------------------------------------------------------------

_TOD_KEYWORDS: dict[str, list[str]] = {
    "morning": ["morning", r"\b(8|9|10|11)\s*(am|a\.m)"],
    "afternoon": ["afternoon", "noon", r"\b(12|1|2|3|4)\s*(pm|p\.m)"],
    "evening": ["evening", r"\b(5|6|7)\s*(pm|p\.m)", "after work", "after 5"],
    "after_school": ["after school", r"\b(3|4)\s*(pm|p\.m)", "after 3"],
}


def extract_time_of_day(text: str) -> str | None:
    lower = text.lower()
    for tod, patterns in _TOD_KEYWORDS.items():
        for pat in patterns:
            if re.search(pat, lower):
                return tod
    return None


# ---------------------------------------------------------------------------
# Emergency summary
# ---------------------------------------------------------------------------


def extract_emergency_summary(text: str) -> str | None:
    """Capture any substantive description of the dental emergency."""
    stripped = text.strip()
    # Reject very short non-descriptive inputs
    if len(stripped) < 10:
        return None
    # Reject generic affirmations / negations
    if re.match(r"^(yes|no|ok|okay|sure|correct|right|yep|nope)[\s.!]*$", stripped, re.IGNORECASE):
        return None
    return stripped


# ---------------------------------------------------------------------------
# Cancel reason
# ---------------------------------------------------------------------------


def extract_cancel_reason(text: str) -> str | None:
    stripped = text.strip()
    if len(stripped) < 3:
        return None
    if re.match(r"^(yes|no|ok|okay|sure)[\s.!]*$", stripped, re.IGNORECASE):
        return None
    return stripped


# ---------------------------------------------------------------------------
# Group preference (family booking)
# ---------------------------------------------------------------------------


def extract_group_preference(text: str) -> str | None:
    lower = text.lower()
    if any(k in lower for k in ("back to back", "back-to-back", "consecutive", "one after")):
        return "back_to_back"
    if any(k in lower for k in ("same day", "same morning", "same afternoon")):
        return "same_day"
    if any(k in lower for k in ("same provider", "same dentist", "same doctor", "same hygienist")):
        return "same_provider"
    if any(k in lower for k in ("any", "flexible", "doesn't matter", "best available")):
        return "best_available"
    return None


# ---------------------------------------------------------------------------
# Slot choice (1 / 2 / 3 / "first" / "second" / "the third one")
# ---------------------------------------------------------------------------


def extract_slot_choice(text: str) -> int | None:
    """
    Returns 1-based index of the chosen slot, or None if not found.
    Handles digits ("1", "2"), ordinal words ("first", "second", "third"),
    and phrases like "option 2" or "the second one".
    """
    import re

    lower = text.strip().lower()

    _ORDINALS = {
        "first": 1, "1st": 1, "one": 1,
        "second": 2, "2nd": 2, "two": 2,
        "third": 3, "3rd": 3, "three": 3,
        "fourth": 4, "4th": 4, "four": 4,
        "fifth": 5, "5th": 5, "five": 5,
    }

    # "option 2", "number 2", "slot 2"
    m = re.search(r"(?:option|number|slot|#)\s*([1-5])", lower)
    if m:
        return int(m.group(1))

    # bare digit 1-5 with word boundary
    m = re.search(r"\b([1-5])\b", lower)
    if m:
        return int(m.group(1))

    # ordinal words
    for word, idx in _ORDINALS.items():
        if re.search(rf"\b{re.escape(word)}\b", lower):
            return idx

    return None


# ---------------------------------------------------------------------------
# Confirmation (yes/no)
# ---------------------------------------------------------------------------


def extract_confirmation(text: str) -> bool | None:
    """
    Returns True for affirmative, False for negative, None if unclear.

    Handles both explicit yes/no and natural conversational phrases like:
      "yeah that should be fine", "works for me", "let's do it",
      "actually not that one", "maybe try a different time"
    """
    lower = text.strip().lower()

    _yes_patterns = [
        # Single-word / short affirmatives
        r"^(yes|yeah|yep|yup|yah|sure|correct|that'?s right|that'?s correct|confirm|confirmed"
        r"|ok|okay|k|go ahead|please do|sounds good|looks good|looks right|all good"
        r"|go for it|perfect|great|do it|book it|proceed|definitely|absolutely"
        r"|works for me|that works|that'?s fine|that'?s great|that'?s perfect"
        r"|let'?s do it|let'?s go|sounds right|that'?s correct)[\s.!,]*$",
        # Phrases that contain affirmative signals
        r"\b(yes|correct|confirmed|looks (good|right|correct)|all (looks )?good"
        r"|go ahead|sounds good|works for me|that works|fine with me"
        r"|that'?s fine|that'?s right|that'?s great|should be fine"
        r"|i (confirm|agree|approve)|please (proceed|book|confirm))\b",
    ]
    for pat in _yes_patterns:
        if re.search(pat, lower):
            return True

    _no_patterns = [
        # Single-word / short negatives
        r"^(no|nope|nah|cancel|stop|not right|wrong|wait|hold on|actually|change|incorrect"
        r"|not that|not quite|nah|neither)[\s.!?]*$",
        # Phrases indicating something is wrong
        r"\b(no,? (that'?s|it'?s) (wrong|incorrect|not right)"
        r"|please (change|fix|update|edit|redo)"
        r"|change something|change that|that'?s? (wrong|not right|incorrect)"
        r"|let me fix|is wrong|is incorrect"
        r"|actually not|not that one|not that time|different (time|date|day)"
        r"|maybe (try|a different)|try again|try a different"
        r"|wait,? (change|fix|update|no)|hold on,? (change|actually))\b",
    ]
    for pat in _no_patterns:
        if re.search(pat, lower):
            return False

    return None


# ---------------------------------------------------------------------------
# Number of family members
# ---------------------------------------------------------------------------


def extract_family_count(text: str) -> int | None:
    """Extract how many people need appointments in family booking."""
    lower = text.lower()
    word_nums = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "2": 2, "3": 3, "4": 4, "5": 5}
    for word, num in word_nums.items():
        if word in lower:
            return num
    m = re.search(r"\b(\d+)\s+(?:people|patients|members|kids|children|of us)", lower)
    if m:
        return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Master extraction table
# Each entry maps a field_key → extractor function.
# Extractors that produce multiple fields return a dict instead of a scalar.
# ---------------------------------------------------------------------------

FIELD_EXTRACTORS: dict[str, Any] = {
    # multi-key: extractor returns {'first_name': ..., 'last_name': ...}
    "full_name": extract_full_name,
    # individual name components (used when only last name was requested)
    "first_name": extract_full_name,  # returns dict; machine unpacks
    "last_name": extract_last_name,
    "phone_number": extract_phone,
    "date_of_birth": extract_dob,
    "insurance_name": extract_insurance,
    "appointment_type": extract_appointment_type,
    "preferred_date_from": extract_preferred_date,
    "preferred_time_of_day": extract_time_of_day,
    "emergency_summary": extract_emergency_summary,
    "cancel_reason": extract_cancel_reason,
    "group_preference": extract_group_preference,
    "confirmation": extract_confirmation,
    "family_count": extract_family_count,
    "slot_choice": extract_slot_choice,
}
