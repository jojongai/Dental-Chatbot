"""
Family group helpers — resolve household members via family_groups / family_group_members
before falling back to phone+name lookup, and keep charts linked after booking.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.patient import FamilyGroup, FamilyGroupMember, Patient


def get_family_group_for_primary(db: Session, practice_id: str, primary_patient_id: str) -> FamilyGroup | None:
    """Family group where this patient is primary contact, or any group they already belong to."""
    fg = db.execute(
        select(FamilyGroup).where(
            FamilyGroup.practice_id == practice_id,
            FamilyGroup.primary_contact_patient_id == primary_patient_id,
        )
    ).scalar_one_or_none()
    if fg:
        return fg
    fgm = db.execute(
        select(FamilyGroupMember).where(FamilyGroupMember.patient_id == primary_patient_id)
    ).scalars().first()
    if fgm:
        return db.get(FamilyGroup, fgm.family_group_id)
    return None


def find_patient_in_family_group_by_name(
    db: Session, family_group_id: str, first_name: str, last_name: str
) -> Patient | None:
    """Match a roster name to an existing chart already linked to this household."""
    fn = first_name.strip().lower()
    ln = last_name.strip().lower()
    if not fn or not ln:
        return None
    stmt = (
        select(Patient)
        .join(FamilyGroupMember, FamilyGroupMember.patient_id == Patient.id)
        .where(FamilyGroupMember.family_group_id == family_group_id)
        .where(func.lower(Patient.first_name) == fn)
        .where(func.lower(Patient.last_name) == ln)
    )
    return db.execute(stmt).scalar_one_or_none()


def ensure_patients_in_same_family_group(
    db: Session,
    practice_id: str,
    primary_patient_id: str,
    other_patient_id: str,
    *,
    member_role_hint: str | None = None,
) -> None:
    """
    Idempotently place primary and other in the same family_group (creates group if needed).
    Safe to call after resolving a non-self member by lookup or create.
    """
    if other_patient_id == primary_patient_id:
        return

    fg = get_family_group_for_primary(db, practice_id, primary_patient_id)
    if fg is None:
        fg = FamilyGroup(
            practice_id=practice_id,
            name="Household",
            primary_contact_patient_id=primary_patient_id,
        )
        db.add(fg)
        db.flush()
        db.add(
            FamilyGroupMember(
                family_group_id=fg.id,
                patient_id=primary_patient_id,
                member_role="primary",
            )
        )
        db.flush()

    def _has_member(patient_id: str) -> bool:
        return (
            db.execute(
                select(FamilyGroupMember.id).where(
                    FamilyGroupMember.family_group_id == fg.id,
                    FamilyGroupMember.patient_id == patient_id,
                )
            ).first()
            is not None
        )

    if not _has_member(other_patient_id):
        db.add(
            FamilyGroupMember(
                family_group_id=fg.id,
                patient_id=other_patient_id,
                member_role=(member_role_hint or "member")[:40],
            )
        )
    db.commit()
