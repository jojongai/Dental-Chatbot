"""
SQLAlchemy model registry.

Importing this package registers all ORM models with Base.metadata,
which is required before calling Base.metadata.create_all() or running
Alembic migrations.
"""

from models.audit import DomainEvent
from models.base import Base, TimestampMixin, new_uuid, utcnow
from models.content import ClinicSettings, FaqEntry, PricingOption
from models.conversation import (
    Conversation,
    ConversationIntent,
    ConversationMessage,
    ConversationStateSnapshot,
)
from models.notification import StaffNotification, WorkQueueItem
from models.patient import (
    FamilyGroup,
    FamilyGroupMember,
    InsurancePlan,
    Patient,
    PatientAddress,
    PatientInsurancePolicy,
    PatientResponsibleParty,
    ResponsibleParty,
)
from models.practice import Location, LocationHours, Operatory, Practice
from models.scheduling import (
    Appointment,
    AppointmentRequest,
    AppointmentRequestGroup,
    AppointmentSlot,
    AppointmentType,
)
from models.staff import (
    Provider,
    ProviderScheduleException,
    ProviderScheduleTemplate,
    StaffUser,
)

__all__ = [
    "Base",
    "TimestampMixin",
    "new_uuid",
    "utcnow",
    # practice
    "Practice",
    "Location",
    "LocationHours",
    "Operatory",
    # staff
    "StaffUser",
    "Provider",
    "ProviderScheduleTemplate",
    "ProviderScheduleException",
    # patient
    "Patient",
    "PatientAddress",
    "ResponsibleParty",
    "PatientResponsibleParty",
    "FamilyGroup",
    "FamilyGroupMember",
    "InsurancePlan",
    "PatientInsurancePolicy",
    # scheduling
    "AppointmentType",
    "AppointmentSlot",
    "AppointmentRequestGroup",
    "AppointmentRequest",
    "Appointment",
    # conversation
    "Conversation",
    "ConversationMessage",
    "ConversationStateSnapshot",
    "ConversationIntent",
    # notification
    "StaffNotification",
    "WorkQueueItem",
    # content
    "ClinicSettings",
    "FaqEntry",
    "PricingOption",
    # audit
    "DomainEvent",
]
