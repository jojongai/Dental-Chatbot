"""
Field extractors — pure functions, no DB or LLM dependencies.

Each extractor receives a raw user message string and returns either:
  - None          → could not extract the value
  - A scalar      → single extracted value
  - A dict        → multiple fields extracted in one pass (e.g. full_name → first+last)

All extraction is intentionally lenient to handle natural conversational text.
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
    r"(?:patient|calling|i go by)\s+([A-Za-z][a-zA-Z\-']+(?:\s+[A-Za-z][a-zA-Z\-']+)+)",
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
# Insurance
# ---------------------------------------------------------------------------

_NO_INSURANCE_RE = re.compile(
    r"\b(no insurance|self[\s\-]?pay|uninsured|don'?t have|do not have|none|no coverage|cash)\b",
    re.IGNORECASE,
)

_KNOWN_CARRIERS: list[str] = [
    "sun life",
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
    if "next month" in lower:
        return ref + timedelta(days=30)

    for day_name, day_num in _WEEKDAY_MAP.items():
        if re.search(r"\b" + day_name + r"\b", lower):
            days_ahead = (day_num - ref.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return ref + timedelta(days=days_ahead)

    # Explicit date (re-use DOB parser — same date formats)
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
    """Returns True for affirmative, False for negative, None if unclear."""
    lower = text.strip().lower()
    _yes_re = r"^(yes|yeah|yep|yup|sure|correct|that'?s right|confirm|ok|okay|go ahead|please do|sounds good)[\s.!]*$"
    if re.match(_yes_re, lower):
        return True
    if re.match(r"^(no|nope|nah|cancel|stop|not right|wrong|wait|hold on|actually)[\s.!?]*$", lower):
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
