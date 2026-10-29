"""DICOMweb do VYONIX PACS (PS3.18): STOW-RS, QIDO-RS e WADO-RS, sob ``/api/v1/pacs/dicomweb``.

* Autenticação e anti-CSRF iguais ao restante da API (cookie de sessão; ``X-CSRF-Token`` no STOW).
* Toda consulta passa pelo índice da organização da sessão (row level security); o motor nunca é
  consultado por UID vindo do cliente.
* Entrada de estudos exige o módulo PACS habilitado e licença vigente. Pesquisa e recuperação de
  estudos já armazenados exigem só a permissão — a suspensão comercial não bloqueia dados clínicos
  existentes.
* Respostas de recuperação conferem o SHA-256 de cada instância com o registrado na entrada.
"""

from __future__ import annotations

import json
import secrets
from urllib.parse import quote
from typing import Iterable

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from vyonix.api.app import Ctx, needs
from vyonix.errors import NotLicensed, Unavailable, ValidationFailed
from vyonix.modules import registry
from vyonix.pacs import backend_for
from vyonix.pacs import service as pacs
from vyonix.pacs.backend import BackendUnavailable
from vyonix.pacs.dicom import DicomRejected
from vyonix.pacs.dicom import parse as parse_dicom

router = APIRouter(prefix="/pacs")
DW = "/dicomweb"
DICOM_JSON = "application/dicom+json"
STOW_MAX_BYTES = 1024 * 1024 * 1024          # 1 GB por requisição STOW nesta versão
QIDO_PARAMS = {"limit", "offset", "includefield", "fuzzymatching"}


def _backend(c: Ctx):
    b = backend_for(c.plat)
    if b is None:
        raise Unavailable("Armazenamento DICOM não configurado (pacs_orthanc_url).")
    return b


def _json(data, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, media_type=DICOM_JSON)


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/api/v1/pacs" + DW


# --------------------------------------------------------------------------- multipart/related

def _param(content_type: str, name: str) -> str | None:
    for part in content_type.split(";")[1:]:
        k, _, v = part.strip().partition("=")
        if k.strip().lower() == name:
            return v.strip().strip('"')
    return None


def parse_multipart(body: bytes, content_type: str) -> list[bytes]:
    """Partes ``application/dicom`` de um corpo ``multipart/related`` (RFC 2387)."""
    boundary = _param(content_type, "boundary")
    if not boundary:
        raise ValidationFailed("multipart/related sem boundary.")
    delim = b"--" + boundary.encode("latin-1")
    chunks = body.split(delim)
    if len(chunks) < 3:
        raise ValidationFailed("Corpo multipart vazio ou malformado.")
    parts = []
    for chunk in chunks[1:]:
        if chunk.startswith(b"--"):
            break                                            # delimitador final
        chunk = chunk[2:] if chunk.startswith(b"\r\n") else chunk
        head, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            raise ValidationFailed("Parte multipart sem cabeçalhos.")
        headers = {}
        for line in head.decode("latin-1").split("\r\n"):
            k, _, v = line.partition(":")
            if k:
                headers[k.strip().lower()] = v.strip()
        ctype = headers.get("content-type", "application/dicom").split(";")[0].strip().lower()
        if ctype != "application/dicom":
            raise ValidationFailed(f"Tipo de parte não aceito no STOW-RS desta versão: {ctype}.")
        parts.append(data[:-2] if data.endswith(b"\r\n") else data)
    return parts


def multipart(items: Iterable[bytes], media: str, *, transfer_syntax: str | None = None) -> tuple[bytes, str]:
    boundary = "vyx-" + secrets.token_hex(12)
    ptype = media + (f"; transfer-syntax={transfer_syntax}" if transfer_syntax else "")
    out = bytearray()
    for data in items:
        out += f"--{boundary}\r\nContent-Type: {ptype}\r\n\r\n".encode() + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f'multipart/related; type="{media}"; boundary={boundary}'


# --------------------------------------------------------------------------- STOW-RS

