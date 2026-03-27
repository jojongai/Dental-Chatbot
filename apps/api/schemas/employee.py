"""Employee dashboard (schedule) API schemas."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class EmployeeScheduleAppointment(BaseModel):
    id: str
    patient_name: str
    appointment_type_display: str
    appointment_type_code: str
    time_start: str = Field(..., description="e.g. '8:00 AM'")
    duration_minutes: int
    provider_display_name: str | None = None
    status: str = Field(..., description="Raw DB status")
    ui_status: str = Field(
        ...,
        description="Mapped for UI: confirmed | arrived | in-progress | completed | cancelled",
    )
    is_emergency: bool = False


class EmployeeEmergencyAlert(BaseModel):
    id: str
    patient_name: str
    description: str
    time: str
    severity: str = Field(default="critical", description="urgent | critical")


class WeekDayCount(BaseModel):
    day: str = Field(..., description="Mon, Tue, …")
    count: int
    date: date


class EmployeeScheduleOut(BaseModel):
    date: date
    timezone: str = "America/Toronto"
    appointments: list[EmployeeScheduleAppointment]
    emergency_alerts: list[EmployeeEmergencyAlert]
    week_day_counts: list[WeekDayCount]
    provider_count: int = Field(..., description="Active bookable providers (for stats card)")
