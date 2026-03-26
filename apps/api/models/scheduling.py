from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, new_uuid, utcnow

if TYPE_CHECKING:
    pass


class AppointmentType(Base):
    __tablename__ = "appointment_types"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    # cleaning | general_checkup | emergency | new_patient_exam
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    default_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    requires_provider_type: Mapped[str | None] = mapped_column(Text)
    is_emergency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    slots: Mapped[list[AppointmentSlot]] = relationship("AppointmentSlot", back_populates="appointment_type")
    requests: Mapped[list[AppointmentRequest]] = relationship("AppointmentRequest", back_populates="appointment_type")


class AppointmentSlot(Base, TimestampMixin):
    __tablename__ = "appointment_slots"
    __table_args__ = (
        Index("ix_appt_slots_location_starts", "location_id", "starts_at"),
        Index("ix_appt_slots_provider_starts", "provider_id", "starts_at"),
        Index("ix_appt_slots_status_starts", "slot_status", "starts_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey("locations.id"), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("providers.id"))
    operatory_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("operatories.id"))
    appointment_type_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("appointment_types.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # available | held | booked | blocked | expired
    slot_status: Mapped[str] = mapped_column(Text, nullable=False, default="available")
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hold_token: Mapped[str | None] = mapped_column(Text)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    appointment_type: Mapped[AppointmentType | None] = relationship("AppointmentType", back_populates="slots")
    appointment: Mapped[Appointment | None] = relationship("Appointment", back_populates="slot", uselist=False)


class AppointmentRequestGroup(Base, TimestampMixin):
    __tablename__ = "appointment_request_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    family_group_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("family_groups.id"))
    requested_by_patient_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("patients.id"))
    requested_by_responsible_party_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("responsible_parties.id")
    )
    # same_day | back_to_back | same_provider | best_available
    group_preference: Mapped[str | None] = mapped_column(Text)
    # pending | partially_fulfilled | fulfilled | manual_review | cancelled
    request_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    notes: Mapped[str | None] = mapped_column(Text)

    requests: Mapped[list[AppointmentRequest]] = relationship("AppointmentRequest", back_populates="request_group")
    appointments: Mapped[list[Appointment]] = relationship("Appointment", back_populates="appointment_group")


class AppointmentRequest(Base, TimestampMixin):
    __tablename__ = "appointment_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    request_group_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("appointment_request_groups.id"))
    # NOTE: conversations table is defined in conversation.py; use string FK reference
    conversation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("conversations.id"))
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey("locations.id"), nullable=False)
    appointment_type_id: Mapped[str] = mapped_column(String(36), ForeignKey("appointment_types.id"), nullable=False)
    preferred_date_from: Mapped[date | None] = mapped_column(Date)
    preferred_date_to: Mapped[date | None] = mapped_column(Date)
    # morning | afternoon | evening | after_school | any
    preferred_time_of_day: Mapped[str | None] = mapped_column(Text)
    natural_language_preference: Mapped[str | None] = mapped_column(Text)
    # routine | urgent | emergency
    urgency_level: Mapped[str] = mapped_column(Text, nullable=False, default="routine")
    insurance_context: Mapped[str | None] = mapped_column(Text)
    # draft | ready_for_search | options_presented | confirmed_by_patient
    # converted | abandoned | manual_review
    request_status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    extracted_constraints: Mapped[dict | None] = mapped_column(JSON)

    request_group: Mapped[AppointmentRequestGroup | None] = relationship(
        "AppointmentRequestGroup", back_populates="requests"
    )
    appointment_type: Mapped[AppointmentType] = relationship("AppointmentType", back_populates="requests")
    appointment: Mapped[Appointment | None] = relationship(
        "Appointment", back_populates="appointment_request", uselist=False
    )


class Appointment(Base, TimestampMixin):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    appointment_request_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("appointment_requests.id"))
    appointment_group_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("appointment_request_groups.id"))
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    # unique: one slot → at most one appointment
    slot_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("appointment_slots.id"), unique=True)
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey("locations.id"), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("providers.id"))
    operatory_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("operatories.id"))
    appointment_type_id: Mapped[str] = mapped_column(String(36), ForeignKey("appointment_types.id"), nullable=False)
    # booked | confirmed | checked_in | completed | cancelled | no_show | rescheduled
    status: Mapped[str] = mapped_column(Text, nullable=False)
    # chatbot | staff | phone | walk_in
    booked_via: Mapped[str] = mapped_column(Text, nullable=False, default="chatbot")
    scheduled_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason_for_visit: Mapped[str | None] = mapped_column(Text)
    special_instructions: Mapped[str | None] = mapped_column(Text)
    is_emergency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    emergency_summary: Mapped[str | None] = mapped_column(Text)
    rescheduled_from_appointment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("appointments.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    created_by_staff_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("staff_users.id"))

    slot: Mapped[AppointmentSlot | None] = relationship("AppointmentSlot", back_populates="appointment")
    appointment_request: Mapped[AppointmentRequest | None] = relationship(
        "AppointmentRequest", back_populates="appointment"
    )
    appointment_group: Mapped[AppointmentRequestGroup | None] = relationship(
        "AppointmentRequestGroup", back_populates="appointments"
    )
