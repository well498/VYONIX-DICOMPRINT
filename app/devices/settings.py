"""Configurações gerais de impressão de cada equipamento — independentes entre equipamentos.

Cada equipamento tem **o seu** registro (``device_settings``), nunca compartilhado: duas
tomografias podem usar papel, layout e calibração completamente diferentes. Valores ``None``
herdam do nível inferior da hierarquia (ver ``app.printing.resolver``). Toda gravação cria uma
nova versão em ``device_settings_versions`` (restauração e "reverter calibração").

Duplicar de outro equipamento copia os **valores** (cópia independente, sem referência).
"""

from __future__ import annotations

import json
from typing import Any, Callable

from app.core.errors import SettingsValidationError, ValidationError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.database.repositories.settings_repo import ChangeHistoryRepository
from app.imaging import tone
from app.printing.paper import PAPER_SIZES, parse_layout
from app.utils.timeutil import utc_now_iso

DICOM_POLICIES = {
    "device_first": "Configuração do equipamento prevalece sobre o pedido DICOM Print",
    "dicom_first": "Pedido DICOM Print prevalece (layout, orientação, cópias)",
    "ignore_dicom": "Ignorar parâmetros do pedido DICOM Print",
}

# chave → (rótulo, tipo)
FIELDS: dict[str, tuple[str, str]] = {
    "printer": ("Impressora", "printer"),
    "paper": ("Papel", "paper"),
    "orientation": ("Orientação", "orientation"),
    "layout": ("Layout", "layout"),
    "copies": ("Cópias", "int"),
    "margin_mm": ("Margens (mm)", "float"),
    "spacing_mm": ("Espaçamento entre imagens (mm)", "float"),
    "brightness": ("Brilho (−5 a +5)", "tone"),
    "contrast": ("Contraste (−5 a +5)", "tone"),
    "gamma": ("Gama (−5 a +5)", "tone"),
    "invert": ("Inverter escala de cinza", "bool"),
    "header_enabled": ("Cabeçalho (BMP)", "bool"),
    "footer_enabled": ("Rodapé (BMP)", "bool"),
    "extra_margin_mm": ("Margem adicional (mm)", "float"),
    "header_gap_mm": ("Espaço cabeçalho → imagens (mm)", "float"),
    "footer_gap_mm": ("Espaço imagens → rodapé (mm)", "float"),
    "auto_print": ("Impressão automática", "bool"),
    "dicom_policy": ("Prioridade do pedido DICOM Print", "policy"),
    "calibration_profile_id": ("Perfil de calibração da impressora", "profile"),
}
RANGES = {"copies": (1, 99), "margin_mm": (0, 40), "spacing_mm": (0, 20), "extra_margin_mm": (0, 30),
          "header_gap_mm": (0, 30), "footer_gap_mm": (0, 30)}
TONE_KEYS = ("brightness", "contrast", "gamma")


def validate_values(values: dict[str, Any], profile_exists: Callable[[int], bool] | None = None,
                    prefix: str = "") -> dict[str, Any]:
    """Valida e normaliza (remove ``None``). Usada também pelas ações das regras."""
    clean: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, val in (values or {}).items():
        if val is None or val == "":
            continue
        if key not in FIELDS:
            errors[prefix + key] = f"Configuração desconhecida: {key}."
            continue
        label, kind = FIELDS[key]
        try:
            if kind == "paper":
                if val not in PAPER_SIZES:
                    raise ValueError("papel inválido")
            elif kind == "orientation":
                if val not in ("auto", "portrait", "landscape"):
                    raise ValueError("orientação inválida")
            elif kind == "layout":
                r, c = parse_layout(str(val))
                val = f"{r}x{c}"
            elif kind == "bool":
                if not isinstance(val, bool):
                    raise ValueError("deve ser sim ou não")
            elif kind == "tone":
                val = float(val)
                if not tone.MIN <= val <= tone.MAX:
                    raise ValueError("deve estar entre −5,0 e +5,0")
                val = tone.snap(val)
            elif kind == "policy":
                if val not in DICOM_POLICIES:
                    raise ValueError("opção inválida")
            elif kind == "profile":
                val = int(val)
                if profile_exists and not profile_exists(val):
                    raise ValueError("perfil inexistente ou desativado")
            elif kind == "printer":
                val = str(val).strip()
                if len(val) > 256:
                    raise ValueError("nome longo demais")
            elif kind in ("int", "float"):
                val = int(val) if kind == "int" else round(float(val), 1)
                lo, hi = RANGES[key]
                if not lo <= val <= hi:
                    raise ValueError(f"deve estar entre {lo} e {hi}")
        except (ValueError, TypeError, ValidationError) as exc:
            errors[prefix + key] = f"{label}: {exc}"
            continue
        clean[key] = val
    if errors:
        raise SettingsValidationError(errors)
    return clean


