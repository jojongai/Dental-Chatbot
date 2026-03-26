"""Patient request/response schemas."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


class PatientLookupIn(BaseModel):
    """
    Primary key: first_name + last_name + phone_number (should be unique in practice).
    Falls back to phone-only (confidence 0.8) or name-only (confidence 0.7).
    email is only used as a last-resort tiebreaker if two records share all three primary fields.
    date_of_birth is kept for backwards-compat but no longer required.
    """

    first_name: str | None = Field(None, examples=["Alice"])
    last_name: str | None = Field(None, examples=["Thompson"])
    phone_number: str | None = Field(None, examples=["(416) 555-2001"])
    email: str | None = Field(None, examples=["alice@example.com"])
    date_of_birth: date | None = Field(None, examples=["1985-03-14"])


# ---------------------------------------------------------------------------
# Create (new-patient registration)
# ---------------------------------------------------------------------------


class PatientCreateIn(BaseModel):
    """Minimum fields required during new-patient chat registration."""

    first_name: str = Field(..., examples=["Ben"])
    last_name: str = Field(..., examples=["Kowalski"])
    phone_number: str = Field(..., examples=["(416) 555-2002"])
    date_of_birth: date = Field(..., examples=["1990-07-22"])
    email: str | None = Field(None, examples=["ben.k@example.com"])
    # Insurance carrier name as free text — linked to InsurancePlan later by staff
    insurance_name: str | None = Field(None, examples=["Sun Life"])
    preferred_contact_method: Literal["phone", "text", "email"] | None = None


# ---------------------------------------------------------------------------
# Family member add (within an existing family group)
# ---------------------------------------------------------------------------


class FamilyMemberIn(BaseModel):
    """Add a family member to a booking request (child, spouse, etc.)."""

    patient_id: str | None = Field(None, description="Set if patient already exists.")
    # If patient_id is None, inline creation fields are required:
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    phone_number: str | None = None
    relationship_to_primary: str | None = Field(None, examples=["child", "spouse", "parent"])
    appointment_type_code: str = Field(..., examples=["cleaning"])


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class PatientOut(BaseModel):
    """Patient summary returned after lookup or creation."""

    id: str
    first_name: str
    last_name: str
    preferred_name: str | None
    phone_number: str
    date_of_birth: date
    is_existing_patient: bool
    status: str
    primary_insurance: str | None = None  # carrier name for display
