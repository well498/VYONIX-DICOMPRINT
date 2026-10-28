"""Agendamentos do RIS (por organização, com row level security)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from vyonix.db.base import Base, TenantMixin

SCHEMA = {"schema": "ris"}
STATUSES = ("scheduled", "arrived", "in_progress", "received", "completed", "cancelled")   # arrived = check-in


class Schedule(TenantMixin, Base):
    """Passo de procedimento agendado (DICOM Scheduled Procedure Step) de um pedido."""
    __tablename__ = "schedules"
    __table_args__ = (Index("uq_ris_schedules_sps", "tenant_id", "sps_id", unique=True),
                      Index("uq_ris_schedules_study_uid", "tenant_id", "study_instance_uid", unique=True),
                      Index("ix_ris_schedules_when", "tenant_id", "scheduled_at"),
                      Index("uq_ris_schedules_mpps", "tenant_id", "mpps_uid", unique=True,
                            postgresql_where=text("mpps_uid IS NOT NULL")), SCHEMA)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.orders.id"), nullable=False, index=True)
    sps_id: Mapped[str] = mapped_column(String(16), nullable=False)
    study_instance_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    modality: Mapped[str] = mapped_column(String(16), nullable=False)
    station_aet: Mapped[str | None] = mapped_column(String(16))
    room: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="scheduled")
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False, default=15, server_default="15")
    mpps_uid: Mapped[str | None] = mapped_column(String(64))         # MPPS (N-CREATE) da modalidade
    mpps_status: Mapped[str | None] = mapped_column(String(16))      # IN PROGRESS | COMPLETED | DISCONTINUED
    mpps_performed: Mapped[dict | None] = mapped_column(JSON)         # {série: [SOP Instance UIDs]} informados no MPPS
    mpps_summary: Mapped[dict | None] = mapped_column(JSON)           # séries e dose informadas no MPPS (não validadas)


class Room(TenantMixin, Base):
    """Sala de exames: nome único, modalidade, estação (AE) e duração padrão para o agendamento."""
    __tablename__ = "rooms"
    __table_args__ = (Index("uq_ris_rooms_name", "tenant_id", text("lower(name)"), unique=True), SCHEMA)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    modality: Mapped[str | None] = mapped_column(String(16))
    station_aet: Mapped[str | None] = mapped_column(String(16))
    default_duration_min: Mapped[int] = mapped_column(Integer, nullable=False, default=15, server_default="15")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))


# ------------------------------------------------------------------ preparação técnica do estudo (Central de Exames)
class ExamPrep(TenantMixin, Base):
    """Preparação técnica de um estudo recebido antes do laudo. Criada sob demanda (sem linha = "recebido")."""
    __tablename__ = "exam_preps"
    __table_args__ = (Index("uq_ris_exam_preps_study", "tenant_id", "study_id", unique=True), SCHEMA)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.studies.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="preparing")
    checklist: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)      # código -> {done, by, at}
    priority: Mapped[str | None] = mapped_column(String(10))                           # estudo sem pedido
    reason: Mapped[str | None] = mapped_column(String(300))                            # devolução / cancelamento
    forwarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    forwarded_by: Mapped[str | None] = mapped_column(String(120))
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    duplicate_checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class ExamAttachment(TenantMixin, Base):
    """Documento, foto de documento ou áudio do técnico: cifrado (AES-GCM), validado pelo conteúdo, sem URL pública."""
    __tablename__ = "exam_attachments"
    __table_args__ = (Index("ix_ris_exam_attachments_study", "tenant_id", "study_id"), SCHEMA)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.studies.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)                      # document | photo | audio
    media_type: Mapped[str] = mapped_column(String(40), nullable=False)
    filename: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class ExamComment(TenantMixin, Base):
    __tablename__ = "exam_comments"
    __table_args__ = (Index("ix_ris_exam_comments_study", "tenant_id", "study_id"), SCHEMA)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.studies.id"), nullable=False)
    author: Mapped[str] = mapped_column(String(120), nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    text: Mapped[str] = mapped_column(String(2000), nullable=False)


class ExamCommentRead(TenantMixin, Base):
    __tablename__ = "exam_comment_reads"
    __table_args__ = (Index("uq_ris_exam_comment_reads", "tenant_id", "study_id", "user_id", unique=True), SCHEMA)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.studies.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExamFlag(TenantMixin, Base):
    """Suspeita técnica registrada por pessoa (o sistema não conclui sozinho)."""
    __tablename__ = "exam_flags"
    __table_args__ = (Index("ix_ris_exam_flags_study", "tenant_id", "study_id"), SCHEMA)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.studies.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")   # open | resolved
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    resolved_by: Mapped[str | None] = mapped_column(String(120))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExamShare(TenantMixin, Base):
    """Acesso temporário de um usuário da instituição a um estudo (visualizar ou laudar), com prazo."""
    __tablename__ = "exam_shares"
    __table_args__ = (Index("ix_ris_exam_shares_user", "tenant_id", "user_id"), SCHEMA)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.studies.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    scope: Mapped[str] = mapped_column(String(10), nullable=False, default="view")     # view | report
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
