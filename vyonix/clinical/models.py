from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from vyonix.db.base import Base, TenantMixin

SCHEMA = {"schema": "clinical"}


class Patient(TenantMixin, Base):
    __tablename__ = "patients"
    __table_args__ = (Index("ix_patients_name", "tenant_id", "name"), SCHEMA)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(String(1))                  # M, F, O (DICOM)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("clinical.patients.id"))


class PatientIdentifier(TenantMixin, Base):
    """Identificador por emissor (prontuário, CPF, CNS, ID do HIS). Único por (clínica, emissor, valor)."""
    __tablename__ = "patient_identifiers"
    __table_args__ = (Index("uq_patient_identifiers_issuer_value", "tenant_id", "issuer", "value", unique=True), SCHEMA)
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.patients.id"), nullable=False, index=True)
    issuer: Mapped[str] = mapped_column(String(60), nullable=False)
    value: Mapped[str] = mapped_column(String(80), nullable=False)


class Encounter(TenantMixin, Base):
    __tablename__ = "encounters"
    __table_args__ = (Index("uq_encounters_site_number", "tenant_id", "site_id", "number", unique=True), SCHEMA)
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.patients.id"), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenancy.sites.id"), nullable=False)
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")      # open|closed|cancelled


class Procedure(TenantMixin, Base):
    __tablename__ = "procedures"
    __table_args__ = (Index("uq_procedures_code", "tenant_id", "code", unique=True), SCHEMA)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    modality: Mapped[str | None] = mapped_column(String(8))
    tuss: Mapped[str | None] = mapped_column(String(12))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Order(TenantMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (Index("uq_orders_accession", "tenant_id", "accession", unique=True,
                            postgresql_where="accession IS NOT NULL"), SCHEMA)
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.patients.id"), nullable=False, index=True)
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("clinical.encounters.id"))
    procedure_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("clinical.procedures.id"))
    requester: Mapped[str | None] = mapped_column(String(200))
    accession: Mapped[str | None] = mapped_column(String(32))
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="routine")   # routine|urgent|stat
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenancy.sites.id"))      # P0 0.3.2


class Study(TenantMixin, Base):
    __tablename__ = "studies"
    __table_args__ = (Index("uq_studies_uid", "tenant_id", "study_instance_uid", unique=True), SCHEMA)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("clinical.patients.id"), index=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("clinical.orders.id"))
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenancy.sites.id"))
    study_instance_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    accession: Mapped[str | None] = mapped_column(String(32))
    modality: Mapped[str | None] = mapped_column(String(8))
    study_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    storage_location: Mapped[str | None] = mapped_column(String(40))
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # P0 0.3.2: origem da unidade (pedido, atendimento, no_dicom, unica, manual, simulacao); NULL = legado
    site_source: Mapped[str | None] = mapped_column(String(12))
    site_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    site_set_by: Mapped[str | None] = mapped_column(String(120))


class StudySiteAssignment(TenantMixin, Base):
    """Trilha somente-inserção das atribuições de unidade a estudos (P0 0.3.2)."""
    __tablename__ = "study_site_assignments"
    __table_args__ = (Index("ix_clinical_ssa_study", "tenant_id", "study_id", "created_at"), SCHEMA)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.studies.id"), nullable=False)
    from_site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    to_site_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenancy.sites.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    simulation_sha256: Mapped[str | None] = mapped_column(String(64))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class PatientMerge(TenantMixin, Base):
    """Mescla de pacientes: guarda o que foi movido para permitir desfazer (auditável)."""
    __tablename__ = "patient_merges"
    __table_args__ = SCHEMA
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.patients.id"), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.patients.id"), nullable=False)
    moved: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    merged_by: Mapped[str] = mapped_column(String(120), nullable=False)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_by: Mapped[str | None] = mapped_column(String(120))
