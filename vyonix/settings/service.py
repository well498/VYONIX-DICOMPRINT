"""Configurações por módulo, com esquema validado e histórico.

Valor efetivo = padrão do esquema ← valor da clínica ← valor da unidade (quando o item aceita
unidade). Cada alteração grava o valor anterior e o novo, quem alterou e o motivo, e publica
``core.setting.changed.v1``. ``row_version`` impede que duas pessoas sobrescrevam uma à outra.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.errors import Conflict, NotFound, ValidationFailed
from vyonix.events.bus import publish
from vyonix.modules.manifest import MANIFESTS, SettingSpec
from vyonix.settings.models import Setting, SettingHistory


def _spec(module: str, key: str) -> SettingSpec:
    m = MANIFESTS.get(module)
    spec = m.setting(key) if m else None
    if not spec:
        raise NotFound(f"Configuração desconhecida: {module}.{key}")
    return spec


def _row(s: Session, module: str, key: str, site_id: uuid.UUID | None) -> Setting | None:
    q = select(Setting).where(Setting.module == module, Setting.key == key)
    q = q.where(Setting.site_id == site_id) if site_id else q.where(Setting.site_id.is_(None))
    return s.execute(q).scalar_one_or_none()


def get(s: Session, module: str, key: str, site_id: uuid.UUID | None = None) -> dict[str, Any]:
    spec = _spec(module, key)
    value = spec.model().model_dump()
    tenant_row = _row(s, module, key, None)
    if tenant_row and isinstance(tenant_row.value, dict):
        value.update(tenant_row.value)
    if site_id and spec.scope == "site":
        site_row = _row(s, module, key, site_id)
        if site_row and isinstance(site_row.value, dict):
            value.update(site_row.value)
    return spec.model.model_validate(value).model_dump()


def describe(s: Session, module: str, key: str, site_id: uuid.UUID | None = None) -> dict[str, Any]:
    spec = _spec(module, key)
    row = _row(s, module, key, site_id)
    return {"module": module, "key": key, "description": spec.description, "scope": spec.scope,
            "schema": spec.model.model_json_schema(), "value": get(s, module, key, site_id),
            "row_version": row.row_version if row else 0}


def put(s: Session, module: str, key: str, value: dict[str, Any], *, actor: str, reason: str | None = None,
        site_id: uuid.UUID | None = None, expected_version: int | None = None, actor_id=None, ip=None) -> dict:
    spec = _spec(module, key)
    if site_id and spec.scope != "site":
        raise ValidationFailed("Esta configuração vale para toda a clínica (não por unidade).")
    try:
        clean = spec.model.model_validate(value).model_dump()
    except ValidationError as exc:
        raise ValidationFailed("Valores inválidos.", details={"errors": [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]}) from None
    row = _row(s, module, key, site_id)
    current = row.row_version if row else 0
    if expected_version is not None and expected_version != current:
        raise Conflict("A configuração foi alterada por outra pessoa. Recarregue e tente de novo.")
    old = row.value if row else None
    if old == clean:
        return clean
    if row is None:
        s.add(Setting(module=module, key=key, site_id=site_id, value=clean))
    else:
        row.value = clean
    s.add(SettingHistory(module=module, key=key, site_id=site_id, old_value=old, new_value=clean, actor=actor,
                         reason=reason))
    changed = sorted(k for k in clean if (old or {}).get(k) != clean[k])
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="settings.change", target_type="setting",
                 target_id=f"{module}.{key}", details={"fields": changed, "site_id": str(site_id) if site_id else None,
                                                     "reason": reason})
    publish(s, "core.setting.changed.v1", {"module": module, "key": key, "fields": changed}, source="core",
            subject_kind="setting", subject_id=f"{module}.{key}", site_id=site_id)
    s.flush()
    return clean


def history(s: Session, module: str, key: str, limit: int = 50) -> list[dict]:
    rows = s.execute(select(SettingHistory).where(SettingHistory.module == module, SettingHistory.key == key)
                     .order_by(SettingHistory.created_at.desc()).limit(limit)).scalars()
    return [{"at": r.created_at.isoformat(), "actor": r.actor, "reason": r.reason, "old": r.old_value,
             "new": r.new_value, "site_id": str(r.site_id) if r.site_id else None} for r in rows]
