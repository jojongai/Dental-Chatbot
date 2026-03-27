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

from models.patient import InsurancePlan, Patient, PatientInsurancePolicy
from schemas.patient import PatientOut
from schemas.tools import (
    CreatePatientInput,
    CreatePatientOutput,
    LookupPatientInput,
    LookupPatientOutput,
)
from tools.validators import normalize_phone, validate_dob


def normalize_phone_digits(raw: str) -> str:
    """Strip to digits; normalize NANP to last 10 digits (no validation)."""
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


def _patient_to_out(p: Patient, primary_insurance: str | None = None) -> PatientOut:
    return PatientOut(
        id=p.id,
        first_name=p.first_name,
        last_name=p.last_name,
        preferred_name=p.preferred_name,
        phone_number=p.phone_number,
        date_of_birth=p.date_of_birth,
        is_existing_patient=p.is_existing_patient,
        status=p.status,
        primary_insurance=primary_insurance,
    )


def lookup_patient(db: Session, payload: LookupPatientInput, practice_id: str = "") -> LookupPatientOutput:
    """
    Search for an existing patient.

    Lookup strategy (in order of specificity):
    1. phone + first_name + last_name  → confidence 1.0  (primary key; should be unique)
       If still multiple (data-quality edge case): email tiebreaker → 1.0, else multiple_matches.
    2. phone only (e.g. caller ID pre-fill, name not yet given) → confidence 0.8
    3. first_name + last_name only (no phone)                   → confidence 0.7
       If multiple on names only: email tiebreaker → 1.0, else multiple_matches.
    """
    stmt = select(Patient)
    if practice_id:
        stmt = stmt.where(Patient.practice_id == practice_id)
    patients = list(db.execute(stmt).scalars().all())

    phone_norm = normalize_phone_digits(payload.phone_number) if payload.phone_number else ""
    fn = payload.first_name.strip().lower() if payload.first_name else ""
    ln = payload.last_name.strip().lower() if payload.last_name else ""

    # ── Strategy 1: phone + first_name + last_name ───────────────────────────
    if phone_norm and fn and ln:
        matches = [
            p for p in patients
            if normalize_phone_digits(p.phone_number) == phone_norm
            and p.first_name.strip().lower() == fn
            and p.last_name.strip().lower() == ln
        ]
        if len(matches) == 1:
            return LookupPatientOutput(found=True, patient=_patient_to_out(matches[0]), match_confidence=1.0)
        if len(matches) > 1:
            return _disambiguate_by_email(matches, payload.email)

    # ── Strategy 2: phone only ───────────────────────────────────────────────
    if phone_norm:
        matches = [p for p in patients if normalize_phone_digits(p.phone_number) == phone_norm]
        if len(matches) == 1:
            p = matches[0]
            # Phone-only / caller-ID: one chart on this number — attribute it.
            if not fn or not ln:
                return LookupPatientOutput(found=True, patient=_patient_to_out(p), match_confidence=0.8)
            # Name was given but Strategy 1 found no phone+name row. If the only chart on this
            # number is someone else, do not return them — try Strategy 3 (name-only) for a
            # family member whose chart uses a different phone.
            # (If fn/ln matched this record, Strategy 1 would already have returned.)
        elif len(matches) > 1:
            # Try to narrow with name if available
            if fn and ln:
                narrowed = [p for p in matches if p.first_name.strip().lower() == fn and p.last_name.strip().lower() == ln]
                if len(narrowed) == 1:
                    return LookupPatientOutput(found=True, patient=_patient_to_out(narrowed[0]), match_confidence=1.0)
            return _disambiguate_by_email(matches, payload.email)

    # ── Strategy 3: first_name + last_name only ──────────────────────────────
    if fn and ln:
        matches = [
            p for p in patients
            if p.first_name.strip().lower() == fn and p.last_name.strip().lower() == ln
        ]
        if len(matches) == 1:
            return LookupPatientOutput(found=True, patient=_patient_to_out(matches[0]), match_confidence=0.7)
        if len(matches) > 1:
            return _disambiguate_by_email(matches, payload.email)

    return LookupPatientOutput(found=False, match_confidence=0.0)


def _disambiguate_by_email(matches: list[Patient], email: str | None) -> LookupPatientOutput:
    """Try email as a tiebreaker; return multiple_matches if still ambiguous."""
    if email:
        needle = email.strip().lower()
        narrowed = [p for p in matches if p.email and p.email.strip().lower() == needle]
        if len(narrowed) == 1:
            return LookupPatientOutput(found=True, patient=_patient_to_out(narrowed[0]), match_confidence=1.0)
    return LookupPatientOutput(found=False, patient=None, match_confidence=0.0, multiple_matches=True)


def create_patient(
    db: Session,
    payload: CreatePatientInput,
    practice_id: str,
    *,
    allow_shared_household_phone: bool = False,
) -> CreatePatientOutput:
    """
    Create a new Patient row (status='lead') and optionally link an InsurancePlan
    if insurance_name matches a known carrier in the DB.

    Validates:
    - No duplicate by normalized phone (unless allow_shared_household_phone — family booking
      adds a dependent on the verified primary's number)
    - Valid date_of_birth (past, realistic)
    - Phone normalizes to 10 digits
    """
    # --- validate inputs ---
    try:
        norm_phone = normalize_phone(payload.phone_number)
    except ValueError as exc:
        return CreatePatientOutput(success=False, error=str(exc))

    try:
        validate_dob(payload.date_of_birth)
    except ValueError as exc:
        return CreatePatientOutput(success=False, error=str(exc))

    # --- duplicate check ---
    if not allow_shared_household_phone:
        existing = db.execute(
            select(Patient).where(Patient.practice_id == practice_id).limit(500)
        ).scalars().all()

        for p in existing:
            if normalize_phone_digits(p.phone_number) == norm_phone:
                return CreatePatientOutput(
                    success=False,
                    error=(
                        f"A patient with that phone number already exists "
                        f"({p.first_name} {p.last_name}). Are you an existing patient?"
                    ),
                )

    # --- create patient ---
    patient = Patient(
        practice_id=practice_id,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone_number=norm_phone,
        date_of_birth=payload.date_of_birth,
        email=payload.email,
        preferred_contact_method=payload.preferred_contact_method or "text",
        is_existing_patient=False,
        status="lead",
    )
    db.add(patient)
    db.flush()  # get patient.id without committing

    # --- optionally link insurance ---
    primary_insurance: str | None = None
    if payload.insurance_name:
        plan = _fuzzy_find_plan(db, practice_id, payload.insurance_name)
        if plan:
            db.add(
                PatientInsurancePolicy(
                    patient_id=patient.id,
                    insurance_plan_id=plan.id,
                    provider_name=plan.carrier_name,
                    is_primary=True,
                    verification_status="unverified",
                )
            )
            primary_insurance = plan.carrier_name

    db.commit()
    db.refresh(patient)

    return CreatePatientOutput(success=True, patient=_patient_to_out(patient, primary_insurance))


def _fuzzy_find_plan(db: Session, practice_id: str, insurance_name: str) -> InsurancePlan | None:
    """Case-insensitive substring match against carrier_name in insurance_plans."""
    plans = db.execute(
        select(InsurancePlan).where(InsurancePlan.practice_id == practice_id)
    ).scalars().all()

    query = insurance_name.strip().lower()
    # exact match first
    for plan in plans:
        if plan.carrier_name.lower() == query:
            return plan
    # substring match
    for plan in plans:
        if query in plan.carrier_name.lower() or plan.carrier_name.lower() in query:
            return plan
    return None
