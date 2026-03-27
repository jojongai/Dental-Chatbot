"""Unit tests for date-of-birth extraction (lenient path for SMS-style input)."""

from datetime import date

from state_machine.extractors import extract_dob, extract_dob_lenient


def test_extract_dob_standard_month_day_year():
    assert extract_dob("September 22, 2003") == date(2003, 9, 22)
    assert extract_dob("September 22 2003") == date(2003, 9, 22)


def test_extract_dob_sept_abbreviation():
    assert extract_dob("Sept 22 2003") == date(2003, 9, 22)


def test_extract_dob_year_not_only_2000_2029():
    assert extract_dob("March 3, 1995") == date(1995, 3, 3)


def test_extract_dob_lenient_glued_day_year():
    assert extract_dob_lenient("September 222004") == date(2004, 9, 22)


def test_extract_dob_lenient_falls_back_to_same_as_extract_dob_when_possible():
    assert extract_dob_lenient("Sept 22 2003") == date(2003, 9, 22)
