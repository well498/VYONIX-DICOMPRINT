"""Gestão de nós DICOM da organização (equipamentos, estações e PACS remotos).

Referência de maturidade: o modelo de "Application Entities" de arquivos PACS corporativos (dispositivo, AE Title,
conexões, serviços aceitos, AE Titles de origem aceitos). Implementação própria do VYONIX, sem código de terceiros.

* **Cadastro:** identificação, fabricante, modelo, modalidade, unidade (clínica) da organização, AE Title, IP ou nome
  de máquina, porta e os serviços permitidos: enviar estudos (C-STORE ao PACS), consultar (C-FIND de estudos e
  worklist, MPPS) e receber estudos (destino de C-MOVE/C-GET).
* **Status:** desativado, sem contato, falha no último C-ECHO ou ativo (contato recente).
* **Histórico de conexões:** associações aceitas e recusadas, recepções, C-ECHO — agrupadas por janela de 10 minutos.
* **Recepção só de equipamentos cadastrados** (configuração ``pacs/reception``): o que chega de AE Title desconhecido
  fica retido no motor, sem índice e sem acesso, até o administrador autorizar (indexar) ou descartar. Nada é
  excluído automaticamente.
* **Isolamento:** tudo por organização (row level security); um nó só alcança estudos da própria organização.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.db.base import utcnow
from vyonix.errors import Conflict, NotFound, ValidationFailed

AET_RE = re.compile(r"^[A-Z0-9 _\-.]{1,16}$")
HOST_RE = re.compile(r"^(?=.{1,64}$)[A-Za-z0-9]([A-Za-z0-9\-]{0,62}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9\-]{0,62}"
                     r"[A-Za-z0-9])?)*$")
MODALITY_RE = re.compile(r"^[A-Z]{2,8}$")
COALESCE = timedelta(minutes=10)
ACTIVE_WINDOW = timedelta(days=7)
SERVICES = ("association", "echo", "store", "find", "move", "get", "mwl", "mpps")
OUTCOMES = ("accepted", "rejected", "ok", "failed", "held")


def _aet(value: str) -> str:
    v = (value or "").strip().upper()
    if not AET_RE.match(v):
        raise ValidationFailed("AE Title inválido: até 16 caracteres (letras, números, espaço, _ - .).")
    return v


def _host(value: str | None) -> str | None:
    h = (value or "").strip()
    if not h:
        return None
    try:
        return str(ipaddress.ip_address(h))
    except ValueError:
        pass
    if not HOST_RE.match(h) or h.replace(".", "").isdigit():
        raise ValidationFailed("Endereço inválido: informe o IP (ex.: 192.168.0.20) ou o nome da máquina na rede.")
    return h.lower()


def _clip(v: str | None, n: int) -> str | None:
    return (v or "").strip()[:n] or None


def status(n) -> dict[str, str]:
    """Situação do nó para a tela: código e texto."""
    now = utcnow()
    if not n.enabled:
        return {"code": "disabled", "label": "Desativado"}
    if n.last_echo_ok is False and (n.last_seen_at is None or (n.last_echo_at and n.last_echo_at >= n.last_seen_at)):
        return {"code": "error", "label": "Falha no último teste (C-ECHO)"}
    seen = max([t for t in (n.last_seen_at, n.last_echo_at if n.last_echo_ok else None) if t], default=None)
    if seen is None:
        return {"code": "never", "label": "Sem contato ainda"}
    if now - seen > ACTIVE_WINDOW:
        return {"code": "idle", "label": "Sem contato há mais de 7 dias"}
    return {"code": "ok", "label": "Ativo"}


def out(n, sites: dict | None = None) -> dict[str, Any]:
    iso = lambda t: t.isoformat() if t else None  # noqa: E731
    return {"id": str(n.id), "ae_title": n.ae_title, "host": n.host, "port": n.port, "description": n.description,
            "name": n.name, "manufacturer": n.manufacturer, "model": n.model, "modality": n.modality,
            "site_id": str(n.site_id) if n.site_id else None,
            "site_name": (sites or {}).get(n.site_id) if n.site_id else None,
            "can_store": n.can_store, "can_query": n.can_query, "can_receive": n.can_receive, "enabled": n.enabled,
            "last_seen_at": iso(n.last_seen_at), "last_echo_at": iso(n.last_echo_at), "last_echo_ok": n.last_echo_ok,
            "last_error": n.last_error, "last_error_at": iso(n.last_error_at), "status": status(n),
            "row_version": n.row_version}


def _sites(s: Session) -> dict:
    from vyonix.tenancy.models import Site
    return {x.id: x.name for x in s.execute(select(Site)).scalars()}


def listing(s: Session) -> list[dict]:
    from vyonix.pacs.models import PacsDicomNode
    sites = _sites(s)
    return [out(n, sites) for n in s.execute(select(PacsDicomNode).order_by(PacsDicomNode.ae_title)).scalars()]


def get(s: Session, node_id: uuid.UUID):
    from vyonix.pacs.models import PacsDicomNode
    n = s.get(PacsDicomNode, node_id)
    if n is None:
        raise NotFound("Nó DICOM não encontrado.")
    return n


def _validate(s: Session, *, host, port, site_id, modality, can_store, can_query, can_receive) -> dict:
    h = _host(host)
    if port is not None and not 1 <= int(port) <= 65535:
        raise ValidationFailed("Porta inválida (1–65535).")
    if can_receive and (not h or not port):
        raise ValidationFailed("Para receber estudos (destino de C-MOVE/C-GET), informe o endereço e a porta.")
    if not (can_store or can_query or can_receive):
        raise ValidationFailed("Marque ao menos um serviço: enviar estudos, consultar ou receber estudos.")
    mod = (modality or "").strip().upper() or None
    if mod and not MODALITY_RE.match(mod):
        raise ValidationFailed("Modalidade inválida (código DICOM, ex.: CT, MR, CR, DX, US, MG).")
    sid = None
    if site_id:
        from vyonix.tenancy.models import Site
        sid = uuid.UUID(str(site_id))
        if s.get(Site, sid) is None:                    # RLS: unidade de outra organização não aparece
            raise ValidationFailed("Unidade não encontrada nesta organização.")
    return {"host": h, "port": int(port) if port else None, "site_id": sid, "modality": mod}


def add(s: Session, ae_title: str, *, host: str | None = None, port: int | None = None,
        description: str | None = None, name: str | None = None, manufacturer: str | None = None,
        model: str | None = None, modality: str | None = None, site_id=None, can_store: bool = False,
        can_query: bool = True, can_receive: bool = False, enabled: bool = True, actor: str, actor_id=None,
        ip=None) -> dict:
    from sqlalchemy.exc import IntegrityError
    from vyonix.pacs.models import PacsDicomNode
    aet = _aet(ae_title)
    v = _validate(s, host=host, port=port, site_id=site_id, modality=modality, can_store=can_store,
                  can_query=can_query, can_receive=can_receive)
    n = PacsDicomNode(ae_title=aet, description=_clip(description, 200), name=_clip(name, 120),
                      manufacturer=_clip(manufacturer, 80), model=_clip(model, 80), can_store=bool(can_store),
                      can_query=bool(can_query), can_receive=bool(can_receive), enabled=bool(enabled),
                      created_by=actor[:120], **v)
    try:
        with s.begin_nested():
            s.add(n)
            s.flush()
    except IntegrityError as exc:
        raise Conflict(f"Já existe um nó DICOM com o AE Title {aet} nesta organização.") from exc
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.node.add", target_type="dicom_node",
                 target_id=n.id, details={"ae_title": aet, "host": n.host, "port": n.port, "modality": n.modality,
                                          "site_id": str(n.site_id) if n.site_id else None,
                                          "can_store": n.can_store, "can_query": n.can_query,
                                          "can_receive": n.can_receive, "enabled": n.enabled})
    return out(n, _sites(s))


EDITABLE = ("ae_title", "host", "port", "description", "name", "manufacturer", "model", "modality", "site_id",
            "can_store", "can_query", "can_receive", "enabled")


def update(s: Session, node_id: uuid.UUID, changes: dict[str, Any], *, row_version: int | None = None, actor: str,
           actor_id=None, ip=None) -> dict:
    from sqlalchemy.exc import IntegrityError
    n = get(s, node_id)
    if row_version is not None and row_version != n.row_version:
        raise Conflict("O cadastro foi alterado por outra pessoa. Recarregue a tela e repita a alteração.")
    cur = {k: getattr(n, k) for k in EDITABLE}
    new = dict(cur, **{k: v for k, v in changes.items() if k in EDITABLE})
    new["ae_title"] = _aet(new["ae_title"])
    v = _validate(s, host=new["host"], port=new["port"], site_id=new["site_id"], modality=new["modality"],
                  can_store=new["can_store"], can_query=new["can_query"], can_receive=new["can_receive"])
    new.update(v, description=_clip(new["description"], 200), name=_clip(new["name"], 120),
               manufacturer=_clip(new["manufacturer"], 80), model=_clip(new["model"], 80))
    diff = {k: [str(cur[k]) if cur[k] is not None else None, str(new[k]) if new[k] is not None else None]
            for k in EDITABLE if cur[k] != new[k]}
    if not diff:
        return out(n, _sites(s))
    for k in diff:
        setattr(n, k, new[k])
    try:
        with s.begin_nested():
            s.flush()
    except IntegrityError as exc:
        raise Conflict(f"Já existe um nó DICOM com o AE Title {new['ae_title']} nesta organização.") from exc
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.node.update", target_type="dicom_node",
                 target_id=n.id, details={"ae_title": n.ae_title, "changes": diff})
    return out(n, _sites(s))


def remove(s: Session, node_id: uuid.UUID, *, actor: str, actor_id=None, ip=None) -> None:
    n = get(s, node_id)
    aet = n.ae_title
    s.delete(n)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.node.remove", target_type="dicom_node",
                 target_id=node_id, details={"ae_title": aet})


def _address_matches(host: str, address: str | None) -> bool:
    if not address:
        return True
    try:
        return ipaddress.ip_address(host) == ipaddress.ip_address(address)
    except ValueError:
        pass
    try:                                         # nome de máquina: confere com os endereços resolvidos agora
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return any(i[4][0] == address for i in infos)


def find(s: Session, ae_title: str | None, *, address: str | None = None, service: str = "query"):
    """Nó ativo da organização com o AE Title e o serviço pedido (``store``, ``query`` ou ``receive``).

    Para os serviços de entrada (``store`` e ``query``), se o nó tiver endereço cadastrado, o endereço da associação
    precisa conferir."""
    from vyonix.pacs.models import PacsDicomNode
    n = s.execute(select(PacsDicomNode).where(PacsDicomNode.ae_title == (ae_title or "").strip().upper())
                  ).scalar_one_or_none()
    if n is None or not n.enabled:
        return None
    if not {"store": n.can_store, "query": n.can_query, "receive": n.can_receive}[service]:
        return None
    if service in ("store", "query") and n.host and not _address_matches(n.host, address):
        return None
    return n


def refusal_reason(s: Session, ae_title: str | None, *, address: str | None, service: str) -> str:
    """Motivo legível de um AE não ter sido aceito para o serviço (para o histórico e a tela de retidos)."""
    from vyonix.pacs.models import PacsDicomNode
    if not (ae_title or "").strip():
        return "Origem sem AE Title"
    n = s.execute(select(PacsDicomNode).where(PacsDicomNode.ae_title == ae_title.strip().upper())).scalar_one_or_none()
    if n is None:
        return "AE Title não cadastrado"
    if not n.enabled:
        return "Equipamento desativado"
    label = {"store": "enviar estudos", "query": "consultar", "receive": "receber estudos"}[service]
    if not {"store": n.can_store, "query": n.can_query, "receive": n.can_receive}[service]:
        return f"Equipamento sem permissão para {label}"
    return "Endereço de origem diferente do cadastrado"


# --------------------------------------------------------------------------- histórico de conexões

def record(s: Session, *, direction: str, service: str, outcome: str, calling_ae: str | None = None,
           called_ae: str | None = None, address: str | None = None, detail: str | None = None, node=None,
           count: int = 1) -> None:
    """Registra (ou agrupa) um evento de conexão DICOM. Também atualiza o último contato/erro do nó."""
    from vyonix.pacs.models import PacsDicomEvent, PacsDicomNode
    assert direction in ("in", "out") and service in SERVICES and outcome in OUTCOMES
    now = utcnow()
    calling = _clip((calling_ae or "").upper(), 16)
    called = _clip((called_ae or "").upper(), 16)
    det = _clip(detail, 300)
    if node is None and calling and direction == "in":
        node = s.execute(select(PacsDicomNode).where(PacsDicomNode.ae_title == calling)).scalar_one_or_none()
    ev = s.execute(select(PacsDicomEvent).where(
        PacsDicomEvent.direction == direction, PacsDicomEvent.service == service, PacsDicomEvent.outcome == outcome,
        PacsDicomEvent.calling_ae.is_(None) if calling is None else PacsDicomEvent.calling_ae == calling,
        PacsDicomEvent.called_ae.is_(None) if called is None else PacsDicomEvent.called_ae == called,
        PacsDicomEvent.address.is_(None) if address is None else PacsDicomEvent.address == address,
        PacsDicomEvent.detail.is_(None) if det is None else PacsDicomEvent.detail == det,
        PacsDicomEvent.last_at >= now - COALESCE).order_by(PacsDicomEvent.last_at.desc()).limit(1)).scalar()
    if ev is not None:
        ev.count += count
        ev.last_at = now
    else:
        s.add(PacsDicomEvent(node_id=node.id if node is not None else None, direction=direction, service=service,
                             outcome=outcome, calling_ae=calling, called_ae=called, address=_clip(address, 64),
                             detail=det, count=count, last_at=now))
    if node is not None:
        if outcome in ("accepted", "ok") and direction == "in":
            node.last_seen_at = now
        if outcome in ("rejected", "failed", "held"):
            node.last_error, node.last_error_at = det or outcome, now
    s.flush()


def events(s: Session, *, node_id: uuid.UUID | None = None, outcome: str | None = None, limit: int = 100) -> list[dict]:
    from vyonix.pacs.models import PacsDicomEvent
    q = select(PacsDicomEvent)
    if node_id is not None:
        n = get(s, node_id)
        q = q.where((PacsDicomEvent.node_id == n.id) | (PacsDicomEvent.calling_ae == n.ae_title)
                    | (PacsDicomEvent.called_ae == n.ae_title))
    if outcome == "problems":
        q = q.where(PacsDicomEvent.outcome.in_(("rejected", "failed", "held")))
    elif outcome:
        q = q.where(PacsDicomEvent.outcome == outcome)
    rows = s.execute(q.order_by(PacsDicomEvent.last_at.desc()).limit(max(1, min(limit, 500)))).scalars()
    return [{"id": str(e.id), "first_at": e.created_at.isoformat(), "last_at": e.last_at.isoformat(),
             "direction": e.direction, "service": e.service, "outcome": e.outcome, "calling_ae": e.calling_ae,
             "called_ae": e.called_ae, "address": e.address, "detail": e.detail, "count": e.count,
             "node_id": str(e.node_id) if e.node_id else None} for e in rows]


# --------------------------------------------------------------------------- teste de associação (C-ECHO)

def echo(s: Session, node_id: uuid.UUID, *, calling_ae: str, actor: str, actor_id=None, ip=None,
         timeout: float = 8.0) -> dict:
    """C-ECHO do VYONIX para o nó (verificação de conectividade DICOM). Não envia dados de pacientes."""
    import time
    n = get(s, node_id)
    if not n.host or not n.port:
        raise ValidationFailed("Informe o endereço e a porta do equipamento para testar a conexão (C-ECHO).")
    t0 = time.monotonic()
    ok, detail = _c_echo(n.host, n.port, n.ae_title, calling_ae, timeout)
    ms = int((time.monotonic() - t0) * 1000)
    now = utcnow()
    n.last_echo_at, n.last_echo_ok = now, ok
    if not ok:
        n.last_error, n.last_error_at = detail[:300], now
    record(s, direction="out", service="echo", outcome="ok" if ok else "failed", calling_ae=calling_ae,
           called_ae=n.ae_title, address=f"{n.host}:{n.port}", detail=None if ok else detail, node=n)
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.node.echo", target_type="dicom_node",
                 target_id=n.id, details={"ae_title": n.ae_title, "ok": ok, "ms": ms,
                                          **({} if ok else {"detail": detail[:300]})})
    return {"ok": ok, "ms": ms, "detail": detail, "node": out(n, _sites(s))}


def _c_echo(host: str, port: int, called: str, calling: str, timeout: float) -> tuple[bool, str]:
    from pynetdicom import AE
    ae = AE(ae_title=(calling or "VYONIX_QR")[:16])
    ae.acse_timeout = ae.dimse_timeout = ae.network_timeout = timeout
    ae.add_requested_context("1.2.840.10008.1.1")
    try:
        assoc = ae.associate(host, int(port), ae_title=called)
    except Exception as exc:  # noqa: BLE001 - resolução de nome, rede
        return False, f"Não foi possível conectar: {exc}"
    if assoc.is_rejected:
        return False, "O equipamento recusou a associação (confira o AE Title do VYONIX cadastrado nele)."
    if assoc.is_aborted:
        return False, "A associação foi interrompida pelo equipamento."
    if not assoc.is_established:
        return False, f"Sem resposta DICOM em {host}:{port} (equipamento desligado, porta errada ou firewall)."
    try:
        st = assoc.send_c_echo()
    finally:
        assoc.release()
    if st and getattr(st, "Status", None) == 0x0000:
        return True, "Conexão DICOM verificada (C-ECHO bem-sucedido)."
    return False, "O equipamento respondeu ao C-ECHO com erro."


# --------------------------------------------------------------------------- recepção de equipamentos não autorizados

def reception_policy(s: Session) -> str:
    from vyonix.settings import service as settings
    try:
        return settings.get(s, "pacs", "reception").get("store_policy", "any")
    except Exception:  # noqa: BLE001 - configuração ausente: comportamento atual (aceita)
        return "any"


def hold(s: Session, *, backend: str, backend_id: str, remote_aet: str | None, remote_ip: str | None,
         called_aet: str | None, reason: str) -> None:
    from vyonix.pacs.models import PacsStoreHold
    if s.execute(select(PacsStoreHold.id).where(PacsStoreHold.backend == backend,
                                                PacsStoreHold.backend_id == backend_id)).first():
        return
    s.add(PacsStoreHold(backend=backend, backend_id=backend_id, remote_aet=_clip(remote_aet, 16),
                        remote_ip=_clip(remote_ip, 64), called_aet=_clip(called_aet, 16), reason=reason[:200],
                        status="held"))
    record(s, direction="in", service="store", outcome="held", calling_ae=remote_aet, called_ae=called_aet,
           address=remote_ip, detail=reason)


def holds(s: Session, *, status: str = "held", limit: int = 200) -> dict:
    from sqlalchemy import func
    from vyonix.pacs.models import PacsStoreHold
    q = select(PacsStoreHold.remote_aet, PacsStoreHold.remote_ip, PacsStoreHold.called_aet,
               PacsStoreHold.reason, func.count(), func.min(PacsStoreHold.created_at),
               func.max(PacsStoreHold.created_at)).where(PacsStoreHold.status == status).group_by(
        PacsStoreHold.remote_aet, PacsStoreHold.remote_ip, PacsStoreHold.called_aet, PacsStoreHold.reason)
    groups = [{"remote_aet": a, "remote_ip": i, "called_aet": c, "reason": r, "instances": n,
               "first_at": f.isoformat(), "last_at": last.isoformat()}
              for a, i, c, r, n, f, last in s.execute(q.order_by(func.max(PacsStoreHold.created_at).desc())
                                                       .limit(limit))]
    return {"groups": groups, "total": sum(g["instances"] for g in groups)}


def decide_holds(s: Session, backend, *, remote_aet: str | None, decision: str, note: str | None = None,
                 actor: str, actor_id=None, ip=None) -> dict:
    """Autoriza (indexa) ou descarta (remove do motor) as recepções retidas de um AE Title.

    Autorizar não cadastra o equipamento: para as próximas recepções serem aceitas, cadastre-o com "Enviar estudos"."""
    from vyonix.pacs import service as pacs
    from vyonix.pacs.models import PacsStoreHold
    if decision not in ("release", "discard"):
        raise ValidationFailed("Decisão inválida.")
    if decision == "discard" and not (note or "").strip():
        raise ValidationFailed("Informe o motivo do descarte (fica na auditoria).")
    aet = (remote_aet or "").strip().upper() or None
    rows = list(s.execute(select(PacsStoreHold).where(
        PacsStoreHold.status == "held",
        PacsStoreHold.remote_aet.is_(None) if aet is None else PacsStoreHold.remote_aet == aet)).scalars())
    if not rows:
        raise NotFound("Nenhuma recepção retida para este AE Title.")
    res = {"indexed": 0, "duplicates": 0, "rejected": 0, "discarded": 0, "missing": 0}
    now = utcnow()
    for h in rows:
        if decision == "release":
            try:
                with s.begin_nested():
                    r = pacs.ingest(s, backend, backend.fetch(h.backend_id), actor=f"dicom:{aet or '?'}", via="dimse")
                res["duplicates" if r.duplicate else "indexed"] += 1
            except FileNotFoundError:
                res["missing"] += 1
            except pacs.InstanceRejected:
                res["rejected"] += 1
            h.status = "released"
        else:
            try:
                backend.delete(h.backend_id)
            except FileNotFoundError:
                pass
            res["discarded"] += 1
            h.status = "discarded"
        h.decided_by, h.decided_at, h.decision_note = actor[:120], now, _clip(note, 300)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action=f"pacs.hold.{decision}", target_type="dicom_node",
                 details={"remote_aet": aet, "instances": len(rows), **res, "note": _clip(note, 300)})
    return res
