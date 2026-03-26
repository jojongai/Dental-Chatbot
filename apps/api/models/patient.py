from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, new_uuid, utcnow


class Patient(Base, TimestampMixin):
    __tablename__ = "patients"
    __table_args__ = (
        Index("ix_patients_last_name_dob", "last_name", "date_of_birth"),
        Index("ix_patients_phone", "phone_number"),
        Index("ix_patients_email", "email"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    primary_location_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("locations.id"))
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    middle_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    sex: Mapped[str | None] = mapped_column(Text)
    phone_number: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    # phone | text | email
    preferred_contact_method: Mapped[str | None] = mapped_column(Text)
    is_existing_patient: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # lead | active | inactive
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(Text)

    addresses: Mapped[list[PatientAddress]] = relationship("PatientAddress", back_populates="patient")
    insurance_policies: Mapped[list[PatientInsurancePolicy]] = relationship(
        "PatientInsurancePolicy", back_populates="patient"
    )
    responsible_party_links: Mapped[list[PatientResponsibleParty]] = relationship(
        "PatientResponsibleParty", back_populates="patient"
    )
    family_memberships: Mapped[list[FamilyGroupMember]] = relationship(
        "FamilyGroupMember", back_populates="patient"
    )


class PatientAddress(Base):
    __tablename__ = "patient_addresses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    address_type: Mapped[str] = mapped_column(Text, nullable=False, default="home")
    address_line_1: Mapped[str] = mapped_column(Text, nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    province: Mapped[str] = mapped_column(Text, nullable=False)
    postal_code: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[str] = mapped_column(Text, nullable=False, default="CA")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    patient: Mapped[Patient] = relationship("Patient", back_populates="addresses")


class ResponsibleParty(Base, TimestampMixin):
    __tablename__ = "responsible_parties"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_number: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    relationship_to_patient: Mapped[str | None] = mapped_column(Text)

    patient_links: Mapped[list[PatientResponsibleParty]] = relationship(
        "PatientResponsibleParty", back_populates="responsible_party"
    )


class PatientResponsibleParty(Base):
    __tablename__ = "patient_responsible_parties"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    responsible_party_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("responsible_parties.id"), nullable=False
    )
    # parent | guardian | spouse | self
    relationship_type: Mapped[str] = mapped_column(Text, nullable=False)
    is_primary_contact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_schedule: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_receive_billing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    patient: Mapped[Patient] = relationship("Patient", back_populates="responsible_party_links")
    responsible_party: Mapped[ResponsibleParty] = relationship(
        "ResponsibleParty", back_populates="patient_links"
    )


class FamilyGroup(Base, TimestampMixin):
    __tablename__ = "family_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    primary_contact_patient_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("patients.id"))
    primary_contact_responsible_party_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("responsible_parties.id")
    )
    notes: Mapped[str | None] = mapped_column(Text)

    members: Mapped[list[FamilyGroupMember]] = relationship(
        "FamilyGroupMember", back_populates="family_group"
    )


class FamilyGroupMember(Base):
    __tablename__ = "family_group_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    family_group_id: Mapped[str] = mapped_column(String(36), ForeignKey("family_groups.id"), nullable=False)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    # child | parent | spouse
    member_role: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    family_group: Mapped[FamilyGroup] = relationship("FamilyGroup", back_populates="members")
    patient: Mapped[Patient] = relationship("Patient", back_populates="family_memberships")


class InsurancePlan(Base):
    __tablename__ = "insurance_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id"), nullable=False)
    carrier_name: Mapped[str] = mapped_column(Text, nullable=False)
    plan_name: Mapped[str | None] = mapped_column(Text)
    plan_code: Mapped[str | None] = mapped_column(Text)
    # accepted | not_accepted | limited
    acceptance_status: Mapped[str] = mapped_column(Text, nullable=False, default="accepted")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    patient_policies: Mapped[list[PatientInsurancePolicy]] = relationship(
        "PatientInsurancePolicy", back_populates="insurance_plan"
    )


class PatientInsurancePolicy(Base, TimestampMixin):
    __tablename__ = "patient_insurance_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    insurance_plan_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("insurance_plans.id"))
    provider_name: Mapped[str] = mapped_column(Text, nullable=False)
    member_id: Mapped[str | None] = mapped_column(Text)
    group_number: Mapped[str | None] = mapped_column(Text)
    policy_holder_name: Mapped[str | None] = mapped_column(Text)
    policy_holder_relationship: Mapped[str | None] = mapped_column(Text)
    effective_date: Mapped[date | None] = mapped_column(Date)
    termination_date: Mapped[date | None] = mapped_column(Date)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # unverified | verified | pending
    verification_status: Mapped[str] = mapped_column(Text, nullable=False, default="unverified")

    patient: Mapped[Patient] = relationship("Patient", back_populates="insurance_policies")
    insurance_plan: Mapped[InsurancePlan | None] = relationship(
        "InsurancePlan", back_populates="patient_policies"
    )
