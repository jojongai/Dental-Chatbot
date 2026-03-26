"""
Patient tools — lookup_patient, create_patient.

These are called by the orchestration layer during:
  - existing_patient_verification workflow  → lookup_patient
  - new_patient_registration workflow       → create_patient
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from schemas.tools import (
    CreatePatientInput,
    CreatePatientOutput,
    LookupPatientInput,
    LookupPatientOutput,
)


def lookup_patient(db: Session, payload: LookupPatientInput) -> LookupPatientOutput:
    """
    Search for an existing patient.

    Lookup strategy (in order):
    1. Exact match on phone_number (normalised).
    2. Exact match on (last_name ILIKE + date_of_birth) — used during chat verification.
    3. If both are provided, require both to match (higher confidence).

    Returns match_confidence:
      1.0  — phone + name/DOB all matched
      0.8  — phone only matched
      0.7  — name + DOB matched, no phone provided
      0.0  — no match

    TODO: implement DB query against patients table.
    """
    raise NotImplementedError("lookup_patient not yet implemented")


def create_patient(
    db: Session,
    payload: CreatePatientInput,
    practice_id: str,
) -> CreatePatientOutput:
    """
    Create a new Patient row (status='lead') and optionally link an InsurancePlan
    if insurance_name matches a known plan in insurance_plans.

    Steps:
    1. Validate no duplicate exists (phone or email).
    2. Insert into patients.
    3. If insurance_name provided, fuzzy-match against insurance_plans.carrier_name
       and insert a patient_insurance_policies row with verification_status='unverified'.
    4. Return PatientOut.

    TODO: implement.
    """
    raise NotImplementedError("create_patient not yet implemented")
