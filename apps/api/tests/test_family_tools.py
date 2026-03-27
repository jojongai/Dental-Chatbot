"""Tests for family_groups resolution and linking."""

from __future__ import annotations

import os
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from models.base import Base
from models.patient import FamilyGroup, FamilyGroupMember, Patient
from models.practice import Practice
from tools.family_tools import (
    ensure_patients_in_same_family_group,
    find_patient_in_family_group_by_name,
    get_family_group_for_primary,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    session = Session_()
    p = Practice(
        id="p1",
        name="bright_smile",
        display_name="Bright Smile Dental",
        timezone="America/Toronto",
    )
    session.add(p)
    session.flush()
    session.add(
        Patient(
            id="primary_id",
            practice_id=p.id,
            first_name="Jojo",
            last_name="Ngai",
            phone_number="6476385400",
            date_of_birth=date(1990, 1, 1),
            status="active",
        )
    )
    session.add(
        Patient(
            id="sibling_id",
            practice_id=p.id,
            first_name="Jeremy",
            last_name="Ngai",
            phone_number="6476385400",
            date_of_birth=date(2005, 1, 1),
            status="active",
        )
    )
    session.flush()
    fg = FamilyGroup(
        id="fg1",
        practice_id=p.id,
        name="Ngai household",
        primary_contact_patient_id="primary_id",
    )
    session.add(fg)
    session.flush()
    session.add(
        FamilyGroupMember(
            family_group_id=fg.id,
            patient_id="primary_id",
            member_role="primary",
        )
    )
    session.add(
        FamilyGroupMember(
            family_group_id=fg.id,
            patient_id="sibling_id",
            member_role="sibling",
        )
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


def test_get_family_group_for_primary(db: Session) -> None:
    fg = get_family_group_for_primary(db, "p1", "primary_id")
    assert fg is not None
    assert fg.id == "fg1"


def test_find_patient_in_family_group_by_name(db: Session) -> None:
    p = find_patient_in_family_group_by_name(db, "fg1", "Jeremy", "Ngai")
    assert p is not None
    assert p.id == "sibling_id"


def test_ensure_patients_in_same_family_group_idempotent(db: Session) -> None:
    ensure_patients_in_same_family_group(db, "p1", "primary_id", "sibling_id", member_role_hint="sibling")
    n = db.execute(FamilyGroupMember.__table__.select().where(FamilyGroupMember.patient_id == "sibling_id")).fetchall()
    assert len(n) == 1