@router.post(DW + "/studies")
async def stow(request: Request, c: Ctx = Depends(needs("pacs.studies.store"))):
    return await _stow(request, c, None)


@router.post(DW + "/studies/{study_uid}")
async def stow_study(study_uid: str, request: Request, c: Ctx = Depends(needs("pacs.studies.store"))):
    return await _stow(request, c, study_uid)


async def _stow(request: Request, c: Ctx, only_study: str | None):
    declared = int(request.headers.get("content-length") or 0)
    if declared > STOW_MAX_BYTES:
        raise ValidationFailed("Requisição acima do limite do STOW-RS (1 GB). Envie em partes.")
    body = await request.body()
    if len(body) > STOW_MAX_BYTES:
        raise ValidationFailed("Requisição acima do limite do STOW-RS (1 GB). Envie em partes.")
    ctype = request.headers.get("content-type", "")
    main = ctype.split(";")[0].strip().lower()
    if main == "multipart/related":
        parts = parse_multipart(body, ctype)
    elif main == "application/dicom":
        parts = [body]
    else:
        raise ValidationFailed("Use multipart/related; type=\"application/dicom\".")
    if not parts:
        raise ValidationFailed("Nenhuma instância enviada.")
    base = _base(request)
    return await run_in_threadpool(_stow_sync, c, parts, only_study, base)


def _stow_sync(c: Ctx, parts: list[bytes], only_study: str | None, base: str):
    backend = _backend(c)
    ok, failed, studies = [], [], set()
    with c.session() as s:
        if not registry.is_enabled(s, "pacs"):
            raise NotLicensed("O módulo VYONIX PACS não está habilitado nesta organização.", code="module_disabled")
        c.plat.licensing.require_module(s, "pacs")
        for data in parts:
            try:
                if only_study:
                    p, _ = parse_dicom(data)
                    if p.study_uid != only_study:
                        raise pacs.InstanceRejected("A instância é de outro estudo que o indicado na URL.",
                                                    failure=0xA900, sop_uid=p.sop_uid, sop_class_uid=p.sop_class_uid)
                r = pacs.ingest(s, backend, data, actor=c.p.username, actor_id=c.p.user_id, ip=c.ip, via="stow")
            except pacs.InstanceRejected as exc:
                failed.append(exc)
                continue
            except DicomRejected as exc:
                failed.append(pacs.InstanceRejected(str(exc), failure=pacs.FAIL_CANNOT_UNDERSTAND))
                continue
            except BackendUnavailable as exc:
                raise Unavailable(str(exc)) from exc
            studies.add(r.study_uid)
            ok.append(r)
    resp: dict = {}
    if len(studies) == 1:
        resp["00081190"] = {"vr": "UR", "Value": [f"{base}/studies/{next(iter(studies))}"]}
    if ok:
        resp["00081199"] = {"vr": "SQ", "Value": [{
            "00081150": {"vr": "UI", "Value": [r.sop_class_uid]},
            "00081155": {"vr": "UI", "Value": [r.sop_uid]},
            "00081190": {"vr": "UR", "Value": [f"{base}/studies/{r.study_uid}/series/{r.series_uid}"
                                               f"/instances/{r.sop_uid}"]},
            **({"00081196": {"vr": "US", "Value": [0xB007]}} if r.duplicate else {}),   # aviso: já existia
        } for r in ok]}
    if failed:
        resp["00081198"] = {"vr": "SQ", "Value": [{
            **({"00081150": {"vr": "UI", "Value": [f.sop_class_uid]}} if f.sop_class_uid else {}),
            **({"00081155": {"vr": "UI", "Value": [f.sop_uid]}} if f.sop_uid else {}),
            "00081197": {"vr": "US", "Value": [f.failure]},
        } for f in failed]}
    status = 200 if not failed else (202 if ok else 409)
    r = _json(resp, status)
    if failed:
        # Motivos legíveis (também na auditoria) fora do DICOM JSON, para não quebrar clientes estritos.
        r.headers["X-Vyonix-Failures"] = quote(json.dumps([str(f) for f in failed], ensure_ascii=False)[:4000])
    return r


