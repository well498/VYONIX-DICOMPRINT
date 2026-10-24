"""Serviço do PACS: recepção, validação, armazenamento, indexação, pesquisa e recuperação.

Fluxo de entrada (STOW-RS ou sincronização de C-STORE recebido pelo motor):

1. ``dicom.parse`` valida o objeto (cabeçalho Part 10, UIDs, Patient ID) e calcula o SHA-256.
2. Se a organização já tem a instância: mesmo SHA-256 = reenvio idempotente; SHA-256 diferente =
   recusa (nunca sobrescreve uma instância já indexada).
3. O motor guarda o arquivo sem alterá-lo. Em seguida o arquivo é relido do motor e o SHA-256 é
   comparado — isso confirma a integridade do que ficou guardado e recusa o caso em que o motor
   (compartilhado entre organizações) já tinha outro conteúdo com os mesmos UIDs.
4. O índice (estudo, série, instância) é gravado no PostgreSQL da organização, com row level
   security. Estudo novo é registrado no cadastro clínico comum (``clinical.register_study``) e
   publica ``pacs.study.received.v1`` — sem dados do paciente no evento.
5. Toda entrada aceita ou recusada e toda abertura de estudo é auditada.

Pesquisa (QIDO-RS) e recuperação (WADO-RS) leem só o índice da organização da sessão; o motor nunca
é consultado por UID diretamente, então uma organização não alcança arquivos de outra.

Recuperação de dados já armazenados não depende de licença vigente (a suspensão comercial não pode
bloquear o acesso a dados clínicos existentes); a entrada de novos estudos depende.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterator

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.clinical import service as clinical
from vyonix.db.base import utcnow
from vyonix.errors import Conflict, NotFound, ValidationFailed
from vyonix.events.bus import publish
from vyonix.pacs import dicom
from vyonix.pacs.backend import PacsBackend
from vyonix.pacs.models import PacsInstance, PacsSeries, PacsStudy, PacsSyncState

IDENTIFIER_ISSUER_FALLBACK = "DICOM"
MAX_RESULTS = 500


@dataclass(frozen=True)
class StoreResult:
    sop_uid: str
    sop_class_uid: str
    study_uid: str
    series_uid: str
    instance_id: uuid.UUID
    study_id: uuid.UUID
    duplicate: bool
    new_study: bool


class InstanceRejected(ValueError):
    """Recusa de uma instância, com o código de falha DICOM (PS3.4, tabela GG.4-1 / PS3.18 STOW)."""

    def __init__(self, message: str, *, failure: int = 0xC000, sop_uid: str | None = None,
                 sop_class_uid: str | None = None) -> None:
        super().__init__(message)
        self.failure, self.sop_uid, self.sop_class_uid = failure, sop_uid, sop_class_uid


FAIL_PROCESSING = 0x0110          # falha de processamento
FAIL_CANNOT_UNDERSTAND = 0xC000   # não pôde ser entendida
FAIL_CONFLICT = 0xA770            # (específico do VYONIX) conflito com conteúdo já indexado


# --------------------------------------------------------------------------- entrada

def ingest(s: Session, backend: PacsBackend, data: bytes, *, actor: str, via: str = "stow",
           actor_id: uuid.UUID | None = None, ip: str | None = None) -> StoreResult:
    """Valida, guarda e indexa uma instância DICOM Part 10 na organização da sessão."""
    try:
        p, ds = dicom.parse(data)
    except dicom.DicomRejected as exc:
        audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.instance.reject", target_type="instance",
                     details={"reason": str(exc), "via": via, "size": len(data),
                              "sha256": hashlib.sha256(data).hexdigest()})
        raise InstanceRejected(str(exc), failure=FAIL_CANNOT_UNDERSTAND) from exc

    existing = s.execute(select(PacsInstance).where(PacsInstance.sop_uid == p.sop_uid)).scalar_one_or_none()
    if existing is not None:
        if existing.sha256 == p.sha256:
            st = s.get(PacsStudy, existing.study_id)
            return StoreResult(p.sop_uid, p.sop_class_uid, st.study_uid, p.series_uid, existing.id, st.id,
                               duplicate=True, new_study=False)
        reason = "SOP Instance UID já indexado com conteúdo diferente."
        _audit_reject(s, p, actor, actor_id, ip, via, reason)
        raise InstanceRejected(reason, failure=FAIL_CONFLICT, sop_uid=p.sop_uid, sop_class_uid=p.sop_class_uid)

    ref = backend.store(data)
    try:
        stored = backend.fetch(ref.backend_id)
        if hashlib.sha256(stored).hexdigest() != p.sha256:
            # O motor manteve outro conteúdo para estes UIDs (de outra organização ou anterior):
            # nada é indexado e o arquivo do motor não é tocado (already_existed).
            raise InstanceRejected("O armazenamento já contém outro conteúdo com estes UIDs; a instância "
                                   "não foi aceita.", failure=FAIL_CONFLICT, sop_uid=p.sop_uid,
                                   sop_class_uid=p.sop_class_uid)
        if ref.sop_uid and ref.sop_uid != p.sop_uid:
            raise InstanceRejected("O armazenamento devolveu outra instância.", failure=FAIL_PROCESSING,
                                   sop_uid=p.sop_uid, sop_class_uid=p.sop_class_uid)
        with s.begin_nested():               # índice parcial nunca fica gravado
            result = _index(s, p, ds, backend.name, ref.backend_id, via)
    except Exception as exc:
        if not ref.already_existed:
            try:
                backend.delete(ref.backend_id)    # desfaz só o que esta entrada acabou de criar
            except Exception:  # noqa: BLE001 - a falha original é a que importa
                pass
        if isinstance(exc, InstanceRejected):
            _audit_reject(s, p, actor, actor_id, ip, via, str(exc))
        raise

    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.instance.store", target_type="instance",
                 target_id=result.instance_id,
                 details={"via": via, "study_id": str(result.study_id), "sha256": p.sha256, "size": p.size,
                          "sop_class": p.sop_class_uid, "modality": p.modality, "new_study": result.new_study})
    if result.new_study:
        st = s.get(PacsStudy, result.study_id)
        publish(s, "pacs.study.received.v1",
                {"study_id": str(st.id), "clinical_study_id": str(st.clinical_study_id) if st.clinical_study_id else None,
                 "modality": p.modality, "via": via},
                source="pacs", subject_kind="study", subject_id=st.id)
    return result


def _audit_reject(s, p, actor, actor_id, ip, via, reason: str) -> None:
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.instance.reject", target_type="instance",
                 details={"reason": reason, "via": via, "sha256": p.sha256, "size": p.size})


def _index(s: Session, p: dicom.ParsedInstance, ds, backend_name: str, backend_id: str, via: str) -> StoreResult:
    st = s.execute(select(PacsStudy).where(PacsStudy.study_uid == p.study_uid)).scalar_one_or_none()
    new_study = st is None
    if new_study:
        st = PacsStudy(study_uid=p.study_uid, patient_id=p.patient_id, patient_name=p.patient_name)
        s.add(st)
    elif st.patient_id != p.patient_id:
        raise InstanceRejected("A instância pertence a outro paciente do que o estudo já indexado "
                               "(Patient ID diferente para o mesmo Study Instance UID).",
                               failure=FAIL_CONFLICT, sop_uid=p.sop_uid, sop_class_uid=p.sop_class_uid)
    st.patient_name = st.patient_name or p.patient_name
    st.patient_birth_date = st.patient_birth_date or p.patient_birth_date
    st.patient_sex = st.patient_sex or p.patient_sex
    st.study_date = st.study_date or p.study_date
    st.study_time = st.study_time or (p.study_time or "")[:16] or None
    st.accession = st.accession or (p.accession or "")[:32] or None
    st.description = st.description or (p.study_description or "")[:200] or None
    st.referring_physician = st.referring_physician or (p.referring_physician or "")[:200] or None
    st.dicom_study_id = st.dicom_study_id or (p.study_id or "")[:16] or None
    st.last_received_at = utcnow()
    s.flush()

    se = s.execute(select(PacsSeries).where(PacsSeries.series_uid == p.series_uid)).scalar_one_or_none()
    if se is None:
        se = PacsSeries(study_id=st.id, series_uid=p.series_uid, modality=(p.modality or "")[:16] or None,
                        series_number=p.series_number, description=(p.series_description or "")[:200] or None)
        s.add(se)
        s.flush()
    elif se.study_id != st.id:
        raise InstanceRejected("Series Instance UID já pertence a outro estudo.", failure=FAIL_CONFLICT,
                               sop_uid=p.sop_uid, sop_class_uid=p.sop_class_uid)

    it = PacsInstance(series_id=se.id, study_id=st.id, sop_uid=p.sop_uid, sop_class_uid=p.sop_class_uid,
                      transfer_syntax=p.transfer_syntax, instance_number=p.instance_number, rows=p.rows,
                      columns=p.columns, frames=p.frames, sha256=p.sha256, size_bytes=p.size,
                      backend=backend_name, backend_id=backend_id, received_via=via)
    s.add(it)
    s.flush()

    if st.clinical_study_id is None:
        issuer = _issuer(ds)
        cs = clinical.register_study(s, study_instance_uid=p.study_uid, accession=st.accession,
                                     modality=p.modality, study_date=p.study_date, description=st.description,
                                     patient_identifier=(issuer, p.patient_id), storage_location=f"pacs:{st.id.hex}",
                                     actor="pacs")
        st.clinical_study_id = cs.id
        s.flush()
    return StoreResult(p.sop_uid, p.sop_class_uid, p.study_uid, p.series_uid, it.id, st.id,
                       duplicate=False, new_study=new_study)


def _issuer(ds) -> str:
    v = str(ds.get("IssuerOfPatientID", "") or "").strip()
    return v[:60] or IDENTIFIER_ISSUER_FALLBACK


# --------------------------------------------------------------------------- sincronização (C-STORE)

def sync(s: Session, backend: PacsBackend, *, limit: int = 100, max_batches: int = 50) -> dict[str, int]:
    """Indexa as instâncias que chegaram ao motor por C-STORE desde a última sincronização.

    Só no modo edge (um servidor, uma organização): o motor não é multiorganização e um C-STORE não
    diz a qual organização pertence — a API recusa a sincronização no modo cloud. Instâncias recusadas
    são auditadas e não param a sincronização; o motor não é alterado por ela.
    """
    row = s.execute(select(PacsSyncState).where(PacsSyncState.backend == backend.name)).scalar_one_or_none()
    if row is None:
        row = PacsSyncState(backend=backend.name, last_seq=0)
        s.add(row)
        s.flush()
    out = {"indexed": 0, "duplicates": 0, "rejected": 0}
    for _ in range(max_batches):
        changes, last, done = backend.changes(row.last_seq, limit)
        for ch in changes:
            known = s.execute(select(PacsInstance.id).where(PacsInstance.backend == backend.name,
                                                            PacsInstance.backend_id == ch.backend_id)).first()
            if known:
                out["duplicates"] += 1
                continue
            try:
                with s.begin_nested():
                    r = ingest(s, backend, backend.fetch(ch.backend_id), actor="pacs-sync", via="dimse")
                out["duplicates" if r.duplicate else "indexed"] += 1
            except InstanceRejected:
                out["rejected"] += 1
            except FileNotFoundError:
                continue                       # removida do motor entre o evento e a leitura
        row.last_seq = last
        s.flush()
        if done:
            break
    return out


# --------------------------------------------------------------------------- pesquisa (QIDO-RS)

def _like(value: str) -> str:
    """Curinga DICOM (``*`` e ``?``) para LIKE, com escape dos caracteres especiais do SQL."""
    v = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return v.replace("*", "%").replace("?", "_")


def _date_range(value: str) -> tuple[date | None, date | None]:
    def one(t: str) -> date | None:
        t = t.strip()
        if not t:
            return None
        if len(t) != 8 or not t.isdigit():
            raise ValidationFailed("Data inválida (use AAAAMMDD ou AAAAMMDD-AAAAMMDD).")
        try:
            return date(int(t[:4]), int(t[4:6]), int(t[6:]))
        except ValueError as exc:
            raise ValidationFailed("Data inválida.") from exc
    if "-" in value:
        a, b = value.split("-", 1)
        return one(a), one(b)
    d = one(value)
    return d, d


def search_studies(s: Session, params: dict[str, str], *, limit: int = 100, offset: int = 0) -> list[dict]:
    q = select(PacsStudy)
    pid = params.get("PatientID") or params.get("00100020")
    if pid:
        q = q.where(PacsStudy.patient_id.like(_like(pid), escape="\\") if any(c in pid for c in "*?")
                    else PacsStudy.patient_id == pid)
    name = params.get("PatientName") or params.get("00100010")
    if name:
        pat = _like(name if any(c in name for c in "*?") else name + "*")
        q = q.where(PacsStudy.patient_name.ilike(pat, escape="\\"))
    acc = params.get("AccessionNumber") or params.get("00080050")
    if acc:
        q = q.where(PacsStudy.accession == acc)
    uid = params.get("StudyInstanceUID") or params.get("0020000D")
    if uid:
        q = q.where(PacsStudy.study_uid.in_([u.strip() for u in uid.split(",") if u.strip()]))
    sd = params.get("StudyDate") or params.get("00080020")
    if sd:
        a, b = _date_range(sd)
        if a:
            q = q.where(PacsStudy.study_date >= a)
        if b:
            q = q.where(PacsStudy.study_date <= b)
    desc = params.get("StudyDescription") or params.get("00081030")
    if desc:
        q = q.where(PacsStudy.description.ilike(_like(desc if "*" in desc else f"*{desc}*"), escape="\\"))
    mod = params.get("ModalitiesInStudy") or params.get("00080061")
    if mod:
        mods = [m.strip() for m in mod.split(",") if m.strip()]
        q = q.where(PacsStudy.id.in_(select(PacsSeries.study_id).where(PacsSeries.modality.in_(mods))))
    q = q.order_by(PacsStudy.study_date.desc().nulls_last(), PacsStudy.last_received_at.desc())
    q = q.limit(max(1, min(limit, MAX_RESULTS))).offset(max(0, offset))
    rows = list(s.execute(q).scalars())
    return [_study_out(s, st) for st in rows]


def _study_out(s: Session, st: PacsStudy) -> dict:
    mods = [m for (m,) in s.execute(select(PacsSeries.modality).where(PacsSeries.study_id == st.id).distinct())]
    n_series = s.execute(select(func.count()).select_from(PacsSeries).where(PacsSeries.study_id == st.id)).scalar()
    n_inst = s.execute(select(func.count()).select_from(PacsInstance).where(PacsInstance.study_id == st.id)).scalar()
    return dicom.study_json(st, mods, n_series, n_inst)


def study(s: Session, study_uid: str) -> PacsStudy:
    st = s.execute(select(PacsStudy).where(PacsStudy.study_uid == study_uid)).scalar_one_or_none()
    if st is None:
        raise NotFound("Estudo não encontrado.")
    return st


def search_series(s: Session, study_uid: str, params: dict[str, str] | None = None) -> list[dict]:
    st = study(s, study_uid)
    q = select(PacsSeries).where(PacsSeries.study_id == st.id)
    mod = (params or {}).get("Modality") or (params or {}).get("00080060")
    if mod:
        q = q.where(PacsSeries.modality == mod)
    out = []
    for se in s.execute(q.order_by(PacsSeries.series_number.nulls_last(), PacsSeries.created_at)).scalars():
        n = s.execute(select(func.count()).select_from(PacsInstance).where(PacsInstance.series_id == se.id)).scalar()
        out.append(dicom.series_json(se, st.study_uid, n))
    return out


def _instances_q(s: Session, study_uid: str, series_uid: str | None = None):
    st = study(s, study_uid)
    q = select(PacsInstance, PacsSeries).join(PacsSeries, PacsSeries.id == PacsInstance.series_id) \
        .where(PacsInstance.study_id == st.id)
    if series_uid:
        q = q.where(PacsSeries.series_uid == series_uid)
    return st, q.order_by(PacsSeries.series_number.nulls_last(), PacsInstance.instance_number.nulls_last(),
                          PacsInstance.created_at)


def search_instances(s: Session, study_uid: str, series_uid: str | None = None) -> list[dict]:
    st, q = _instances_q(s, study_uid, series_uid)
    rows = list(s.execute(q))
    if series_uid and not rows and not s.execute(select(PacsSeries.id).where(PacsSeries.series_uid == series_uid,
                                                                             PacsSeries.study_id == st.id)).first():
        raise NotFound("Série não encontrada.")
    return [dicom.instance_summary_json(it, st.study_uid, se.series_uid) for it, se in rows]


# --------------------------------------------------------------------------- recuperação (WADO-RS)

def _verified(backend: PacsBackend, it: PacsInstance) -> bytes:
    data = backend.fetch(it.backend_id)
    if hashlib.sha256(data).hexdigest() != it.sha256:
        raise Conflict("Integridade da instância não confere com o registro de entrada (SHA-256 diferente). "
                       "A instância não foi entregue; verifique o armazenamento.", code="integrity",
                       details={"sop_uid": it.sop_uid})
    return data


def instance(s: Session, study_uid: str, series_uid: str, sop_uid: str) -> PacsInstance:
    st = study(s, study_uid)
    row = s.execute(select(PacsInstance).join(PacsSeries, PacsSeries.id == PacsInstance.series_id)
                    .where(PacsInstance.study_id == st.id, PacsSeries.series_uid == series_uid,
                           PacsInstance.sop_uid == sop_uid)).scalar_one_or_none()
    if row is None:
        raise NotFound("Instância não encontrada.")
    return row


def retrieve_instance(s: Session, backend: PacsBackend, study_uid: str, series_uid: str, sop_uid: str) -> bytes:
    return _verified(backend, instance(s, study_uid, series_uid, sop_uid))


def retrieve_many(s: Session, backend: PacsBackend, study_uid: str, series_uid: str | None = None) -> Iterator[bytes]:
    _, q = _instances_q(s, study_uid, series_uid)
    for it, _se in list(s.execute(q)):
        yield _verified(backend, it)


def metadata(s: Session, backend: PacsBackend, study_uid: str, series_uid: str | None = None, *,
             base_url: str = "") -> list[dict]:
    """Metadados WADO-RS de cada instância (sem pixel; o pixel tem ``BulkDataURI`` para os frames)."""
    import pydicom
    st, q = _instances_q(s, study_uid, series_uid)
    out = []
    for it, se in list(s.execute(q)):
        ds = pydicom.dcmread(io.BytesIO(_verified(backend, it)), stop_before_pixels=False)
        j = dicom.instance_json(ds)
        if "7FE00010" in j and base_url:
            j["7FE00010"] = {"vr": j["7FE00010"].get("vr", "OW"),
                             "BulkDataURI": f"{base_url}/studies/{st.study_uid}/series/{se.series_uid}"
                                            f"/instances/{it.sop_uid}/frames/1"}
        j.setdefault("00083002", {"vr": "UI", "Value": [it.transfer_syntax]})   # Available Transfer Syntax UID
        out.append(j)
    return out


NATIVE_TS = {"1.2.840.10008.1.2", "1.2.840.10008.1.2.1", "1.2.840.10008.1.2.2", "1.2.840.10008.1.2.1.99"}
ENCAPSULATED_MEDIA = {
    "1.2.840.10008.1.2.4.50": "image/jpeg", "1.2.840.10008.1.2.4.51": "image/jpeg",
    "1.2.840.10008.1.2.4.57": "image/jpeg", "1.2.840.10008.1.2.4.70": "image/jpeg",
    "1.2.840.10008.1.2.4.80": "image/jls", "1.2.840.10008.1.2.4.81": "image/jls",
    "1.2.840.10008.1.2.4.90": "image/jp2", "1.2.840.10008.1.2.4.91": "image/jp2",
    "1.2.840.10008.1.2.5": "image/x-dicom-rle",
}


def frames(s: Session, backend: PacsBackend, study_uid: str, series_uid: str, sop_uid: str,
           numbers: list[int]) -> tuple[str, str, list[bytes]]:
    """Frames de uma instância como estão no arquivo (sem recompressão): (media type, transfer syntax, frames).

    Pixel nativo (sem compressão) sai como ``application/octet-stream`` em little endian explícito;
    pixel encapsulado sai no formato comprimido original (``image/jpeg``, ``image/jls``, ...).
    """
    import pydicom
    from pydicom.encaps import generate_frames
    it = instance(s, study_uid, series_uid, sop_uid)
    ds = pydicom.dcmread(io.BytesIO(_verified(backend, it)))
    if "PixelData" not in ds:
        raise NotFound("A instância não tem dados de imagem.")
    ts = it.transfer_syntax
    n = int(ds.get("NumberOfFrames", 1) or 1)
    bad = [k for k in numbers if k < 1 or k > n]
    if bad or not numbers:
        raise NotFound(f"Frame inexistente (a instância tem {n}).")
    if ts in NATIVE_TS:
        if ts == "1.2.840.10008.1.2.2":
            raise ValidationFailed("Big endian explícito ainda não é entregue em frames.")
        raw = ds.PixelData
        size = len(raw) // n
        return "application/octet-stream", "1.2.840.10008.1.2.1", [raw[(k - 1) * size:k * size] for k in numbers]
    media = ENCAPSULATED_MEDIA.get(ts)
    if media is None:
        raise ValidationFailed("Sintaxe de transferência sem entrega de frames nesta versão.",
                               details={"transfer_syntax": ts})
    all_frames = list(generate_frames(ds.PixelData, number_of_frames=n))
    return media, ts, [all_frames[k - 1] for k in numbers]


OPEN_DEDUP_S = 600


def open_study(s: Session, study_uid: str, *, actor: str, actor_id=None, ip=None, purpose: str = "viewer",
               dedup_s: int | None = None) -> PacsStudy:
    """Registra a abertura do estudo (auditoria de acesso) e devolve o índice dele.

    ``dedup_s``: não repete o registro se o mesmo usuário abriu o mesmo estudo com a mesma finalidade nesse
    intervalo (o Viewer pede os metadados série por série)."""
    from datetime import timedelta
    from vyonix.audit.models import AuditEntry
    st = study(s, study_uid)
    if dedup_s:
        since = utcnow() - timedelta(seconds=dedup_s)
        recent = s.execute(select(AuditEntry.seq).where(
            AuditEntry.action == "pacs.study.open", AuditEntry.target_id == str(st.id), AuditEntry.actor == actor[:120],
            AuditEntry.at >= since, AuditEntry.details["purpose"].as_string() == purpose).limit(1)).first()
        if recent:
            return st
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.study.open", target_type="study",
                 target_id=st.id, details={"purpose": purpose})
    return st


def stats(s: Session) -> dict[str, Any]:
    return {"studies": s.execute(select(func.count()).select_from(PacsStudy)).scalar(),
            "series": s.execute(select(func.count()).select_from(PacsSeries)).scalar(),
            "instances": s.execute(select(func.count()).select_from(PacsInstance)).scalar(),
            "bytes": int(s.execute(select(func.coalesce(func.sum(PacsInstance.size_bytes), 0))).scalar())}


# --------------------------------------------------------------------------- qualidade (PM §25)

STABLE_AFTER_S = 120          # sem instância nova por 2 min → recepção considerada encerrada


def _gaps(numbers: list[int]) -> list[int]:
    if not numbers:
        return []
    have = set(numbers)
    return [n for n in range(min(numbers), max(numbers) + 1) if n not in have][:50]


def quality(s: Session, study_uid: str, *, now=None) -> dict[str, Any]:
    """Indicadores de qualidade de um estudo indexado.

    O DICOM não informa quantas instâncias um estudo deveria ter; por isso "possivelmente incompleto" é
    um indício (lacuna ou repetição na numeração das instâncias, recepção ainda em andamento), nunca uma
    afirmação de completude. Estudo sem pedido conciliado aparece como pendência de conciliação.
    """
    from vyonix.clinical.models import Study
    now = now or utcnow()
    st = study(s, study_uid)
    issues: list[dict[str, Any]] = []
    series_out = []
    for se in s.execute(select(PacsSeries).where(PacsSeries.study_id == st.id)
                        .order_by(PacsSeries.series_number.nulls_last())).scalars():
        nums = [n for (n,) in s.execute(select(PacsInstance.instance_number).where(PacsInstance.series_id == se.id))]
        known = [n for n in nums if n is not None]
        gaps = _gaps(known)
        dup = sorted({n for n in known if known.count(n) > 1})
        no_number = len(nums) - len(known)
        series_out.append({"series_uid": se.series_uid, "modality": se.modality, "series_number": se.series_number,
                           "instances": len(nums), "missing_numbers": gaps, "repeated_numbers": dup,
                           "without_number": no_number})
        if gaps:
            issues.append({"code": "instance_gap", "series_uid": se.series_uid,
                           "message": f"Série {se.series_number or '?'}: faltam as instâncias {', '.join(map(str, gaps[:10]))}"
                                      + ("…" if len(gaps) > 10 else "") + " na numeração recebida."})
        if dup:
            issues.append({"code": "instance_repeated", "series_uid": se.series_uid,
                           "message": f"Série {se.series_number or '?'}: números de instância repetidos "
                                      f"({', '.join(map(str, dup[:10]))})."})
    receiving = (now - st.last_received_at).total_seconds() < STABLE_AFTER_S
    if receiving:
        issues.append({"code": "receiving", "message": "Recepção em andamento (instância recebida há menos de "
                                                         f"{STABLE_AFTER_S // 60} minutos)."})
    cs = s.get(Study, st.clinical_study_id) if st.clinical_study_id else None
    if cs is None or cs.order_id is None:
        issues.append({"code": "no_order", "message": "Estudo sem pedido conciliado."})
    if not st.accession:
        issues.append({"code": "no_accession", "message": "Estudo sem número de acesso (Accession Number)."})
    return {"study_uid": st.study_uid, "receiving": receiving, "last_received_at": st.last_received_at.isoformat(),
            "reconciled": bool(cs and cs.order_id), "series": series_out, "issues": issues,
            "possibly_incomplete": receiving or any(i["code"] == "instance_gap" for i in issues)}


def quality_overview(s: Session, *, limit: int = 100, only_issues: bool = True) -> list[dict[str, Any]]:
    """Estudos mais recentes com os indicadores de qualidade (por padrão, só os que têm pendência)."""
    out = []
    for st in s.execute(select(PacsStudy).order_by(PacsStudy.last_received_at.desc()).limit(min(limit, MAX_RESULTS))
                        ).scalars():
        q = quality(s, st.study_uid)
        if q["issues"] or not only_issues:
            out.append({"study_uid": q["study_uid"], "study_date": st.study_date.isoformat() if st.study_date else None,
                        "accession": st.accession, "possibly_incomplete": q["possibly_incomplete"],
                        "reconciled": q["reconciled"], "issues": [i["code"] for i in q["issues"]]})
    return out


# --------------------------------------------------------------------------- rotas de AE Title (modo cloud)

AET_RE = __import__("re").compile(r"^[A-Z0-9_\-. ]{1,16}$")


def _aet(value: str) -> str:
    v = (value or "").strip().upper()
    if not AET_RE.match(v) or v != v.strip():
        raise ValidationFailed("AE Title inválido: até 16 caracteres (letras, números, espaço, _ - .).")
    return v


def routes(s: Session) -> list[dict]:
    from vyonix.pacs.models import PacsAeRoute
    return [{"id": str(r.id), "called_aet": r.called_aet, "description": r.description, "created_by": r.created_by,
             "created_at": r.created_at.isoformat()}
            for r in s.execute(select(PacsAeRoute).order_by(PacsAeRoute.called_aet)).scalars()]


def add_route(s: Session, called_aet: str, *, description: str | None = None, actor: str, actor_id=None,
              ip=None) -> dict:
    """Reserva um AE Title para a organização da sessão. O AE é único no servidor inteiro."""
    from sqlalchemy.exc import IntegrityError
    from vyonix.pacs.models import PacsAeRoute
    aet = _aet(called_aet)
    r = PacsAeRoute(called_aet=aet, description=(description or "").strip()[:200] or None, created_by=actor[:120])
    try:
        with s.begin_nested():
            s.add(r)
            s.flush()
    except IntegrityError as exc:
        # Não revela qual organização usa o AE (só que ele não está disponível).
        raise Conflict(f"O AE Title {aet} não está disponível neste servidor.") from exc
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.route.add", target_type="ae_route",
                 target_id=r.id, details={"called_aet": aet})
    return {"id": str(r.id), "called_aet": aet, "description": r.description}


def remove_route(s: Session, route_id: uuid.UUID, *, actor: str, actor_id=None, ip=None) -> None:
    from vyonix.pacs.models import PacsAeRoute
    r = s.get(PacsAeRoute, route_id)
    if r is None:
        raise NotFound("Rota não encontrada.")
    aet = r.called_aet
    s.delete(r)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.route.remove", target_type="ae_route",
                 target_id=route_id, details={"called_aet": aet})


def cloud_sync(db, backend: PacsBackend, *, allowed=None, limit: int = 100, max_batches: int = 50) -> dict[str, int]:
    """Distribui às organizações o que chegou por C-STORE ao motor compartilhado (modo cloud).

    A organização é a dona do AE Title chamado pela modalidade (``CalledAET`` registrado pelo motor). Instâncias
    sem rota, ou recebidas por outro meio que não o DICOM, ficam em quarentena: não são indexadas para ninguém
    (continuam só no motor, sem acesso pelo DICOMweb) e entram na contagem. Cada organização só recebe o que foi
    endereçado ao AE Title dela; nada é indexado "por aproximação". ``allowed(sessão) -> bool`` confere se a
    organização pode receber (módulo habilitado e licença vigente); sem isso, a instância também fica em quarentena.
    """
    from vyonix.pacs.models import PacsAeRoute, PacsCloudSyncState
    out = {"indexed": 0, "duplicates": 0, "rejected": 0, "quarantined": 0}
    with db.service_session() as svc:
        st = svc.get(PacsCloudSyncState, backend.name)
        if st is None:
            st = PacsCloudSyncState(backend=backend.name, last_seq=0, quarantined=0)
            svc.add(st)
            svc.flush()
        route_map = {r.called_aet: r.tenant_id for r in svc.execute(select(PacsAeRoute)).scalars()}
        since = st.last_seq
    for _ in range(max_batches):
        changes, last, done = backend.changes(since, limit)
        quarantined = 0
        for ch in changes:
            try:
                org = backend.origin(ch.backend_id)
            except FileNotFoundError:
                continue
            aet = (org.get("called_aet") or "").upper()
            tid = route_map.get(aet) if org.get("origin") == "DicomProtocol" else None
            if tid is None:
                quarantined += 1
                continue
            with db.session(tid) as s:
                if allowed is not None and not allowed(s):
                    quarantined += 1
                    continue
                if s.execute(select(PacsInstance.id).where(PacsInstance.backend == backend.name,
                                                           PacsInstance.backend_id == ch.backend_id)).first():
                    out["duplicates"] += 1
                    continue
                try:
                    with s.begin_nested():
                        r = ingest(s, backend, backend.fetch(ch.backend_id), actor="pacs-sync", via="dimse")
                    out["duplicates" if r.duplicate else "indexed"] += 1
                except InstanceRejected:
                    out["rejected"] += 1
                except FileNotFoundError:
                    continue
        out["quarantined"] += quarantined
        since = last
        with db.service_session() as svc:
            st = svc.get(PacsCloudSyncState, backend.name)
            st.last_seq, st.quarantined, st.updated_at = last, st.quarantined + quarantined, utcnow()
        if done:
            break
    return out
