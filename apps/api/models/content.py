from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, new_uuid, utcnow


class ClinicSettings(Base, TimestampMixin):
    __tablename__ = "clinic_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    default_location_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("locations.id"))
    accepts_major_insurance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    self_pay_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    membership_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    financing_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    emergency_escalation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class FaqEntry(Base, TimestampMixin):
    __tablename__ = "faq_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    location_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("locations.id"))
    # insurance | payment | hours | location | new_patient
    category: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int | None] = mapped_column(Integer)


class PricingOption(Base):
    __tablename__ = "pricing_options"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    location_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("locations.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # self_pay | membership | financing
    pricing_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
