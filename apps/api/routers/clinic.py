"""
Clinic info endpoints.

GET /v1/clinic/info          — FAQ entries + clinic settings (filtered by category)
GET /v1/clinic/hours         — location hours
GET /v1/clinic/insurance     — accepted insurance plans
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from schemas.tools import GetClinicInfoOutput

router = APIRouter(prefix="/v1/clinic", tags=["clinic"])


@router.get("/info", response_model=GetClinicInfoOutput, summary="Get clinic FAQ and settings")
async def get_clinic_info(
    category: str | None = Query(
        None,
        examples=["insurance", "payment", "hours", "location", "new_patient"],
    ),
    question_hint: str | None = Query(
        None,
        description="Free-text hint to surface the most relevant FAQ entries.",
    ),
    db: Session = Depends(get_db),
) -> GetClinicInfoOutput:
    """
    Return FAQ entries and clinic settings.

    Called by the chatbot during general_inquiry workflow and directly by the
    frontend for static content pages.

    TODO: delegate to tools.clinic_tools.get_clinic_info.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="TODO")


@router.get("/hours", summary="Location hours summary")
async def get_hours(db: Session = Depends(get_db)) -> dict:
    """
    Return structured opening hours for all active locations.

    TODO: query location_hours table and format response.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="TODO")


@router.get("/insurance", summary="Accepted insurance plans")
async def get_insurance_plans(db: Session = Depends(get_db)) -> dict:
    """
    Return the list of accepted insurance plans.

    TODO: query insurance_plans WHERE acceptance_status='accepted'.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="TODO")
