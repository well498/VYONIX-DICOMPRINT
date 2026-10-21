"""Cadastro de impressoras (tabela ``printers``) sobre os backends disponíveis.

* ``refresh()`` consulta o Windows e a impressora virtual VYONIX PDF e atualiza o banco; as
  impressoras que sumiram do Windows ficam marcadas como "não encontrada" (não são apagadas,
  pois trabalhos antigos as referenciam).
* ``resolve(name)`` decide a impressora de um trabalho: a pedida, a padrão do VYONIX ou a
  padrão do Windows — **nunca** cai silenciosamente para o PDF.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Callable

from app.core.contracts import PrinterBackend, PrinterInfo
from app.core.errors import ValidationError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.printing.backends.pdf import PDF_PRINTER
from app.utils.logging_setup import get_logger
from app.utils.timeutil import utc_now_iso

log = get_logger("printing")

NOT_FOUND = "não encontrada no Windows"


@dataclass
class PrinterRecord:
    id: int
    name: str
    driver: str
    backend: str
    port: str
    is_default: bool            # padrão do Windows
    is_vyonix_default: bool     # padrão do VYONIX (configuração printing.default_printer)
    paper_sizes: list[str]
    resolutions: list[int]
    color: bool | None
    status: str
    available: bool
    last_seen_at: str | None


class PrinterService:
    def __init__(self, db: Database, events: EventRepository, backends: list[PrinterBackend],
                 settings_get: Callable[[str], Any], backend_errors: dict[str, str] | None = None) -> None:
        self.db = db
        self.events = events
        self.backends = backends
        self.get = settings_get
        self.backend_errors = backend_errors or {}
        self._lock = threading.Lock()
        self._by_name: dict[str, PrinterBackend] = {}

    # ----------------------------------------------------------------- consulta
    def refresh(self) -> list[PrinterRecord]:
        infos: list[PrinterInfo] = []
        mapping: dict[str, PrinterBackend] = {}
        for backend in self.backends:
            try:
                found = backend.list_printers()
            except Exception as exc:  # noqa: BLE001
                log.exception("Falha ao listar impressoras (%s)", backend.name)
                self.backend_errors[backend.name] = str(exc)
                continue
            for info in found:
                infos.append(info)
                mapping[info.name] = backend
        now = utc_now_iso()
        conn = self.db.connection()
        with self._lock, self.db.transaction():
            self._by_name = mapping
            seen = set()
            for info in infos:
                caps = {"backend": info.backend, "port": info.port, "paper_sizes": list(info.paper_sizes),
                        "resolutions": list(info.resolutions_dpi), "color": info.supports_color,
                        "available": info.available}
                conn.execute(
                    """INSERT INTO printers(name, driver_name, is_default, capabilities_json, active, last_status,
                                            last_seen_at, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                       ON CONFLICT(name) DO UPDATE SET driver_name = excluded.driver_name,
                           is_default = excluded.is_default, capabilities_json = excluded.capabilities_json,
                           active = 1, last_status = excluded.last_status, last_seen_at = excluded.last_seen_at,
                           updated_at = excluded.updated_at""",
                    (info.name, info.driver, int(info.is_default), json.dumps(caps, ensure_ascii=False),
                     info.status_text, now, now, now))
                seen.add(info.name)
            for row in conn.execute("SELECT id, name FROM printers WHERE active = 1").fetchall():
                if row["name"] not in seen:
                    conn.execute("UPDATE printers SET last_status = ?, is_default = 0, updated_at = ? WHERE id = ?",
                                 (NOT_FOUND, now, row["id"]))
        return self.list()

    def list(self) -> list[PrinterRecord]:
        vy_default = self.get("printing.default_printer") or ""
        rows = self.db.connection().execute(
            "SELECT * FROM printers WHERE active = 1 ORDER BY is_default DESC, name COLLATE NOCASE").fetchall()
        result = []
        for r in rows:
            caps = json.loads(r["capabilities_json"] or "{}")
            available = r["last_status"] != NOT_FOUND and caps.get("available", True)
            result.append(PrinterRecord(
                id=r["id"], name=r["name"], driver=r["driver_name"] or "", backend=caps.get("backend", "windows"),
                port=caps.get("port", ""), is_default=bool(r["is_default"]), is_vyonix_default=r["name"] == vy_default,
                paper_sizes=caps.get("paper_sizes", []), resolutions=caps.get("resolutions", []),
                color=caps.get("color"), status=r["last_status"] or "", available=bool(available),
                last_seen_at=r["last_seen_at"]))
        return result

    def get_record(self, name: str) -> PrinterRecord | None:
        return next((p for p in self.list() if p.name == name), None)

    def printer_id(self, name: str) -> int | None:
        r = self.db.connection().execute("SELECT id FROM printers WHERE name = ?", (name,)).fetchone()
        return int(r["id"]) if r else None

    def backend_for(self, name: str) -> PrinterBackend:
        with self._lock:
            known = self._by_name.get(name)
        if known is None:
            self.refresh()
            with self._lock:
                known = self._by_name.get(name)
        if known is None:
            raise ValidationError(f"Impressora “{name}” não encontrada.")
        return known

    def resolve(self, requested: str | None) -> str:
        """Impressora efetiva de um trabalho (pedida > padrão do VYONIX > padrão do Windows)."""
        if requested:
            return requested
        vy = self.get("printing.default_printer")
        if vy:
            return vy
        for p in self.list() or self.refresh():
            if p.is_default and p.backend == "windows":
                return p.name
        raise ValidationError("Nenhuma impressora definida: escolha a impressora padrão do VYONIX na página "
                              "Impressoras (ou defina uma impressora padrão no Windows).")

    def set_vyonix_default(self, name: str, settings, *, actor: str) -> None:
        if name and self.get_record(name) is None:
            raise ValidationError(f"Impressora “{name}” não encontrada.")
        settings.update({"printing.default_printer": name}, actor=actor)

    def status_summary(self) -> str:
        n = len([p for p in self.list() if p.available])
        msg = f"{n} impressora(s) disponível(is)"
        if self.backend_errors:
            msg += " · " + "; ".join(f"{k}: {v}" for k, v in self.backend_errors.items())
        return msg


def is_pdf(name: str) -> bool:
    return name == PDF_PRINTER