# --------------------------------------------------------------------------- QIDO-RS

def _qido_params(request: Request) -> tuple[dict[str, str], int, int]:
    q = dict(request.query_params)
    try:
        limit = int(q.pop("limit", 100))
        offset = int(q.pop("offset", 0))
    except ValueError as exc:
        raise ValidationFailed("limit/offset inválidos.") from exc
    for k in QIDO_PARAMS:
        q.pop(k, None)
    return q, limit, offset


@router.get(DW + "/studies")
def qido_studies(request: Request, c: Ctx = Depends(needs("pacs.studies.read"))):
    params, limit, offset = _qido_params(request)
    with c.session() as s:
        out = pacs.search_studies(s, params, limit=limit, offset=offset)
    return _json(out) if out else Response(status_code=204)


@router.get(DW + "/studies/{study_uid}/series")
def qido_series(study_uid: str, request: Request, c: Ctx = Depends(needs("pacs.studies.read"))):
    params, _, _ = _qido_params(request)
    with c.session() as s:
        out = pacs.search_series(s, study_uid, params)
    return _json(out) if out else Response(status_code=204)


@router.get(DW + "/studies/{study_uid}/instances")
def qido_study_instances(study_uid: str, c: Ctx = Depends(needs("pacs.studies.read"))):
    with c.session() as s:
        out = pacs.search_instances(s, study_uid)
    return _json(out) if out else Response(status_code=204)


@router.get(DW + "/studies/{study_uid}/series/{series_uid}/instances")
def qido_instances(study_uid: str, series_uid: str, c: Ctx = Depends(needs("pacs.studies.read"))):
    with c.session() as s:
        out = pacs.search_instances(s, study_uid, series_uid)
    return _json(out) if out else Response(status_code=204)


# --------------------------------------------------------------------------- WADO-RS

def _wrap(fn):
    try:
        return fn()
    except BackendUnavailable as exc:
        raise Unavailable(str(exc)) from exc


@router.get(DW + "/studies/{study_uid}/metadata")
def wado_study_metadata(study_uid: str, request: Request, c: Ctx = Depends(needs("pacs.studies.read"))):
    b, base = _backend(c), _base(request)
    with c.session() as s:
        pacs.open_study(s, study_uid, actor=c.p.username, actor_id=c.p.user_id, ip=c.ip,
                        dedup_s=pacs.OPEN_DEDUP_S)
        out = _wrap(lambda: pacs.metadata(s, b, study_uid, base_url=base))
    return _json(out)


@router.get(DW + "/studies/{study_uid}/series/{series_uid}/metadata")
def wado_series_metadata(study_uid: str, series_uid: str, request: Request,
                         c: Ctx = Depends(needs("pacs.studies.read"))):
    b, base = _backend(c), _base(request)
    with c.session() as s:
        pacs.open_study(s, study_uid, actor=c.p.username, actor_id=c.p.user_id, ip=c.ip,
                        dedup_s=pacs.OPEN_DEDUP_S)
        out = _wrap(lambda: pacs.metadata(s, b, study_uid, series_uid, base_url=base))
    return _json(out)


@router.get(DW + "/studies/{study_uid}")
def wado_study(study_uid: str, c: Ctx = Depends(needs("pacs.studies.read"))):
    b = _backend(c)
    with c.session() as s:
        pacs.open_study(s, study_uid, actor=c.p.username, actor_id=c.p.user_id, ip=c.ip, purpose="retrieve")
        body, ctype = _wrap(lambda: multipart(list(pacs.retrieve_many(s, b, study_uid)), "application/dicom"))
    return Response(body, media_type=ctype)


@router.get(DW + "/studies/{study_uid}/series/{series_uid}")
def wado_series(study_uid: str, series_uid: str, c: Ctx = Depends(needs("pacs.studies.read"))):
    b = _backend(c)
    with c.session() as s:
        body, ctype = _wrap(lambda: multipart(list(pacs.retrieve_many(s, b, study_uid, series_uid)),
                                              "application/dicom"))
    return Response(body, media_type=ctype)


