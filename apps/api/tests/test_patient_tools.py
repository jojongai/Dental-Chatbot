"""Tests for patient tool helpers (no DB required)."""

from tools.patient_tools import normalize_phone_digits


def test_normalize_phone_equivalent_formats() -> None:
    a = normalize_phone_digits("(416) 555-2001")
    b = normalize_phone_digits("+1 416-555-2001")
    c = normalize_phone_digits("14165552001")
    assert a == b == c == "4165552001"
