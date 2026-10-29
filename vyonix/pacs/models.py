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
    source_ae: Mapped[str | None] = mapped_column(String(16))                # equipamento de origem (DIMSE)
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
    # cadastro do equipamento (pacs_0006)
    name: Mapped[str | None] = mapped_column(String(120))
    manufacturer: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    modality: Mapped[str | None] = mapped_column(String(16))
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    can_store: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_echo_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_echo_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_error: Mapped[str | None] = mapped_column(String(300))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PacsDicomEvent(TenantMixin, Base):
    """Histórico de conexões DICOM da organização: associações aceitas e recusadas, C-ECHO, recepções e envios.

    Eventos iguais (mesmo AE, serviço e resultado) em até 10 minutos são agrupados em ``count`` para não crescer a cada
    imagem. Sem dados de paciente."""
    __tablename__ = "dicom_events"
    __table_args__ = (Index("ix_pacs_dicom_events_at", "tenant_id", "last_at"), SCHEMA)
    node_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)          # in | out
    service: Mapped[str] = mapped_column(String(16), nullable=False)          # association|echo|store|find|move|get|mwl|mpps
    outcome: Mapped[str] = mapped_column(String(12), nullable=False)          # accepted|rejected|ok|failed|held
    calling_ae: Mapped[str | None] = mapped_column(String(16))
    called_ae: Mapped[str | None] = mapped_column(String(16))
    address: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(String(300))
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PacsStoreHold(TenantMixin, Base):
    """Instância recebida por C-STORE de um equipamento não autorizado (política "só equipamentos cadastrados"):
    fica no motor, sem índice e sem acesso, até o administrador autorizar (indexar) ou descartar."""
    __tablename__ = "store_holds"
    __table_args__ = (Index("uq_pacs_store_holds", "tenant_id", "backend", "backend_id", unique=True), SCHEMA)
    backend: Mapped[str] = mapped_column(String(20), nullable=False)
    backend_id: Mapped[str] = mapped_column(String(80), nullable=False)
    remote_aet: Mapped[str | None] = mapped_column(String(16))
    remote_ip: Mapped[str | None] = mapped_column(String(64))
    called_aet: Mapped[str | None] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="held")   # held|released|discarded
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(300))


class PacsForwardRule(TenantMixin, Base):
    """Regra de encaminhamento automático: estudo recebido que combina com a origem e/ou a modalidade é enviado
    (C-STORE) ao nó de destino da organização com permissão de receber estudos."""
    __tablename__ = "forward_rules"
    __table_args__ = (SCHEMA,)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str | None] = mapped_column(String(16))          # estação/AE de origem (None = qualquer)
    modality: Mapped[str | None] = mapped_column(String(16))        # None = qualquer
    destination_node_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)


class PacsForwardJob(TenantMixin, Base):
    """Envio de um estudo a um nó (por regra ou manual), com novas tentativas. SHA-256 conferido em cada imagem."""
    __tablename__ = "forward_jobs"
    __table_args__ = (Index("ix_pacs_forward_jobs_due", "tenant_id", "status", "next_attempt_at"), SCHEMA)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)          # pacs.studies.id
    destination_node_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")   # queued|done|failed|cancelled
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    instances: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    integrity_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by: Mapped[str] = mapped_column(String(120), nullable=False)


class PacsEdgeSync(TenantMixin, Base):
    """Fila de sincronização edge → central (protótipo ADR-0014, desabilitado): uma linha por instância local."""
    __tablename__ = "edge_sync"
    __table_args__ = (Index("uq_pacs_edge_sync_instance", "tenant_id", "instance_id", unique=True),
                      Index("ix_pacs_edge_sync_due", "tenant_id", "status", "next_attempt_at"), SCHEMA)
    instance_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")  # queued|synced|conflict|integrity
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(300))
    remote_sha256: Mapped[str | None] = mapped_column(String(64))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ViewerProtocol(TenantMixin, Base):
    """Protocolo de exibição do Viewer: da instituição (``owner_user_id`` vazio) ou pessoal do médico; por modalidade
    e/ou procedimento (ambos vazios = padrão). ``layout``: default | grid | compare (atual + anterior)."""
    __tablename__ = "viewer_protocols"
    __table_args__ = (Index("ix_pacs_viewer_protocols_owner", "tenant_id", "owner_user_id"), SCHEMA)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    modality: Mapped[str | None] = mapped_column(String(16))
    procedure_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    layout: Mapped[str] = mapped_column(String(12), nullable=False, default="default")
    compare_prior: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    prior_same_modality: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
