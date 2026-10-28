"""Saúde detalhada da plataforma para o administrador da organização (monitoramento técnico).

Somente leitura. Cada componente informa o estado e, quando há problema, o motivo em linguagem simples:

* **banco**: consulta respondida;
* **eventos**: fila da outbox da organização — pendentes, o mais antigo e os que estão falhando. Fila parada indica
  o serviço VyonixWorker parado (sincronização do PACS, conciliações e worklist dependem dele);
* **PACS**: módulo, motor DICOM (versão ou erro), índice, e a última sincronização de C-STORE (modo edge);
* **consulta DICOM**: porta configurada e se está aceitando conexões;
* **licença**: módulos licenciados e situação;
* **backup do PACS** (quando configurado): resultado e idade do último backup automático.

Não expõe dados de pacientes nem segredos.
"""

from __future__ import annotations

import socket
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from vyonix.db.base import utcnow

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
                     ("pacs_backup", lambda: _backup(plat)),
                     ("license", lambda: _license(plat, s))):
        try:
            comps[name] = fn()
        except Exception as exc:  # noqa: BLE001 - um componente com erro não esconde os demais
            comps[name] = {"problems": [f"Não foi possível verificar ({type(exc).__name__})."]}
    problems = [p for c in comps.values() for p in c.get("problems", [])]
    fail = (comps.get("pacs", {}).get("engine", {}).get("reachable") is False
            or not comps.get("license", {}).get("modules", {}).get("core", {}).get("licensed", True))
    status = "falha" if fail else ("atenção" if problems else "ok")
    return {"status": status, "checked_at": utcnow().isoformat(), "components": comps, "problems": problems}
