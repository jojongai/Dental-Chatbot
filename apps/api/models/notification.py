from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, new_uuid, utcnow


class StaffNotification(Base):
    __tablename__ = "staff_notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    location_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("locations.id"))
    conversation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("conversations.id"))
    patient_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("patients.id"))
    appointment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("appointments.id"))
    # emergency | manual_review | callback_request | verification_issue | family_scheduling_complexity
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    # low | normal | high | urgent
    priority: Mapped[str] = mapped_column(Text, nullable=False, default="normal")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # open | acknowledged | resolved | dismissed
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    assigned_to_staff_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("staff_users.id"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class WorkQueueItem(Base, TimestampMixin):
    __tablename__ = "work_queue_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    location_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("locations.id"))
    # manual_review | call_back | insurance_follow_up | family_coordination | escalation
    queue_type: Mapped[str] = mapped_column(Text, nullable=False)
    related_conversation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("conversations.id"))
    related_patient_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("patients.id"))
    related_appointment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("appointments.id"))
    assigned_to_staff_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("staff_users.id"))
    # open | in_progress | done | cancelled
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON)
