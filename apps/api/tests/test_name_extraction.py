"""Tests for name extractors (intent false positives, merge behavior)."""

from __future__ import annotations

from state_machine.extractors import (
    extract_full_name,
    is_false_positive_name_pair,
    merge_extracted_name_into_collected,
)
from tools.scheduling_tools import normalize_group_preference


def test_cancel_appointment_is_not_a_name() -> None:
    assert extract_full_name("cancel appointment") is None
    assert extract_full_name("new patient") is None


def test_next_week_is_not_a_name() -> None:
    assert extract_full_name("Next week") is None
    assert extract_full_name("this week") is None
    assert is_false_positive_name_pair("Next", "Week")


def test_the_following_friday_is_not_a_name() -> None:
    assert extract_full_name("The following Friday") is None
    assert extract_full_name("the following week") is None


def test_real_two_word_name_still_extracts() -> None:
    r = extract_full_name("Joseph Ngai")
    assert r == {"first_name": "Joseph", "last_name": "Ngai"}


def test_false_positive_pair_detection() -> None:
    assert is_false_positive_name_pair("Cancel", "Appointment")
    assert not is_false_positive_name_pair("Joseph", "Ngai")
    assert is_false_positive_name_pair("Scheduling", "Issue")
    assert is_false_positive_name_pair("Schedule", "Conflict")


def test_normalize_group_preference_back_to_back() -> None:
    assert normalize_group_preference("back to back") == "back_to_back"
    assert normalize_group_preference("same day") == "same_day"
    assert normalize_group_preference(None) == "back_to_back"


def test_name_should_be_correction() -> None:
    assert extract_full_name("Name should be Jojo Ngai") == {
        "first_name": "Jojo",
        "last_name": "Ngai",
    }
    assert extract_full_name("correct the name to Jane Smith") == {
        "first_name": "Jane",
        "last_name": "Smith",
    }


def test_merge_overwrites_bogus_pair() -> None:
    c = {"first_name": "Cancel", "last_name": "Appointment", "phone_number": "6475550100"}
    merge_extracted_name_into_collected(c, extract_full_name("Joseph Ngai"))
    assert c["first_name"] == "Joseph"
    assert c["last_name"] == "Ngai"
    assert c["phone_number"] == "6475550100"
