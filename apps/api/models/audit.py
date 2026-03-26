from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, new_uuid, utcnow


class DomainEvent(Base):
    """Append-only event log. Never update or delete rows."""

    __tablename__ = "domain_events"
    __table_args__ = (
        Index("ix_domain_events_aggregate", "aggregate_type", "aggregate_id"),
        Index("ix_domain_events_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # conversation | appointment | patient | notification
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # conversation_started | patient_created | appointment_requested | appointment_booked |
    # appointment_cancelled | appointment_rescheduled | emergency_flagged | notification_created
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    # assistant | staff | system
    created_by_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
