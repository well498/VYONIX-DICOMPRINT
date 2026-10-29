"""Saúde detalhada da plataforma para o administrador da organização (monitoramento técnico).

Somente leitura. Cada componente informa o estado e, quando há problema, o motivo em linguagem simples:

* **banco**: consulta respondida;
* **eventos**: fila da outbox da organização — pendentes, o mais antigo e os que estão falhando. Fila parada indica
  o serviço VyonixWorker parado (sincronização do PACS, conciliações e worklist dependem dele);
* **PACS**: módulo, motor DICOM (versão ou erro), índice, e a última sincronização de C-STORE (modo edge);
* **consulta DICOM**: porta configurada e se está aceitando conexões;
* **licença**: módulos licenciados e situação;
* **backup do PACS** (quando configurado): resultado e idade do último backup automático;
* **espaço em disco**: pasta de dados da plataforma, armazenamento das imagens (motor DICOM) e pasta de backup —
  atenção abaixo de 10% livre ou 10 GB, falha abaixo de 5% livre ou 2 GB.

Não expõe dados de pacientes nem segredos.
"""

from __future__ import annotations

import socket
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from vyonix.db.base import utcnow

DISK_WARN_PCT, DISK_WARN_GB = 10.0, 10.0
DISK_FAIL_PCT, DISK_FAIL_GB = 5.0, 2.0
EVENTS_STALE_S = 300            # evento pendente há mais de 5 min: worker provavelmente parado
SYNC_STALE_S = 600


def _events(s: Session) -> dict[str, Any]:
    from vyonix.events.models import OutboxEvent
    pending = select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
    n = s.execute(select(func.count()).select_from(pending.subquery())).scalar() or 0
    oldest = s.execute(select(func.min(OutboxEvent.occurred_at)).where(OutboxEvent.published_at.is_(None))).scalar()
    failing = s.execute(select(func.count()).select_from(OutboxEvent).where(
        OutboxEvent.published_at.is_(None), OutboxEvent.attempts > 0)).scalar() or 0
    age = int((utcnow() - oldest).total_seconds()) if oldest else 0
    problems = []
    if n and age > EVENTS_STALE_S:
        problems.append(f"{n} evento(s) aguardando há {age // 60} min: confira se o serviço VyonixWorker está em execução.")
    if failing:
        problems.append(f"{failing} evento(s) com falha no processamento (veja os registros do VyonixWorker).")
    return {"pending": n, "oldest_pending_seconds": age, "failing": failing, "problems": problems}


def _pacs(plat, s: Session) -> dict[str, Any]:
    from vyonix.modules import registry
    from vyonix.pacs import backend_for
    from vyonix.pacs import service as pacs
    from vyonix.pacs.backend import BackendUnavailable
    from vyonix.pacs.models import PacsSyncState
    out: dict[str, Any] = {"enabled": registry.is_enabled(s, "pacs"), "problems": []}
    if not out["enabled"]:
        return out
    b = backend_for(plat)
    if b is None:
        out["engine"] = {"configured": False}
        out["problems"].append("Motor DICOM não configurado (ative o PACS pelo VYONIX DEPLOY).")
    else:
        try:
            info = b.ping()
            out["engine"] = {"configured": True, "reachable": True, "name": info.get("name"),
                             "version": info.get("version")}
        except BackendUnavailable as exc:
            out["engine"] = {"configured": True, "reachable": False}
            out["problems"].append(f"Motor DICOM sem resposta ({exc}): as imagens não podem ser abertas nem recebidas "
                                   "até ele voltar; a pesquisa continua funcionando.")
    out["index"] = pacs.stats(s)
    if plat.edge and b is not None:
        st = s.execute(select(PacsSyncState).where(PacsSyncState.backend == b.name)).scalar_one_or_none()
        if st is not None:
            age = int((utcnow() - st.updated_at).total_seconds())
            out["sync"] = {"last_seq": st.last_seq, "seconds_since_update": age}
    return out


def _qr(plat) -> dict[str, Any]:
    port = plat.cfg.extra.get("pacs_qr_port")
    if not port:
        return {"configured": False, "problems": []}
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=2):
            pass
        return {"configured": True, "port": int(port), "listening": True, "problems": []}
    except OSError:
        return {"configured": True, "port": int(port), "listening": False,
                "problems": [f"Consulta DICOM (porta {port}) não está aceitando conexões: reinicie o VYONIX Core."]}


BACKUP_STALE_H = 36


def _backup(plat) -> dict[str, Any]:
    from datetime import datetime
    from vyonix.pacs.backup_task import read_status
    dest = plat.cfg.extra.get("pacs_backup_dir")
    if not dest:
        return {"configured": False, "problems": []}
    st = read_status(dest)
    out: dict[str, Any] = {"configured": True, "problems": []}
    if st is None:
        out["problems"].append("Nenhum backup automático do PACS registrado ainda (confira o serviço VyonixWorker "
                               "e a pasta de backup).")
        return out
    out.update({k: st.get(k) for k in ("finished_at", "ok", "instances", "copied", "verified")})
    if not st.get("ok"):
        out["problems"].append(f"Último backup do PACS falhou: {st.get('error', 'motivo não registrado')}.")
    try:
        age_h = (datetime.now() - datetime.fromisoformat(st["finished_at"])).total_seconds() / 3600
        out["hours_since"] = round(age_h, 1)
        if age_h > BACKUP_STALE_H:
            out["problems"].append(f"Último backup do PACS há {int(age_h)} h (esperado: diário).")
    except (KeyError, ValueError, TypeError):
        pass
    return out