@router.get(DW + "/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}")
def wado_instance(study_uid: str, series_uid: str, sop_uid: str, c: Ctx = Depends(needs("pacs.studies.read"))):
    b = _backend(c)
    with c.session() as s:
        data = _wrap(lambda: pacs.retrieve_instance(s, b, study_uid, series_uid, sop_uid))
    body, ctype = multipart([data], "application/dicom")
    return Response(body, media_type=ctype)


@router.get(DW + "/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}/frames/{frame_list}")
def wado_frames(study_uid: str, series_uid: str, sop_uid: str, frame_list: str,
                c: Ctx = Depends(needs("pacs.studies.read"))):
    try:
        numbers = [int(x) for x in frame_list.split(",") if x.strip()]
    except ValueError as exc:
        raise ValidationFailed("Lista de frames inválida.") from exc
    b = _backend(c)
    with c.session() as s:
        media, ts, items = _wrap(lambda: pacs.frames(s, b, study_uid, series_uid, sop_uid, numbers))
    body, ctype = multipart(items, media, transfer_syntax=ts)
    return Response(body, media_type=ctype)


# --------------------------------------------------------------------------- qualidade

@router.get("/quality")
def quality_list(only_issues: bool = True, limit: int = 100, c: Ctx = Depends(needs("pacs.studies.read"))):
    with c.session() as s:
        return {"studies": pacs.quality_overview(s, limit=limit, only_issues=only_issues)}


@router.get("/studies/{study_uid}/quality")
def quality_study(study_uid: str, c: Ctx = Depends(needs("pacs.studies.read"))):
    with c.session() as s:
        return pacs.quality(s, study_uid)


# --------------------------------------------------------------------------- administração

class RouteIn(BaseModel):
    called_aet: str = Field(min_length=1, max_length=16)
    description: str | None = Field(None, max_length=200)


@router.get("/routes")
def list_routes(c: Ctx = Depends(needs("pacs.admin"))):
    with c.session() as s:
        return {"routes": pacs.routes(s), "mode": c.plat.cfg.mode}


@router.post("/routes", status_code=201)
def add_route(body: RouteIn, c: Ctx = Depends(needs("pacs.admin"))):
    with c.session() as s:
        return pacs.add_route(s, body.called_aet, description=body.description, **c.actor)


@router.delete("/routes/{route_id}", status_code=204)
def remove_route(route_id: uuid.UUID, c: Ctx = Depends(needs("pacs.admin"))):
    with c.session() as s:
        pacs.remove_route(s, route_id, **c.actor)
    return Response(status_code=204)


class NodeIn(BaseModel):
    ae_title: str = Field(min_length=1, max_length=16)
    host: str | None = Field(None, max_length=64)
    port: int | None = Field(None, ge=1, le=65535)
    description: str | None = Field(None, max_length=200)
    name: str | None = Field(None, max_length=120)
    manufacturer: str | None = Field(None, max_length=80)
    model: str | None = Field(None, max_length=80)
    modality: str | None = Field(None, max_length=16)
    site_id: uuid.UUID | None = None
    can_store: bool = False
    can_query: bool = True
    can_receive: bool = False
    enabled: bool = True


class NodePatch(BaseModel):
    ae_title: str | None = Field(None, min_length=1, max_length=16)
    host: str | None = Field(None, max_length=64)
    port: int | None = Field(None, ge=1, le=65535)
    description: str | None = Field(None, max_length=200)
    name: str | None = Field(None, max_length=120)
    manufacturer: str | None = Field(None, max_length=80)
    model: str | None = Field(None, max_length=80)
    modality: str | None = Field(None, max_length=16)
    site_id: uuid.UUID | None = None
    can_store: bool | None = None
    can_query: bool | None = None
    can_receive: bool | None = None
    enabled: bool | None = None
    row_version: int | None = None


