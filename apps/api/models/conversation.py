from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, new_uuid, utcnow


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    location_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("locations.id"))
    patient_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("patients.id"))
    responsible_party_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("responsible_parties.id"))
    session_token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # web_chat | sms | voice_transcript
    channel: Mapped[str] = mapped_column(Text, nullable=False, default="web_chat")
    # general_inquiry | new_patient_registration | existing_patient_verification |
    # book_appointment | reschedule_appointment | cancel_appointment |
    # family_booking | emergency_triage | handoff
    current_workflow: Mapped[str | None] = mapped_column(Text)
    # active | completed | abandoned | needs_staff_review
    conversation_status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    verified_patient_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2))
    last_user_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_assistant_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list[ConversationMessage]] = relationship("ConversationMessage", back_populates="conversation")
    state_snapshots: Mapped[list[ConversationStateSnapshot]] = relationship(
        "ConversationStateSnapshot", back_populates="conversation"
    )
    intents: Mapped[list[ConversationIntent]] = relationship("ConversationIntent", back_populates="conversation")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=False)
    # user | assistant | system | staff
    sender_type: Mapped[str] = mapped_column(Text, nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    # plain_text | markdown | json
    message_format: Mapped[str] = mapped_column(Text, nullable=False, default="plain_text")
    tool_call_name: Mapped[str | None] = mapped_column(Text)
    tool_result_json: Mapped[dict | None] = mapped_column(JSON)
    llm_model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="messages")


class ConversationStateSnapshot(Base):
    __tablename__ = "conversation_state_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow: Mapped[str] = mapped_column(Text, nullable=False)
    collected_fields: Mapped[dict] = mapped_column(JSON, nullable=False)
    missing_fields: Mapped[dict | None] = mapped_column(JSON)
    next_recommended_action: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="state_snapshots")


class ConversationIntent(Base):
    __tablename__ = "conversation_intents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=False)
    detected_intent: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 2))
    source_message_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("conversation_messages.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="intents")