class DeviceSettingsService:
    def __init__(self, db: Database, events: EventRepository,
                 profile_exists: Callable[[int], bool] | None = None) -> None:
        self.db = db
        self.events = events
        self.history = ChangeHistoryRepository(db)
        self.profile_exists = profile_exists

    # ------------------------------------------------------------------ consulta
    def get(self, device_id: int) -> dict[str, Any]:
        r = self.db.connection().execute("SELECT settings_json FROM device_settings WHERE device_id = ?",
                                         (device_id,)).fetchone()
        return json.loads(r["settings_json"]) if r else {}

    def version(self, device_id: int) -> int:
        r = self.db.connection().execute("SELECT version FROM device_settings WHERE device_id = ?",
                                         (device_id,)).fetchone()
        return int(r["version"]) if r else 0

    def versions(self, device_id: int) -> list[dict[str, Any]]:
        rows = self.db.connection().execute(
            "SELECT * FROM device_settings_versions WHERE device_id = ? ORDER BY version DESC", (device_id,))
        return [{**dict(r), "settings": json.loads(r["settings_json"])} for r in rows]

    def tone(self, device_id: int) -> tone.ToneControls:
        return tone.ToneControls.from_values(self.get(device_id))

    # ------------------------------------------------------------------ escrita
    def save(self, device_id: int, values: dict[str, Any], *, actor: str, reason: str | None = None,
             replace_all: bool = True) -> dict[str, Any]:
        """Grava (substitui) as configurações do equipamento e cria uma nova versão."""
        if self.db.connection().execute("SELECT 1 FROM devices WHERE id = ?", (device_id,)).fetchone() is None:
            raise ValidationError(f"Equipamento {device_id} não encontrado.")
        current = self.get(device_id)
        new = validate_values(values if replace_all else {**current, **values}, self.profile_exists)
        if new == current and self.version(device_id):
            return current
        now = utc_now_iso()
        version = self.version(device_id) + 1
        data = json.dumps(new, ensure_ascii=False, sort_keys=True)
        conn = self.db.connection()
        with self.db.transaction():
            conn.execute("""INSERT INTO device_settings(device_id, settings_json, version, updated_at, updated_by)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(device_id) DO UPDATE SET settings_json = excluded.settings_json,
                                version = excluded.version, updated_at = excluded.updated_at,
                                updated_by = excluded.updated_by""", (device_id, data, version, now, actor))
            conn.execute("""INSERT INTO device_settings_versions(device_id, version, settings_json, reason, actor,
                                created_at) VALUES (?, ?, ?, ?, ?, ?)""", (device_id, version, data, reason, actor, now))
            changed = sorted(k for k in set(current) | set(new) if current.get(k) != new.get(k))
            for k in changed:
                self.history.record(entity_type="device_settings", entity_id=str(device_id), field=k,
                                    old_value=current.get(k), new_value=new.get(k), actor=actor, reason=reason)
            self.events.add(level="INFO", category=Category.DEVICE, action="device.settings",
                            message=f"Configurações de impressão do equipamento #{device_id} salvas (versão {version}"
                                    + (f": {reason}" if reason else "") + ").", device_id=device_id, actor=actor,
                            details={"fields": changed})
        return new

    def save_tone(self, device_id: int, t: tone.ToneControls, *, actor: str, reason: str) -> dict[str, Any]:
        t.validate()
        return self.save(device_id, {**self.get(device_id), **t.to_json()}, actor=actor, reason=reason)

    def restore(self, device_id: int, version: int, *, actor: str) -> dict[str, Any]:
        r = self.db.connection().execute(
            "SELECT settings_json FROM device_settings_versions WHERE device_id = ? AND version = ?",
            (device_id, version)).fetchone()
        if r is None:
            raise ValidationError(f"Versão {version} não encontrada.")
        return self.save(device_id, json.loads(r["settings_json"]), actor=actor,
                         reason=f"restauração da versão {version}")

    def previous_tone_version(self, device_id: int) -> int | None:
        """Versão mais recente cuja calibração (brilho/contraste/gama/inversão) difere da atual."""
        cur = {k: self.get(device_id).get(k) for k in (*TONE_KEYS, "invert")}
        for v in self.versions(device_id)[1:]:
            if {k: v["settings"].get(k) for k in cur} != cur:
                return v["version"]
        return None

    def revert_calibration(self, device_id: int, *, actor: str) -> dict[str, Any]:
        version = self.previous_tone_version(device_id)
        if version is None:
            raise ValidationError("Não há calibração anterior diferente da atual para este equipamento.")
        old = self.versions(device_id)
        old_values = next(v["settings"] for v in old if v["version"] == version)
        merged = {**self.get(device_id)}
        for k in (*TONE_KEYS, "invert"):
            merged.pop(k, None)
            if k in old_values:
                merged[k] = old_values[k]
        return self.save(device_id, merged, actor=actor, reason=f"calibração revertida para a versão {version}")

    def copy_from(self, source_id: int, target_id: int, *, actor: str) -> dict[str, Any]:
        if source_id == target_id:
            raise ValidationError("Escolha outro equipamento como origem.")
        values = json.loads(json.dumps(self.get(source_id)))   # cópia profunda e independente
        return self.save(target_id, values, actor=actor, reason=f"duplicado do equipamento #{source_id}")

    def compare(self, a: int, b: int) -> list[tuple[str, Any, Any, bool]]:
        va, vb = self.get(a), self.get(b)
        return [(FIELDS[k][0], va.get(k), vb.get(k), va.get(k) != vb.get(k)) for k in FIELDS]