def _qr(c: Ctx) -> dict:
    return {"port": c.plat.cfg.extra.get("pacs_qr_port"), "ae_title": c.plat.cfg.extra.get("pacs_qr_aet", "VYONIX_QR"),
            "store": {"port": c.plat.cfg.extra.get("pacs_dicom_port", 4242),
                      "ae_title": c.plat.cfg.extra.get("pacs_dicom_aet", "VYONIX_PACS")}}


@router.get("/nodes")
def list_nodes(c: Ctx = Depends(needs("pacs.admin"))):
    from vyonix.pacs import nodes as dnodes
    with c.session() as s:
        return {"nodes": pacs.nodes(s), "qr": _qr(c), "policy": dnodes.reception_policy(s),
                "held": dnodes.holds(s)["total"]}


@router.post("/nodes", status_code=201)
def add_node(body: NodeIn, c: Ctx = Depends(needs("pacs.admin"))):
    with c.session() as s:
        return pacs.add_node(s, body.ae_title, **body.model_dump(exclude={"ae_title"}), **c.actor)


@router.patch("/nodes/{node_id}")
def update_node(node_id: uuid.UUID, body: NodePatch, c: Ctx = Depends(needs("pacs.admin"))):
    from vyonix.pacs import nodes as dnodes
    ch = body.model_dump(exclude_unset=True)
    rv = ch.pop("row_version", None)
    with c.session() as s:
        return dnodes.update(s, node_id, ch, row_version=rv, **c.actor)


@router.delete("/nodes/{node_id}", status_code=204)
def remove_node(node_id: uuid.UUID, c: Ctx = Depends(needs("pacs.admin"))):
    with c.session() as s:
        pacs.remove_node(s, node_id, **c.actor)
    return Response(status_code=204)


@router.post("/nodes/{node_id}/echo")
async def echo_node(node_id: uuid.UUID, c: Ctx = Depends(needs("pacs.admin"))):
    """Teste de associação DICOM (C-ECHO) do VYONIX para o equipamento."""
    from vyonix.pacs import nodes as dnodes

    def run():
        with c.session() as s:
            return dnodes.echo(s, node_id, calling_ae=_qr(c)["ae_title"], **c.actor)
    return await run_in_threadpool(run)


@router.get("/nodes/{node_id}/events")
def node_events(node_id: uuid.UUID, c: Ctx = Depends(needs("pacs.admin"))):
    from vyonix.pacs import nodes as dnodes
    with c.session() as s:
        return {"items": dnodes.events(s, node_id=node_id, limit=100)}


@router.get("/dicom-events")
def dicom_events(outcome: str | None = None, limit: int = 100, c: Ctx = Depends(needs("pacs.admin"))):
    from vyonix.pacs import nodes as dnodes
    with c.session() as s:
        return {"items": dnodes.events(s, outcome=outcome, limit=limit)}


@router.get("/holds")
def list_holds(c: Ctx = Depends(needs("pacs.admin"))):
    from vyonix.pacs import nodes as dnodes
    with c.session() as s:
        return dnodes.holds(s)


class HoldDecisionIn(BaseModel):
    remote_aet: str | None = Field(None, max_length=16)
    decision: str = Field(pattern=r"^(release|discard)$")
    note: str | None = Field(None, max_length=300)


@router.post("/holds/decide")
def decide_holds(body: HoldDecisionIn, c: Ctx = Depends(needs("pacs.admin"))):
    from vyonix.pacs import nodes as dnodes
    b = _backend(c)
    with c.session() as s:
        if body.decision == "release":
            c.plat.licensing.require_module(s, "pacs")
        return _wrap(lambda: dnodes.decide_holds(s, b, remote_aet=body.remote_aet, decision=body.decision,
                                                 note=body.note, **c.actor))


class ForwardRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    destination_node_id: uuid.UUID
    source: str | None = Field(None, max_length=16)
    modality: str | None = Field(None, max_length=16)
    enabled: bool = True


@router.get("/forward-rules")
def forward_rules(c: Ctx = Depends(needs("pacs.admin"))):
    from vyonix.pacs import forward
    with c.session() as s:
        return {"items": forward.rules(s), "jobs": forward.jobs(s, limit=50)}


