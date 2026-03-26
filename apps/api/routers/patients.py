"""
Patient REST endpoints.

Used by: staff dashboard (direct access), chatbot tool layer, testing.

GET  /v1/patients          — lookup / search
POST /v1/patients          — create new patient
GET  /v1/patients/{id}     — get by ID
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from schemas.patient import PatientCreateIn, PatientOut

router = APIRouter(prefix="/v1/patients", tags=["patients"])


@router.get("", response_model=list[PatientOut], summary="Lookup patient")
async def lookup_patient(
    phone_number: str | None = Query(None, examples=["(416) 555-2001"]),
    last_name: str | None = Query(None),
    date_of_birth: str | None = Query(None, description="ISO date: YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> list[PatientOut]:
    """
    Search for existing patients.

    Accepts at least one of: phone_number OR (last_name + date_of_birth).

    TODO: delegate to tools.patient_tools.lookup_patient.
    """
    if not phone_number and not (last_name and date_of_birth):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide phone_number or last_name+date_of_birth.",
        )
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="TODO")


@router.post(
    "",
    response_model=PatientOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register new patient",
)
async def create_patient(
    body: PatientCreateIn,
    db: Session = Depends(get_db),
) -> PatientOut:
    """
    Create a new patient record (status='lead').

    TODO: delegate to tools.patient_tools.create_patient.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="TODO")


@router.get("/{patient_id}", response_model=PatientOut, summary="Get patient by ID")
async def get_patient(
    patient_id: str,
    db: Session = Depends(get_db),
) -> PatientOut:
    """
    Fetch a patient record by UUID.

    TODO: query patients table.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="TODO")
