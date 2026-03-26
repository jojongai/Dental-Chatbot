"""
Input validation helpers used by patient and scheduling tools.

All functions return the normalized value on success, or raise ValueError
with a patient-readable message on failure.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal


# ---------------------------------------------------------------------------
# Phone
# ---------------------------------------------------------------------------

_PHONE_DIGITS_RE = re.compile(r"\d")

# Maps chatbot appointment_type keywords to canonical DB codes
_APPT_TYPE_ALIASES: dict[str, str] = {
    # cleaning variants
    "cleaning": "cleaning",
    "clean": "cleaning",
    "teeth cleaning": "cleaning",
    "deep clean": "cleaning",
    "deep cleaning": "cleaning",
    "polish": "cleaning",
    "hygiene": "cleaning",
    "hygienist": "cleaning",
    # general checkup variants
    "checkup": "general_checkup",
    "check-up": "general_checkup",
    "check up": "general_checkup",
    "general checkup": "general_checkup",
    "general check-up": "general_checkup",
    "exam": "general_checkup",
    "routine exam": "general_checkup",
    "regular": "general_checkup",
    "routine": "general_checkup",
    # new patient exam
    "new patient": "new_patient_exam",
    "new patient exam": "new_patient_exam",
    "first visit": "new_patient_exam",
    "initial exam": "new_patient_exam",
    "initial": "new_patient_exam",
    # emergency
    "emergency": "emergency",
    "urgent": "emergency",
    "pain": "emergency",
    "toothache": "emergency",
    "broken tooth": "emergency",
    "broken": "emergency",
}

AppointmentTypeCode = Literal["cleaning", "general_checkup", "emergency", "new_patient_exam"]


def normalize_phone(raw: str) -> str:
    """
    Normalize a phone number to 10-digit NANP string (e.g. '4165550100').
    Raises ValueError if the result is not 10 digits.
    """
    digits = "".join(_PHONE_DIGITS_RE.findall(raw))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError(
            f"Phone number should be 10 digits — I got '{raw}'. "
            "Could you re-enter it in the format (416) 555-1234?"
        )
    return digits


def normalize_appointment_type(raw: str) -> AppointmentTypeCode:
    """
    Map a free-text appointment description to a canonical code.
    Raises ValueError with a helpful message if no match found.
    """
    key = raw.strip().lower()
    if key in _APPT_TYPE_ALIASES:
        return _APPT_TYPE_ALIASES[key]  # type: ignore[return-value]
    # Try partial/substring match
    for alias, code in _APPT_TYPE_ALIASES.items():
        if alias in key or key in alias:
            return code  # type: ignore[return-value]
    raise ValueError(
        f"I didn't recognize '{raw}' as an appointment type. "
        "Could you clarify — cleaning, check-up, new patient exam, or emergency?"
    )


def validate_dob(dob: date) -> date:
    """
    Validate that date_of_birth is in the past and realistic.
    Raises ValueError on bad input.
    """
    today = date.today()
    if dob >= today:
        raise ValueError("Date of birth must be in the past.")
    age = (today - dob).days / 365.25
    if age > 130:
        raise ValueError(
            f"Date of birth {dob} would make the patient {age:.0f} years old — "
            "please double-check."
        )
    return dob


def fmt_date(dt: datetime) -> str:
    """'Tuesday, April 8' — used in slot/appointment labels."""
    return dt.strftime("%A, %B %-d")


def fmt_time(dt: datetime) -> str:
    """'10:00 AM' — used in slot/appointment labels."""
    return dt.strftime("%-I:%M %p")


def fmt_time_range(start: datetime, end: datetime) -> str:
    """'10:00 AM - 11:00 AM'"""
    return f"{fmt_time(start)} - {fmt_time(end)}"