def _integrity(plat) -> dict[str, Any]:
    from vyonix.pacs.integrity_task import read_state
    st = read_state(plat)
    if st is None:
        return {"verified": False, "problems": []}
    fails = st.get("failures", [])
    out = {"verified": True, "rounds": st.get("rounds", 0), "last_run_at": st.get("last_run_at"),
           "failures": len(fails), "problems": []}
    if fails:
        out["problems"].append(f"{len(fails)} imagem(ns) do PACS com integridade violada ou ausente no motor "
                               "(veja a auditoria pacs.integrity.failure; recupere pelo backup).")
    return out


def _disk_paths(plat) -> dict[str, str]:
    """Pastas a vigiar: dados da plataforma, imagens do motor (configuração do Orthanc do DEPLOY) e backup."""
    import json
    from pathlib import Path
    paths = {"Dados da plataforma": str(plat.cfg.data_dir)}
    try:
        from vyonix.pacs.engine_host import CONFIG_NAME
        f = Path(plat.cfg.data_dir) / "pacs" / CONFIG_NAME
        if f.exists():
            paths["Imagens do PACS"] = json.loads(f.read_text(encoding="utf-8"))["StorageDirectory"]
    except Exception:  # noqa: BLE001 - sem motor local configurado
        pass
    if plat.cfg.extra.get("pacs_storage_dir"):
        paths["Imagens do PACS"] = str(plat.cfg.extra["pacs_storage_dir"])
    if plat.cfg.extra.get("pacs_backup_dir"):
        paths["Backup do PACS"] = str(plat.cfg.extra["pacs_backup_dir"])
    return paths


def disk_check(paths: dict[str, str], usage=None, exists=None) -> dict[str, Any]:
    """Espaço livre por pasta (agrupado por disco). ``usage`` permite testar sem depender do disco real."""
    import os
    import shutil
    usage = usage or shutil.disk_usage
    exists = exists or os.path.exists
    out: dict[str, Any] = {"volumes": [], "problems": [], "critical": False}
    seen: dict[tuple, dict] = {}
    for label, path in paths.items():
        p = path
        while p and not exists(p) and os.path.dirname(p) != p:
            p = os.path.dirname(p)                   # pasta ainda não criada: mede o disco onde ficará
        try:
            u = usage(p)
        except OSError:
            out["problems"].append(f"Não foi possível medir o espaço de “{label}” ({path}).")
            continue
        key = (u.total, u.free)
        if key in seen:
            seen[key]["labels"].append(label)
            continue
        free_gb, pct = u.free / 1024**3, (u.free / u.total * 100 if u.total else 0.0)
        vol = {"labels": [label], "path": path, "total_gb": round(u.total / 1024**3, 1), "free_gb": round(free_gb, 1),
               "free_pct": round(pct, 1), "level": "ok"}
        if pct < DISK_FAIL_PCT or free_gb < DISK_FAIL_GB:
            vol["level"] = "critical"
            out["critical"] = True
        elif pct < DISK_WARN_PCT or free_gb < DISK_WARN_GB:
            vol["level"] = "warn"
        seen[key] = vol
        out["volumes"].append(vol)
    for v in out["volumes"]:
        if v["level"] != "ok":
            what = " e ".join(v["labels"])
            out["problems"].append(
                f"{'Espaço crítico' if v['level'] == 'critical' else 'Pouco espaço'} em disco para {what}: "
                f"{v['free_gb']} GB livres ({v['free_pct']}%). "
                + ("A recepção de imagens e o banco podem parar; libere espaço ou amplie o disco agora."
                   if v["level"] == "critical" else "Planeje a ampliação do armazenamento."))
    return out


def _license(plat, s: Session) -> dict[str, Any]:
    st = plat.licensing.status(s)
    mods = {code: {"licensed": v.licensed, "state": v.state} for code, v in st.items() if v.licensed or code == "core"}
    problems = [] if st.get("core") and st["core"].licensed else ["Sem licença vigente do VYONIX Core."]
    return {"modules": mods, "problems": problems}


def health_detail(plat, s: Session) -> dict[str, Any]:
    comps: dict[str, Any] = {}
    try:
        s.execute(text("SELECT 1"))
        comps["database"] = {"ok": True, "problems": []}
    except Exception as exc:  # noqa: BLE001
        comps["database"] = {"ok": False, "problems": [f"Banco sem resposta: {type(exc).__name__}"]}
        return {"status": "falha", "components": comps, "problems": comps["database"]["problems"]}
    for name, fn in (("events", lambda: _events(s)), ("pacs", lambda: _pacs(plat, s)), ("dicom_qr", lambda: _qr(plat)),
                     ("pacs_backup", lambda: _backup(plat)), ("pacs_integrity", lambda: _integrity(plat)),
                     ("license", lambda: _license(plat, s)), ("disk", lambda: disk_check(_disk_paths(plat)))):
        try:
            comps[name] = fn()
        except Exception as exc:  # noqa: BLE001 - um componente com erro não esconde os demais
            comps[name] = {"problems": [f"Não foi possível verificar ({type(exc).__name__})."]}
    problems = [p for c in comps.values() for p in c.get("problems", [])]
    fail = (comps.get("pacs", {}).get("engine", {}).get("reachable") is False
            or not comps.get("license", {}).get("modules", {}).get("core", {}).get("licensed", True)
            or bool(comps.get("pacs_integrity", {}).get("failures"))
            or bool(comps.get("disk", {}).get("critical")))
    status = "falha" if fail else ("atenção" if problems else "ok")
    return {"status": status, "checked_at": utcnow().isoformat(), "components": comps, "problems": problems}
