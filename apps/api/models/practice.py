from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, SmallInteger, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, new_uuid, utcnow

if TYPE_CHECKING:
    pass


class Practice(Base, TimestampMixin):
    __tablename__ = "practices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="America/Toronto")
    phone_number: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    locations: Mapped[list[Location]] = relationship("Location", back_populates="practice")


class Location(Base, TimestampMixin):
    __tablename__ = "locations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address_line_1: Mapped[str] = mapped_column(Text, nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    province: Mapped[str] = mapped_column(Text, nullable=False)
    postal_code: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[str] = mapped_column(Text, nullable=False, default="CA")
    phone_number: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    practice: Mapped[Practice] = relationship("Practice", back_populates="locations")
    hours: Mapped[list[LocationHours]] = relationship("LocationHours", back_populates="location")
    operatories: Mapped[list[Operatory]] = relationship("Operatory", back_populates="location")


class LocationHours(Base):
    __tablename__ = "location_hours"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey("locations.id"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    open_time: Mapped[time | None] = mapped_column(Time)
    close_time: Mapped[time | None] = mapped_column(Time)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    effective_start_date: Mapped[date | None] = mapped_column(Date)
    effective_end_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    location: Mapped[Location] = relationship("Location", back_populates="hours")


class Operatory(Base):
    __tablename__ = "operatories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey("locations.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    chair_code: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    location: Mapped[Location] = relationship("Location", back_populates="operatories")
