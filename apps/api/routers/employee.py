"""
Employee dashboard — schedule views for front-desk UI (Next.js /employee).

GET /v1/employee/schedule  — appointments for a calendar day + week counts (Toronto TZ)
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from schemas.employee import EmployeeScheduleOut
from tools.scheduling_tools import get_employee_schedule

router = APIRouter(prefix="/v1/employee", tags=["employee"])


@router.get("/schedule", response_model=EmployeeScheduleOut, summary="Day schedule for employee dashboard")
async def employee_schedule(
    schedule_date: date | None = Query(
        None,
        alias="date",
        description="Calendar day (ISO). Defaults to today in America/Toronto.",
    ),
    db: Session = Depends(get_db),
) -> EmployeeScheduleOut:
    return get_employee_schedule(db, schedule_date)
