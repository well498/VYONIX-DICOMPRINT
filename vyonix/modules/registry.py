"""Registro de módulos: estado por clínica e regras de habilitação.

Habilitar exige: módulo entregue (``available``), dependências habilitadas e — se o módulo exigir —
licença vigente para ele. Desabilitar é recusado enquanto outro módulo habilitado depender dele.
Desabilitar nunca apaga dados.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.db.base import utcnow
from vyonix.errors import Conflict, NotFound, NotLicensed, ValidationFailed
from vyonix.events.bus import publish
from vyonix.modules.manifest import MANIFESTS, ModuleManifest
from vyonix.modules.models import ModuleState

LicenseCheck = Callable[[Session, str], tuple[bool, str]]


def manifest(code: str) -> ModuleManifest:
    m = MANIFESTS.get(code)
    if not m:
        raise NotFound(f"Módulo desconhecido: {code}")
    return m


def ensure_rows(s: Session) -> None:
    have = {r.code: r for r in s.execute(select(ModuleState)).scalars()}
    for m in MANIFESTS.values():
        r = have.get(m.code)
        if r is None:
            s.add(ModuleState(code=m.code, version=m.version, status="enabled" if m.always_enabled else "installed"))
        elif r.version != m.version:
            r.version = m.version
    s.flush()


def states(s: Session) -> dict[str, str]:
    return {r.code: r.status for r in s.execute(select(ModuleState)).scalars()}


def is_enabled(s: Session, code: str) -> bool:
    m = MANIFESTS.get(code)
    if m and m.always_enabled:
        return True
    return states(s).get(code) == "enabled"


def listing(s: Session, license_check: LicenseCheck) -> list[dict]:
    st = states(s)
    out = []
    for m in MANIFESTS.values():
        lic_ok, lic_msg = (True, "") if not m.requires_license else license_check(s, m.code)
        out.append({**m.public(), "status": "enabled" if m.always_enabled else st.get(m.code, "installed"),
                    "licensed": lic_ok, "license_message": lic_msg})
    return out


def enable(s: Session, code: str, *, actor: str, license_check: LicenseCheck, actor_id=None, ip=None) -> None:
    m = manifest(code)
    if not m.available:
        raise ValidationFailed(f"O módulo {m.name} ainda não está disponível nesta versão.")
    if m.always_enabled:
        return
    st = states(s)
    missing = [d for d in m.depends if not (MANIFESTS[d].always_enabled or st.get(d) == "enabled")]
    if missing:
        raise Conflict(f"Habilite antes: {', '.join(missing)}.", details={"missing": missing})
    if m.requires_license:
        ok, msg = license_check(s, code)
        if not ok:
            raise NotLicensed(msg or f"Sem licença vigente para {m.name}.")
    row = s.execute(select(ModuleState).where(ModuleState.code == code)).scalar_one()
    if row.status == "enabled":
        return
    row.status, row.changed_by, row.changed_at = "enabled", actor, utcnow()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="module.enable", target_type="module",
                 target_id=code)
    publish(s, "core.module.enabled.v1", {"module": code}, source="core", subject_kind="module", subject_id=code)


def disable(s: Session, code: str, *, actor: str, actor_id=None, ip=None, reason: str = "") -> None:
    m = manifest(code)
    if m.always_enabled:
        raise ValidationFailed(f"{m.name} não pode ser desabilitado.")
    st = states(s)
    dependents = [d.code for d in MANIFESTS.values() if code in d.depends and st.get(d.code) == "enabled"
                  and not d.always_enabled]
    if dependents:
        raise Conflict(f"Desabilite antes: {', '.join(dependents)}.", details={"dependents": dependents})
    row = s.execute(select(ModuleState).where(ModuleState.code == code)).scalar_one()
    if row.status != "enabled":
        return
    row.status, row.changed_by, row.changed_at = "disabled", actor, utcnow()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="module.disable", target_type="module",
                 target_id=code, details={"reason": reason})
    publish(s, "core.module.disabled.v1", {"module": code}, source="core", subject_kind="module", subject_id=code)
