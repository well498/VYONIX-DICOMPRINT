"""Perfis de impressão (tabela ``print_profiles``) e suas associações (``profile_bindings``).

Um perfil reúne papel, orientação, layout, margens, cópias, anotações e calibração. Pode ser
associado a uma impressora, a um equipamento ou a uma modalidade (§7 itens 7–9). Toda alteração
é registrada no histórico.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import SettingsValidationError, ValidationError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.database.repositories.settings_repo import ChangeHistoryRepository
from app.imaging.calibration import CalibrationProfile
from app.security import validators as v
from app.utils.timeutil import utc_now_iso

SCOPES = ("printer", "device", "modality")
ORIENTATIONS = ("portrait", "landscape", "auto")


@dataclass
class PrintProfile:
    id: int | None
    name: str
    description: str | None = None
    paper_size: str | None = None
    orientation: str | None = None
    layout: str | None = None
    margins: dict[str, float] | None = None
    calibration: CalibrationProfile = field(default_factory=CalibrationProfile)
    copies: int | None = None
    annotations: dict[str, Any] | None = None
    active: bool = True
    updated_at: str | None = None

    @classmethod
    def from_row(cls, r) -> "PrintProfile":
        load = lambda s: json.loads(s) if s else None  # noqa: E731
        return cls(id=r["id"], name=r["name"], description=r["description"], paper_size=r["paper_size"],
                   orientation=r["orientation"], layout=r["layout"], margins=load(r["margins_json"]),
                   calibration=CalibrationProfile.from_json(load(r["calibration_json"])),
                   copies=r["copies"], annotations=load(r["annotations_json"]), active=bool(r["active"]),
                   updated_at=r["updated_at"])


class ProfileService:
    def __init__(self, db: Database, events: EventRepository) -> None:
        self.db = db
        self.events = events
        self.history = ChangeHistoryRepository(db)

    # ---------------------------------------------------------------- consulta
    def list(self, include_inactive: bool = False) -> list[PrintProfile]:
        sql = "SELECT * FROM print_profiles" + ("" if include_inactive else " WHERE active = 1")
        return [PrintProfile.from_row(r) for r in self.db.connection().execute(sql + " ORDER BY name COLLATE NOCASE")]

    def get(self, profile_id: int) -> PrintProfile:
        r = self.db.connection().execute("SELECT * FROM print_profiles WHERE id = ?", (profile_id,)).fetchone()
        if r is None:
            raise ValidationError(f"Perfil {profile_id} não encontrado.")
        return PrintProfile.from_row(r)

    def bindings(self, profile_id: int | None = None) -> list[dict[str, Any]]:
        sql = ("SELECT b.*, p.name AS profile_name FROM profile_bindings b "
               "JOIN print_profiles p ON p.id = b.profile_id")
        params: tuple = ()
        if profile_id is not None:
            sql += " WHERE b.profile_id = ?"
            params = (profile_id,)
        return [dict(r) for r in self.db.connection().execute(sql + " ORDER BY scope_type, scope_value", params)]

    def for_scope(self, scope_type: str, scope_value: str) -> PrintProfile | None:
        r = self.db.connection().execute(
            "SELECT p.* FROM profile_bindings b JOIN print_profiles p ON p.id = b.profile_id "
            "WHERE b.scope_type = ? AND b.scope_value = ? AND p.active = 1", (scope_type, str(scope_value))).fetchone()
        return PrintProfile.from_row(r) if r else None

    # ----------------------------------------------------------------- escrita
    def save(self, profile: PrintProfile, *, actor: str) -> PrintProfile:
        errors: dict[str, str] = {}
        try:
            name = v.free_text(80, "Nome")(profile.name)
            if not name:
                errors["name"] = "Informe um nome para o perfil."
        except ValidationError as exc:
            errors["name"] = str(exc)
            name = ""
        try:
            profile.calibration.validate()
        except ValidationError as exc:
            errors["calibration"] = str(exc)
        if profile.orientation and profile.orientation not in ORIENTATIONS:
            errors["orientation"] = "Orientação inválida."
        if profile.copies is not None and not 1 <= int(profile.copies) <= 99:
            errors["copies"] = "Cópias devem estar entre 1 e 99."
        dup = self.db.connection().execute("SELECT id FROM print_profiles WHERE name = ? AND id IS NOT ?",
                                           (name, profile.id)).fetchone()
        if dup:
            errors["name"] = "Já existe um perfil com este nome."
        if errors:
            raise SettingsValidationError(errors)
        now = utc_now_iso()
        values = (name, profile.description, profile.paper_size, profile.orientation, profile.layout,
                  json.dumps(profile.margins) if profile.margins else None,
                  json.dumps(profile.calibration.to_json()), profile.copies,
                  json.dumps(profile.annotations, ensure_ascii=False) if profile.annotations else None)
        conn = self.db.connection()
        with self.db.transaction():
            if profile.id is None:
                cur = conn.execute(
                    """INSERT INTO print_profiles(name, description, paper_size, orientation, layout, margins_json,
                           calibration_json, copies, annotations_json, active, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""", (*values, now, now))
                pid, old = int(cur.lastrowid), None
            else:
                old = self.get(profile.id)
                conn.execute(
                    """UPDATE print_profiles SET name=?, description=?, paper_size=?, orientation=?, layout=?,
                           margins_json=?, calibration_json=?, copies=?, annotations_json=?, updated_at=?
                       WHERE id = ?""", (*values, now, profile.id))
                pid = profile.id
            self.history.record(entity_type="print_profile", entity_id=str(pid), field="profile",
                                old_value=_summary(old) if old else None, new_value=_summary(profile), actor=actor)
            self.events.add(level="INFO", category=Category.ADMIN,
                            action="profile.create" if old is None else "profile.update",
                            message=f"Perfil de impressão \"{name}\" {'criado' if old is None else 'alterado'}.",
                            actor=actor)
        return self.get(pid)

    def bind(self, profile_id: int, scope_type: str, scope_value: str, *, actor: str) -> None:
        if scope_type not in SCOPES:
            raise ValidationError("Tipo de associação inválido.")
        p = self.get(profile_id)
        with self.db.transaction():
            self.db.connection().execute(
                """INSERT INTO profile_bindings(profile_id, scope_type, scope_value) VALUES (?, ?, ?)
                   ON CONFLICT(scope_type, scope_value) DO UPDATE SET profile_id = excluded.profile_id""",
                (profile_id, scope_type, str(scope_value)))
            self.history.record(entity_type="profile_binding", entity_id=f"{scope_type}:{scope_value}",
                                field="profile", old_value=None, new_value=p.name, actor=actor)
            self.events.add(level="INFO", category=Category.ADMIN, action="profile.bind",
                            message=f"Perfil \"{p.name}\" associado a {scope_type} {scope_value}.", actor=actor)

    def unbind(self, scope_type: str, scope_value: str, *, actor: str) -> None:
        with self.db.transaction():
            self.db.connection().execute("DELETE FROM profile_bindings WHERE scope_type = ? AND scope_value = ?",
                                         (scope_type, str(scope_value)))
            self.history.record(entity_type="profile_binding", entity_id=f"{scope_type}:{scope_value}",
                                field="profile", old_value="(associado)", new_value=None, actor=actor)

    def deactivate(self, profile_id: int, *, actor: str) -> None:
        p = self.get(profile_id)
        with self.db.transaction():
            self.db.connection().execute("UPDATE print_profiles SET active = 0, updated_at = ? WHERE id = ?",
                                         (utc_now_iso(), profile_id))
            self.db.connection().execute("DELETE FROM profile_bindings WHERE profile_id = ?", (profile_id,))
            self.history.record(entity_type="print_profile", entity_id=str(profile_id), field="active",
                                old_value=True, new_value=False, actor=actor)
            self.events.add(level="INFO", category=Category.ADMIN, action="profile.deactivate",
                            message=f"Perfil \"{p.name}\" desativado.", actor=actor)


def _summary(p: PrintProfile) -> dict[str, Any]:
    return {"name": p.name, "paper_size": p.paper_size, "orientation": p.orientation, "layout": p.layout,
            "copies": p.copies, "calibration": p.calibration.to_json()}
