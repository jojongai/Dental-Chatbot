"""
Patient tools — lookup_patient, create_patient.

These are called by the orchestration layer during:
  - existing_patient_verification workflow  → lookup_patient
  - new_patient_registration workflow       → create_patient
  - session opening (caller_phone)          → lookup_patient (phone-only)
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.patient import Patient
from schemas.patient import PatientOut
from schemas.tools import (
    CreatePatientInput,
    CreatePatientOutput,
    LookupPatientInput,
    LookupPatientOutput,
)


def normalize_phone_digits(raw: str) -> str:
    """Strip to digits; normalize NANP numbers to last 10 digits."""
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


def _patient_to_out(p: Patient) -> PatientOut:
    return PatientOut(
        id=p.id,
        first_name=p.first_name,
        last_name=p.last_name,
        preferred_name=p.preferred_name,
        phone_number=p.phone_number,
        date_of_birth=p.date_of_birth,
        is_existing_patient=p.is_existing_patient,
        status=p.status,
        primary_insurance=None,
    )


def lookup_patient(db: Session, payload: LookupPatientInput, practice_id: str = "") -> LookupPatientOutput:
    """
    Search for an existing patient.

    Lookup strategy:
    1. Phone: normalized digit match (last 10 for NANP).
    2. last_name (case-insensitive) + date_of_birth when phone not used or for confidence boost.

    Returns match_confidence 0.8 for phone-only, 1.0 when phone + name/DOB agree, 0.7 for name+DOB only.
    """
    stmt = select(Patient)
    if practice_id:
        stmt = stmt.where(Patient.practice_id == practice_id)
    patients = list(db.execute(stmt).scalars().all())

    if payload.phone_number:
        target = normalize_phone_digits(payload.phone_number)
        if not target:
            return LookupPatientOutput(found=False, match_confidence=0.0)

        matches = [p for p in patients if normalize_phone_digits(p.phone_number) == target]
        if len(matches) > 1:
            return LookupPatientOutput(
                found=False,
                patient=None,
                match_confidence=0.0,
                multiple_matches=True,
            )
        if len(matches) == 1:
            p = matches[0]
            conf = 0.8
            if payload.last_name and payload.date_of_birth:
                if (
                    payload.last_name.strip().lower() == p.last_name.strip().lower()
                    and payload.date_of_birth == p.date_of_birth
                ):
                    conf = 1.0
            return LookupPatientOutput(found=True, patient=_patient_to_out(p), match_confidence=conf)

    if payload.last_name and payload.date_of_birth:
        ln = payload.last_name.strip().lower()
        matches = [
            p
            for p in patients
            if p.last_name.strip().lower() == ln and p.date_of_birth == payload.date_of_birth
        ]
        if len(matches) > 1:
            return LookupPatientOutput(
                found=False,
                patient=None,
                match_confidence=0.0,
                multiple_matches=True,
            )
        if len(matches) == 1:
            return LookupPatientOutput(
                found=True,
                patient=_patient_to_out(matches[0]),
                match_confidence=0.7,
            )

    return LookupPatientOutput(found=False, match_confidence=0.0)


def create_patient(
    db: Session,
    payload: CreatePatientInput,
    practice_id: str,
) -> CreatePatientOutput:
    """
    Create a new Patient row (status='lead') and optionally link an InsurancePlan
    if insurance_name matches a known plan in insurance_plans.

    TODO: implement.
    """
    raise NotImplementedError("create_patient not yet implemented")
