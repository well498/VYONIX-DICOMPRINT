"""Eventos operacionais e de auditoria (§18).

Todo texto e todo detalhe passam pela redação de dados de paciente antes de serem
gravados — o banco de eventos nunca deve conter demografia.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from app.database.connection import Database
from app.security.redaction import redact, redact_text
from app.utils.timeutil import to_iso, utc_now, utc_now_iso


class Category:
    SYSTEM = "system"
    DICOM = "dicom"
    DEVICE = "device"
    PROCESSING = "processing"
    RULES = "rules"
    PRINTER = "printer"
    SPOOLER = "spooler"
    JOB = "job"
    ADMIN = "admin"
    LICENSE = "license"
    SECURITY = "security"

    ALL = (SYSTEM, DICOM, DEVICE, PROCESSING, RULES, PRINTER, SPOOLER, JOB, ADMIN, LICENSE, SECURITY)

    LABELS = {
        SYSTEM: "Sistema", DICOM: "DICOM", DEVICE: "Equipamentos", PROCESSING: "Processamento",
        RULES: "Regras", PRINTER: "Impressoras", SPOOLER: "Spooler", JOB: "Trabalhos",
        ADMIN: "Administração", LICENSE: "Licença", SECURITY: "Segurança",
    }


# Categorias que formam a trilha de auditoria (quem alterou o quê): retenção própria, mais longa.
AUDIT_CATEGORIES = (Category.ADMIN, Category.SECURITY, Category.LICENSE)

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


@dataclass(frozen=True)
class EventRecord:
    id: int
    ts: str
    level: str
    category: str
    action: str
    message: str
    device_id: int | None
    job_id: int | None
    actor: str | None
    details: dict[str, Any] | None


@dataclass
class EventFilter:
    start: datetime | None = None
    end: datetime | None = None
    categories: tuple[str, ...] = ()
    min_level: str | None = None
    device_id: int | None = None
    text: str | None = None
    limit: int = 500
    offset: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class EventRepository:
    """Implementa o contrato ``core.contracts.EventSink``."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, *, level: str, category: str, action: str, message: str,
            device_id: int | None = None, job_id: int | None = None,
            actor: str | None = None, details: Mapping[str, Any] | None = None) -> int:
        level = level.upper()
        if level not in LEVELS:
            raise ValueError(f"Nível de evento inválido: {level}")
        details_json = None
        if details:
            details_json = json.dumps(redact(dict(details)), ensure_ascii=False, default=str)
        cur = self.db.connection().execute(
            """INSERT INTO events(ts, level, category, action, message, device_id, job_id,
                                  actor, details_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (utc_now_iso(), level, category, action, redact_text(message), device_id, job_id,
             actor, details_json),
        )
        return int(cur.lastrowid)

    def query(self, flt: EventFilter | None = None) -> list[EventRecord]:
        flt = flt or EventFilter()
        where, params = self._where(flt)
        sql = (f"SELECT * FROM events {where} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?")
        params += [int(flt.limit), int(flt.offset)]
        return [self._row(r) for r in self.db.connection().execute(sql, params)]

    def count(self, flt: EventFilter | None = None) -> int:
        where, params = self._where(flt or EventFilter())
        return int(self.db.connection().execute(
            f"SELECT COUNT(*) FROM events {where}", params).fetchone()[0])

    def export_csv(self, path: Path, flt: EventFilter | None = None) -> int:
        """Exporta eventos para CSV (UTF-8 com BOM, separador ';' — abre corretamente no Excel pt-BR)."""
        flt = flt or EventFilter(limit=1_000_000)
        rows = self.query(flt)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(["id", "data_hora_utc", "nivel", "categoria", "acao", "mensagem",
                             "equipamento_id", "trabalho_id", "usuario", "detalhes"])
            for e in rows:
                writer.writerow([e.id, e.ts, e.level, e.category, e.action, e.message,
                                 e.device_id or "", e.job_id or "", e.actor or "",
                                 json.dumps(e.details, ensure_ascii=False) if e.details else ""])
        return len(rows)

    def purge_older_than(self, days: int, audit_days: int | None = None) -> int:
        """Remove eventos operacionais com mais de ``days`` dias. A trilha de auditoria
        (``AUDIT_CATEGORIES``: administração, segurança e licença) tem prazo próprio, ``audit_days``
        — nunca menor que o dos eventos operacionais (Prompt Mestre §19: logs operacionais
        temporários separados da trilha de auditoria obrigatória)."""
        cutoff = to_iso(utc_now() - timedelta(days=days))
        audit_cutoff = to_iso(utc_now() - timedelta(days=max(days, audit_days if audit_days is not None else days)))
        marks = ",".join("?" * len(AUDIT_CATEGORIES))
        with self.db.transaction():
            cur = self.db.connection().execute(
                f"DELETE FROM events WHERE (category NOT IN ({marks}) AND ts < ?) "
                f"OR (category IN ({marks}) AND ts < ?)",
                (*AUDIT_CATEGORIES, cutoff, *AUDIT_CATEGORIES, audit_cutoff))
        return cur.rowcount

    def last_ts(self) -> str | None:
        row = self.db.connection().execute("SELECT MAX(ts) FROM events").fetchone()
        return row[0]

    # ------------------------------------------------------------------
    @staticmethod
    def _where(flt: EventFilter) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if flt.start:
            clauses.append("ts >= ?")
            params.append(to_iso(flt.start))
        if flt.end:
            clauses.append("ts <= ?")
            params.append(to_iso(flt.end))
        if flt.categories:
            clauses.append(f"category IN ({','.join('?' * len(flt.categories))})")
            params += list(flt.categories)
        if flt.min_level:
            allowed = LEVELS[LEVELS.index(flt.min_level.upper()):]
            clauses.append(f"level IN ({','.join('?' * len(allowed))})")
            params += list(allowed)
        if flt.device_id is not None:
            clauses.append("device_id = ?")
            params.append(flt.device_id)
        if flt.text:
            clauses.append("(message LIKE ? ESCAPE '\\' OR action LIKE ? ESCAPE '\\')")
            like = "%" + flt.text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params += [like, like]
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    @staticmethod
    def _row(r: Any) -> EventRecord:
        return EventRecord(
            id=r["id"], ts=r["ts"], level=r["level"], category=r["category"], action=r["action"],
            message=r["message"], device_id=r["device_id"], job_id=r["job_id"], actor=r["actor"],
            details=json.loads(r["details_json"]) if r["details_json"] else None,
        )


def now_iso() -> str:  # conveniência para camadas superiores
    return utc_now_iso()
