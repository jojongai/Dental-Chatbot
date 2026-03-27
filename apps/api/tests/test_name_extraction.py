"""Tests for name extractors (intent false positives, merge behavior)."""

from __future__ import annotations

from state_machine.extractors import (
    extract_full_name,
    is_false_positive_name_pair,
    merge_extracted_name_into_collected,
)


def test_cancel_appointment_is_not_a_name() -> None:
    assert extract_full_name("cancel appointment") is None
    assert extract_full_name("new patient") is None


def test_real_two_word_name_still_extracts() -> None:
    r = extract_full_name("Joseph Ngai")
    assert r == {"first_name": "Joseph", "last_name": "Ngai"}


def test_false_positive_pair_detection() -> None:
    assert is_false_positive_name_pair("Cancel", "Appointment")
    assert not is_false_positive_name_pair("Joseph", "Ngai")


def test_merge_overwrites_bogus_pair() -> None:
    c = {"first_name": "Cancel", "last_name": "Appointment", "phone_number": "6475550100"}
    merge_extracted_name_into_collected(c, extract_full_name("Joseph Ngai"))
    assert c["first_name"] == "Joseph"
    assert c["last_name"] == "Ngai"
    assert c["phone_number"] == "6475550100"
