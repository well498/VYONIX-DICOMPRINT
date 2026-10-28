"""Índice do PACS no PostgreSQL (por organização, com row level security).

O arquivo DICOM fica no motor (Orthanc). O índice consultado pelo DICOMweb fica aqui — é ele que
garante que uma organização só veja os próprios estudos, mesmo com um único motor por servidor.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from vyonix.db.base import Base, TenantMixin

SCHEMA = {"schema": "pacs"}


class PacsStudy(TenantMixin, Base):
    __tablename__ = "studies"
    __table_args__ = (Index("uq_pacs_studies_uid", "tenant_id", "study_uid", unique=True),
                      Index("ix_pacs_studies_patient", "tenant_id", "patient_id"),
                      Index("ix_pacs_studies_date", "tenant_id", "study_date"), SCHEMA)
    study_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    patient_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    patient_birth_date: Mapped[date | None] = mapped_column(Date)
    patient_sex: Mapped[str | None] = mapped_column(String(1))
    study_date: Mapped[date | None] = mapped_column(Date)
    study_time: Mapped[str | None] = mapped_column(String(16))
    accession: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(String(200))
    referring_physician: Mapped[str | None] = mapped_column(String(200))
    dicom_study_id: Mapped[str | None] = mapped_column(String(16))
    clinical_study_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("clinical.studies.id"))
    last_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                       server_default=func.now())
    retention_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    retention_hold_reason: Mapped[str | None] = mapped_column(String(300))  # guarda obrigatória (processo, pedido)


class PacsSeries(TenantMixin, Base):
    __tablename__ = "series"
    __table_args__ = (Index("uq_pacs_series_uid", "tenant_id", "series_uid", unique=True), SCHEMA)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("pacs.studies.id"), nullable=False, index=True)
    series_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    modality: Mapped[str | None] = mapped_column(String(16))
    series_number: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(200))


class PacsInstance(TenantMixin, Base):
    __tablename__ = "instances"
    __table_args__ = (Index("uq_pacs_instances_uid", "tenant_id", "sop_uid", unique=True), SCHEMA)
    series_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("pacs.series.id"), nullable=False, index=True)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("pacs.studies.id"), nullable=False, index=True)
    sop_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    sop_class_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    transfer_syntax: Mapped[str] = mapped_column(String(64), nullable=False)
    instance_number: Mapped[int | None] = mapped_column(Integer)
    rows: Mapped[int | None] = mapped_column(Integer)
    columns: Mapped[int | None] = mapped_column(Integer)
    frames: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    backend: Mapped[str] = mapped_column(String(20), nullable=False)
    backend_id: Mapped[str] = mapped_column(String(80), nullable=False)
    received_via: Mapped[str] = mapped_column(String(10), nullable=False)       # stow | dimse


class PacsSyncState(TenantMixin, Base):
    """Último evento do motor já indexado (recepção por C-STORE direto no Orthanc)."""
    __tablename__ = "sync_state"
    __table_args__ = (Index("uq_pacs_sync_backend", "tenant_id", "backend", unique=True), SCHEMA)
    backend: Mapped[str] = mapped_column(String(20), nullable=False)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class PacsAeRoute(TenantMixin, Base):
    """AE Title chamado pelas modalidades → organização (recepção por C-STORE no modo cloud). Único no servidor."""
    __tablename__ = "ae_routes"
    __table_args__ = (Index("uq_pacs_ae_routes_aet", "called_aet", unique=True), SCHEMA)
    called_aet: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)


class PacsCloudSyncState(Base):
    """Último evento do motor já distribuído às organizações (modo cloud). Só o papel de serviço acessa."""
    __tablename__ = "cloud_sync_state"
    __table_args__ = (SCHEMA,)
    backend: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    quarantined: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PacsDicomNode(TenantMixin, Base):
    """Estação, modalidade ou PACS da organização: pode consultar (C-FIND/C-MOVE) e/ou receber (destino de C-MOVE)."""
    __tablename__ = "dicom_nodes"
    __table_args__ = (Index("uq_pacs_dicom_nodes_aet", "tenant_id", "ae_title", unique=True), SCHEMA)
    ae_title: Mapped[str] = mapped_column(String(16), nullable=False)
    host: Mapped[str | None] = mapped_column(String(64))
    port: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(200))
    can_query: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_receive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
