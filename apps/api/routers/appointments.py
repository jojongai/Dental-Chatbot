"""
Appointment REST endpoints.

Used by: staff dashboard, chatbot tool layer, testing.

GET    /v1/appointments/slots              — search available slots
GET    /v1/appointments/{id}               — get appointment by ID
POST   /v1/appointments                    — book appointment (single patient)
POST   /v1/appointments/family             — book family back-to-back
PUT    /v1/appointments/{id}/reschedule    — reschedule
POST   /v1/appointments/{id}/cancel       — cancel
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from schemas.appointment import (
    AppointmentOut,
    BookAppointmentIn,
    CancelAppointmentIn,
    FamilyBookingIn,
    FamilyBookingOut,
    RescheduleAppointmentIn,
    SlotSearchOut,
)

router = APIRouter(prefix="/v1/appointments", tags=["appointments"])


@router.get("/slots", response_model=SlotSearchOut, summary="Search available slots")
async def search_slots(
    appointment_type_code: str,
    date_from: str,
    date_to: str,
    preferred_time_of_day: str = "any",
    provider_type: str | None = None,
    location_id: str | None = None,
    db: Session = Depends(get_db),
) -> SlotSearchOut:
    """
    Return available appointment slots matching the criteria.

    Typical chatbot flow: the orchestration layer calls this after collecting
    appointment_type + date preference, then presents results to the patient.

    TODO: delegate to tools.scheduling_tools.search_slots.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="TODO")


@router.get("/{appointment_id}", response_model=AppointmentOut, summary="Get appointment")
async def get_appointment(
    appointment_id: str,
    db: Session = Depends(get_db),
) -> AppointmentOut:
    """
    Fetch appointment details by ID.

    TODO: query appointments table with joins.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="TODO")


@router.post(
    "",
    response_model=AppointmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Book appointment",
)
async def book_appointment(
    body: BookAppointmentIn,
    db: Session = Depends(get_db),
) -> AppointmentOut:
    """
    Book a slot for a single patient.

    - Set `is_emergency=true` and provide `emergency_summary` for emergency visits;
      the staff dashboard will receive an urgent notification automatically.

    TODO: delegate to tools.scheduling_tools.book_appointment.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="TODO")


@router.post(
    "/family",
    response_model=FamilyBookingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Book back-to-back family appointments",
)
async def book_family_appointments(
    body: FamilyBookingIn,
    db: Session = Depends(get_db),
) -> FamilyBookingOut:
    """
    Book multiple appointments for family members in one request.

    The `group_preference` field controls slot selection:
    - `back_to_back`  — consecutive slots, smallest gap between them.
    - `same_day`      — same calendar day, any time.
    - `same_provider` — all with the same provider if available.
    - `best_available`— independent optimal slots.

    TODO: delegate to tools.scheduling_tools.book_family_appointments.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="TODO")


@router.put(
    "/{appointment_id}/reschedule",
    response_model=AppointmentOut,
    summary="Reschedule appointment",
)
async def reschedule_appointment(
    appointment_id: str,
    body: RescheduleAppointmentIn,
    db: Session = Depends(get_db),
) -> AppointmentOut:
    """
    Move an existing appointment to a new available slot.
    The old slot is automatically freed.

    TODO: delegate to tools.scheduling_tools.reschedule_appointment.
    """
    if body.appointment_id != appointment_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="appointment_id in body must match path parameter.",
        )
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="TODO")


@router.post(
    "/{appointment_id}/cancel",
    response_model=AppointmentOut,
    summary="Cancel appointment",
)
async def cancel_appointment(
    appointment_id: str,
    body: CancelAppointmentIn,
    db: Session = Depends(get_db),
) -> AppointmentOut:
    """
    Cancel an appointment and release the slot.

    TODO: delegate to tools.scheduling_tools.cancel_appointment.
    """
    if body.appointment_id != appointment_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="appointment_id in body must match path parameter.",
        )
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="TODO")
