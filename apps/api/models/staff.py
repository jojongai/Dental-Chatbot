from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, new_uuid, utcnow


class StaffUser(Base, TimestampMixin):
    __tablename__ = "staff_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    location_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("locations.id"))
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    phone_number: Mapped[str | None] = mapped_column(Text)
    # admin | receptionist | dentist | hygienist | assistant
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    provider: Mapped[Provider | None] = relationship("Provider", back_populates="staff_user", uselist=False)


class Provider(Base, TimestampMixin):
    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    staff_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("staff_users.id"), unique=True)
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey("locations.id"), nullable=False)
    # dentist | hygienist
    provider_type: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    license_number: Mapped[str | None] = mapped_column(Text)
    specialties: Mapped[dict | None] = mapped_column(JSON)
    is_bookable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    staff_user: Mapped[StaffUser | None] = relationship("StaffUser", back_populates="provider")
    schedule_templates: Mapped[list[ProviderScheduleTemplate]] = relationship(
        "ProviderScheduleTemplate", back_populates="provider"
    )
    schedule_exceptions: Mapped[list[ProviderScheduleException]] = relationship(
        "ProviderScheduleException", back_populates="provider"
    )


class ProviderScheduleTemplate(Base):
    __tablename__ = "provider_schedule_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("providers.id"), nullable=False)
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey("locations.id"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_start_date: Mapped[date | None] = mapped_column(Date)
    effective_end_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    provider: Mapped[Provider] = relationship("Provider", back_populates="schedule_templates")


class ProviderScheduleException(Base):
    __tablename__ = "provider_schedule_exceptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("providers.id"), nullable=False)
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey("locations.id"), nullable=False)
    exception_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    is_unavailable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    provider: Mapped[Provider] = relationship("Provider", back_populates="schedule_exceptions")