@router.post("/forward-rules", status_code=201)
def add_forward_rule(body: ForwardRuleIn, c: Ctx = Depends(needs("pacs.admin"))):
    from vyonix.pacs import forward
    with c.session() as s:
        return forward.save_rule(s, **body.model_dump(), **c.actor)


@router.put("/forward-rules/{rule_id}")
def update_forward_rule(rule_id: uuid.UUID, body: ForwardRuleIn, c: Ctx = Depends(needs("pacs.admin"))):
    from vyonix.pacs import forward
    with c.session() as s:
        return forward.save_rule(s, rule_id=rule_id, **body.model_dump(), **c.actor)


@router.delete("/forward-rules/{rule_id}", status_code=204)
def remove_forward_rule(rule_id: uuid.UUID, c: Ctx = Depends(needs("pacs.admin"))):
    from vyonix.pacs import forward
    with c.session() as s:
        forward.remove_rule(s, rule_id, **c.actor)
    return Response(status_code=204)


class ForwardIn(BaseModel):
    destination_node_id: uuid.UUID


@router.post("/studies/{study_uid}/forward", status_code=201)
def forward_study(study_uid: str, body: ForwardIn, c: Ctx = Depends(needs("pacs.admin"))):
    """Envia o estudo a um nó cadastrado para receber (entra na fila do serviço; SHA-256 conferido)."""
    from vyonix.pacs import forward
    with c.session() as s:
        return forward.request(s, study_uid, body.destination_node_id, **c.actor)


@router.post("/forward-jobs/{job_id}/retry")
def retry_forward(job_id: uuid.UUID, c: Ctx = Depends(needs("pacs.admin"))):
    from vyonix.pacs import forward
    with c.session() as s:
        return forward.retry(s, job_id, **c.actor)


@router.get("/status")
def status(c: Ctx = Depends(needs("pacs.admin"))):
    b = backend_for(c.plat)
    engine: dict = {"configured": b is not None}
    if b is not None:
        try:
            engine.update(b.ping(), reachable=True)
        except BackendUnavailable as exc:
            engine.update(reachable=False, message=str(exc))
    with c.session() as s:
        return {"engine": engine, "index": pacs.stats(s), "enabled": registry.is_enabled(s, "pacs")}


@router.post("/sync")
def sync(c: Ctx = Depends(needs("pacs.admin"))):
    if not c.plat.edge:
        # No modo cloud o motor é compartilhado: a distribuição às organizações é feita pelo VyonixWorker, pelas
        # rotas de AE Title (/pacs/routes), nunca por uma organização puxando tudo para si.
        raise ValidationFailed("No modo cloud, os recebimentos por C-STORE são distribuídos automaticamente pelas "
                               "rotas de AE Title da organização (Rotas DICOM).")
    b = _backend(c)
    with c.session() as s:
        if not registry.is_enabled(s, "pacs"):
            raise NotLicensed("O módulo VYONIX PACS não está habilitado nesta organização.", code="module_disabled")
        c.plat.licensing.require_module(s, "pacs")
        return _wrap(lambda: pacs.sync(s, b))


# ------------------------------------------------------------------ retenção (relatório; nada é excluído)
class HoldIn(BaseModel):
    hold: bool
    reason: str | None = Field(None, max_length=300)


@router.get("/retention")
def retention_report(c: Ctx = Depends(needs("pacs.admin"))):
    from vyonix.pacs import retention
    with c.session() as s:
        return retention.report(s)


@router.post("/studies/{study_uid}/retention-hold")
def retention_hold(study_uid: str, body: HoldIn, c: Ctx = Depends(needs("pacs.admin"))):
    from vyonix.pacs import retention
    with c.session() as s:
        st = retention.set_hold(s, study_uid, body.hold, reason=body.reason, **c.actor)
        return {"study_uid": st.study_uid, "hold": st.retention_hold, "reason": st.retention_hold_reason}
