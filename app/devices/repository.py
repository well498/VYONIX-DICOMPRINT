"""Persistência dos equipamentos (tabela ``devices``)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

from app.database.connection import Database
from app.utils.timeutil import utc_now_iso

EDITABLE = ("name", "manufacturer", "model", "modality", "ae_title", "ip_address", "port", "site",
            "department", "printer_id", "print_profile_id", "notes", "called_ae", "listen_port", "service")
ANY_AE = "*"            # restrição de Calling AE Title não definida (qualquer origem)


@dataclass
class Device:
    id: int | None
    name: str
    ae_title: str
    manufacturer: str | None = None
    model: str | None = None
    modality: str | None = None
    ip_address: str | None = None
    port: int | None = None
    site: str | None = None
    department: str | None = None
    printer_id: int | None = None
    print_profile_id: int | None = None
    authorized: bool = False
    active: bool = True
    comm_status: str | None = None
    notes: str | None = None
    last_seen_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    called_ae: str | None = None          # AE Title de destino (VYONIX) — seleciona a regra
    listen_port: int | None = None        # porta do VYONIX; None = porta padrão do serviço
    service: str = "store"                # store (C-STORE) | print (DICOM Print)

    @property
    def calling_restriction(self) -> str | None:
        return None if (self.ae_title or ANY_AE) == ANY_AE else self.ae_title

    def effective_port(self, default_port: int) -> int:
        return int(self.listen_port or default_port)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Any) -> "Device":
        keys = row.keys()
        data = {f.name: row[f.name] for f in fields(cls) if f.name in keys}
        data["authorized"] = bool(data["authorized"])
        data["active"] = bool(data["active"])
        data["service"] = data.get("service") or "store"
        return cls(**data)


class DeviceRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self, include_inactive: bool = False) -> list[Device]:
        sql = "SELECT * FROM devices"
        if not include_inactive:
            sql += " WHERE active = 1"
        sql += " ORDER BY name COLLATE NOCASE"
        return [Device.from_row(r) for r in self.db.connection().execute(sql)]

    def get(self, device_id: int) -> Device | None:
        row = self.db.connection().execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        return Device.from_row(row) if row else None

    def get_by_ae(self, ae_title: str) -> Device | None:
        row = self.db.connection().execute(
            "SELECT * FROM devices WHERE active = 1 AND ae_title = ?", (ae_title.strip(),)).fetchone()
        return Device.from_row(row) if row else None

    def find_by_ae(self, ae_title: str) -> list[Device]:
        rows = self.db.connection().execute(
            "SELECT * FROM devices WHERE active = 1 AND ae_title = ? ORDER BY id", (ae_title.strip(),)).fetchall()
        return [Device.from_row(r) for r in rows]

    def match(self, ae_title: str, address: str | None) -> tuple[Device | None, str | None]:
        """Identifica a origem por AE Title + IP. Retorna (equipamento, motivo do conflito)."""
        cands = self.find_by_ae(ae_title)
        if not cands:
            return None, None
        exact = [d for d in cands if d.ip_address and d.ip_address == address]
        if len(exact) == 1:
            return exact[0], None
        if len(cands) == 1:
            return cands[0], None
        no_ip = [d for d in cands if not d.ip_address]
        if len(no_ip) == 1:
            return no_ip[0], None
        return None, (f"conflito: o AE Title '{ae_title}' pertence a {len(cands)} equipamentos e nenhum está "
                      f"cadastrado com o IP {address}")

    def routes(self, service: str) -> list[Device]:
        """Regras DICOM ativas de um serviço (habilitadas ou não: a política informa o motivo)."""
        rows = self.db.connection().execute(
            "SELECT * FROM devices WHERE active = 1 AND service = ? ORDER BY id", (service,)).fetchall()
        return [Device.from_row(r) for r in rows]

    def authorized_ae_titles(self) -> list[str]:
        return [r[0] for r in self.db.connection().execute(
            "SELECT ae_title FROM devices WHERE active = 1 AND authorized = 1")]

    def insert(self, d: Device) -> int:
        now = utc_now_iso()
        cur = self.db.connection().execute(
            """INSERT INTO devices(name, manufacturer, model, modality, ae_title, ip_address, port,
                   site, department, printer_id, print_profile_id, authorized, active, notes,
                   created_at, updated_at, called_ae, listen_port, service)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
            (d.name, d.manufacturer, d.model, d.modality, d.ae_title or ANY_AE, d.ip_address, d.port, d.site,
             d.department, d.printer_id, d.print_profile_id, int(d.authorized), d.notes, now, now,
             d.called_ae, d.listen_port, d.service or "store"))
        return int(cur.lastrowid)

    def update_fields(self, device_id: int, values: dict[str, Any]) -> None:
        if not values:
            return
        cols = ", ".join(f"{k} = ?" for k in values)
        params = [int(v) if isinstance(v, bool) else v for v in values.values()]
        self.db.connection().execute(
            f"UPDATE devices SET {cols}, updated_at = ? WHERE id = ?",
            (*params, utc_now_iso(), device_id))

    def touch_seen(self, device_id: int, status: str) -> None:
        self.db.connection().execute(
            "UPDATE devices SET last_seen_at = ?, comm_status = ? WHERE id = ?",
            (utc_now_iso(), status, device_id))

    def set_status(self, device_id: int, status: str) -> None:
        self.db.connection().execute("UPDATE devices SET comm_status = ? WHERE id = ?",
                                     (status, device_id))

    def has_references(self, device_id: int) -> bool:
        conn = self.db.connection()
        for table in ("instances", "jobs"):
            if conn.execute(f"SELECT 1 FROM {table} WHERE device_id = ? LIMIT 1",
                            (device_id,)).fetchone():
                return True
        return False

    def delete(self, device_id: int) -> None:
        self.db.connection().execute("DELETE FROM devices WHERE id = ?", (device_id,))
