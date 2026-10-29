"""Lançador do VYONIX Viewer: protocolos de exibição, comparação com exame anterior e escopo de acesso às imagens.

O Viewer é o OHIF compilado sem alterações; a VYONIX decide **o que abrir e como** e monta o endereço:

* ``default`` → protocolo padrão do OHIF (1 quadro; o médico muda o layout pelo botão Layout);
* ``grid``    → ``@ohif/mnGrid`` (grade com as séries do estudo);
* ``compare`` → ``@ohif/hpCompare`` com o estudo atual e **um** anterior lado a lado (1×2, ou 2×2 com duas séries).

Protocolo efetivo, do mais forte ao mais fraco: escolha explícita → protocolo **pessoal** (se a instituição permitir)
→ protocolo da **instituição** → padrão. Em cada nível vale o mais específico: procedimento > modalidade > geral.

Comparação: só com anteriores **do mesmo paciente**, **no PACS** e **que o usuário pode ver** (mesmo escopo da fila de
laudos e compartilhamentos). Nenhuma correspondência anatômica automática: o OHIF só posiciona o anterior ao lado.

Acesso (``pacs/viewer.access``): ``organization`` (padrão, comportamento homologado) ou ``linked`` — o DICOMweb passa a
aplicar o escopo do médico (unidades com vínculo vigente ou compartilhamento). Coordenação (``report.assign``) e
administração do PACS (``pacs.admin``) continuam vendo a organização inteira.
"""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.errors import Forbidden, NotFound, ValidationFailed
from vyonix.pacs.models import ViewerProtocol

LAYOUTS = {"default": None, "grid": "@ohif/mnGrid", "compare": "@ohif/hpCompare"}
LAYOUT_NAMES = {"default": "Padrão (1 quadro)", "grid": "Grade de séries", "compare": "Comparação com anterior"}
MAX_PER_OWNER = 100


# ------------------------------------------------------------------ escopo de acesso
def settings_of(s: Session) -> dict[str, Any]:
    from vyonix.settings import service as settings
    return settings.get(s, "pacs", "viewer")


def scope_for(s: Session, p) -> tuple[bool, set] | None:
    """``None`` = vê a organização inteira; senão (organização_inteira, {unidades}) do vínculo do médico."""
    from vyonix.report import queue
    if p.has("pacs.admin") or p.has("report.assign") or settings_of(s).get("access") != "linked":
        return None
    return queue.scope(s, p.user_id, can_assign=False)


def can_see(s: Session, sc, p, study, shared: set | None = None) -> bool:
    from vyonix.report import queue
    if sc is None:
        return True
    if queue.allowed(sc, study.site_id):
        return True
    if shared is None:
        from vyonix.ris import prep
        shared = prep.shared_studies(s, p.user_id)
    return study.id in shared


def allowed_uids(s: Session, p, uids: list[str]) -> set[str]:
    """Quais Study Instance UIDs o usuário pode ver (para filtrar o QIDO e conferir o WADO)."""
    sc = scope_for(s, p)
    if sc is None:
        return set(uids)
    from vyonix.clinical.models import Study
    from vyonix.ris import prep
    shared = prep.shared_studies(s, p.user_id)
    rows = s.execute(select(Study).where(Study.study_instance_uid.in_(uids))).scalars() if uids else []
    return {st.study_instance_uid for st in rows if can_see(s, sc, p, st, shared)}


def require_uid(s: Session, p, study_uid: str) -> None:
    """Estudo fora do escopo responde como inexistente (não revela que existe)."""
    if study_uid not in allowed_uids(s, p, [study_uid]):
        raise NotFound("Estudo não encontrado.")


# ------------------------------------------------------------------ protocolos
def _out(r: ViewerProtocol) -> dict[str, Any]:
    return {"id": str(r.id), "personal": r.owner_user_id is not None, "modality": r.modality,
            "procedure_id": str(r.procedure_id) if r.procedure_id else None, "layout": r.layout,
            "layout_name": LAYOUT_NAMES[r.layout], "compare_prior": r.compare_prior,
            "prior_same_modality": r.prior_same_modality}


def protocols(s: Session, *, user_id: uuid.UUID | None, scope: str = "all") -> list[dict[str, Any]]:
    q = select(ViewerProtocol)
    if scope == "own":
        q = q.where(ViewerProtocol.owner_user_id == user_id)
    elif scope == "institution":
        q = q.where(ViewerProtocol.owner_user_id.is_(None))
    else:
        q = q.where((ViewerProtocol.owner_user_id.is_(None)) | (ViewerProtocol.owner_user_id == user_id))
    rows = [_out(r) for r in s.execute(q).scalars()]
    return sorted(rows, key=lambda x: (x["personal"], x["modality"] or "~", x["procedure_id"] or ""))


def save_protocol(s: Session, *, owner_user_id: uuid.UUID | None, modality: str | None, procedure_id: uuid.UUID | None,
                  layout: str, compare_prior: bool = False, prior_same_modality: bool = True,
                  protocol_id: uuid.UUID | None = None, actor: str, actor_id=None, ip=None) -> ViewerProtocol:
    from vyonix.clinical.models import Procedure
    if layout not in LAYOUTS:
        raise ValidationFailed("Layout inválido (padrão, grade ou comparação).")
    mod = (modality or "").strip().upper()[:16] or None
    if procedure_id and s.get(Procedure, procedure_id) is None:
        raise NotFound("Procedimento não encontrado nesta organização.")
    r = None
    if protocol_id:
        r = s.get(ViewerProtocol, protocol_id)
        if r is None or r.owner_user_id != owner_user_id:
            raise NotFound("Protocolo não encontrado.")
    same = s.execute(select(ViewerProtocol).where(
        ViewerProtocol.modality == mod if mod else ViewerProtocol.modality.is_(None),
        ViewerProtocol.procedure_id == procedure_id if procedure_id else ViewerProtocol.procedure_id.is_(None),
        ViewerProtocol.owner_user_id == owner_user_id if owner_user_id else ViewerProtocol.owner_user_id.is_(None),
    )).scalars().first()
    if same is not None and same is not r:
        r = same                                              # um protocolo por (dono, modalidade, procedimento)
    if r is None:
        n = len(s.execute(select(ViewerProtocol.id).where(
            ViewerProtocol.owner_user_id == owner_user_id if owner_user_id
            else ViewerProtocol.owner_user_id.is_(None))).all())
        if n >= MAX_PER_OWNER:
            raise ValidationFailed(f"Limite de {MAX_PER_OWNER} protocolos.")
        r = ViewerProtocol(owner_user_id=owner_user_id, created_by=actor[:120], layout=layout)
        s.add(r)
    r.modality, r.procedure_id, r.layout = mod, procedure_id, layout
    r.compare_prior = bool(compare_prior or layout == "compare")
    r.prior_same_modality = bool(prior_same_modality)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.viewer.protocol.save",
                 target_type="viewer_protocol", target_id=r.id,
                 details={"personal": owner_user_id is not None, "modality": mod, "layout": layout})
    return r


def delete_protocol(s: Session, protocol_id: uuid.UUID, *, owner_user_id: uuid.UUID | None, actor: str,
                    actor_id=None, ip=None) -> None:
    r = s.get(ViewerProtocol, protocol_id)
    if r is None or r.owner_user_id != owner_user_id:
        raise NotFound("Protocolo não encontrado.")
    s.delete(r)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.viewer.protocol.delete",
                 target_type="viewer_protocol", target_id=protocol_id, details={"personal": owner_user_id is not None})


def _pick(rows: list[ViewerProtocol], modality: str | None, procedure_id) -> ViewerProtocol | None:
    best, rank = None, -1
    for r in rows:
        if r.procedure_id and r.procedure_id != procedure_id:
            continue
        if r.modality and r.modality != (modality or "").upper():
            continue
        k = (2 if r.procedure_id else 0) + (1 if r.modality else 0)
        if k > rank:
            best, rank = r, k
    return best


def effective(s: Session, *, user_id, modality: str | None, procedure_id=None) -> tuple[ViewerProtocol | None, str]:
    rows = list(s.execute(select(ViewerProtocol).where(
        (ViewerProtocol.owner_user_id.is_(None)) | (ViewerProtocol.owner_user_id == user_id))).scalars())
    if settings_of(s).get("allow_personal", True):
        mine = _pick([r for r in rows if r.owner_user_id is not None], modality, procedure_id)
        if mine is not None:
            return mine, "personal"
    inst = _pick([r for r in rows if r.owner_user_id is None], modality, procedure_id)
    return (inst, "institution") if inst is not None else (None, "default")


# ------------------------------------------------------------------ lançamento
def launch(s: Session, p, study_uid: str, *, layout: str | None = None, prior_uid: str | None = None,
           ip=None, record: bool = True) -> dict[str, Any]:
    """Endereço do Viewer para o estudo (e o anterior, na comparação), com o protocolo efetivo e a lista de anteriores
    autorizados para escolher. Registra na auditoria quais estudos foram abertos e como."""
    from vyonix.clinical.models import Order, Study
    from vyonix.ris import timeline
    st = s.execute(select(Study).where(Study.study_instance_uid == study_uid)).scalars().first()
    sc = scope_for(s, p)
    if st is None:                                   # só no índice do PACS (sem cadastro clínico): abre sem protocolo
        from vyonix.pacs.models import PacsStudy
        if sc is not None or s.execute(select(PacsStudy.id).where(PacsStudy.study_uid == study_uid)).first() is None:
            raise NotFound("Estudo não encontrado.")
        return {"url": "/viewer/viewer?" + urlencode({"StudyInstanceUIDs": study_uid}), "layout": "default",
                "layout_name": LAYOUT_NAMES["default"], "source": "default", "prior": None, "priors": [],
                "note": "Estudo ainda sem cadastro clínico: aberto sem protocolo nem comparação.", "study": None}
    from vyonix.ris import prep
    shared = prep.shared_studies(s, p.user_id)
    if not can_see(s, sc, p, st, shared):
        raise NotFound("Estudo não encontrado.")
    if layout is not None and layout not in LAYOUTS:
        raise ValidationFailed("Layout inválido (padrão, grade ou comparação).")
    order = s.get(Order, st.order_id) if st.order_id else None
    proto, source = effective(s, user_id=p.user_id, modality=st.modality,
                              procedure_id=order.procedure_id if order else None)
    eff = layout or (proto.layout if proto else "default")
    if layout:
        source = "explicit"
    same_mod = proto.prior_same_modality if proto else True
    want_prior = eff == "compare" or bool(prior_uid) or bool(proto and proto.compare_prior and not layout)
    priors = []
    for it in timeline.priors(s, st.id)["items"]:
        if not it["study_instance_uid"]:
            continue                                            # sem imagens no PACS
        if st.study_date and it["study_date"] and it["study_date"] > st.study_date.isoformat():
            continue                                            # posterior ao exame aberto: não é "anterior"
        pst = s.get(Study, uuid.UUID(it["study_id"]))
        if not can_see(s, sc, p, pst, shared):
            continue
        priors.append({k: it[k] for k in ("study_id", "study_instance_uid", "study_date", "modality", "description",
                                          "accession", "same_modality")})
    prior, note = None, None
    if prior_uid:
        prior = next((x for x in priors if x["study_instance_uid"] == prior_uid), None)
        if prior is None:
            raise Forbidden("Exame anterior não disponível para comparação (outro paciente, sem imagens ou fora do "
                            "seu acesso).", code="prior_not_allowed")
        eff = "compare"
    elif want_prior:
        cands = [x for x in priors if x["same_modality"]] if same_mod else priors
        prior = (cands or [None])[0]
        if prior is None:
            note = "Sem exame anterior disponível para comparação: aberto só o estudo atual."
            eff = "default" if eff == "compare" else eff
    if eff == "compare" and prior is None:
        eff = "default"
    uids = [st.study_instance_uid] + ([prior["study_instance_uid"]] if prior and eff == "compare" else [])
    q = {"StudyInstanceUIDs": ",".join(uids)}
    if LAYOUTS[eff]:
        q["hangingprotocolId"] = LAYOUTS[eff]
    url = "/viewer/viewer?" + urlencode(q, safe=",@/")
    if record:                                              # ``record=False``: só consulta (montar a tela de escolha)
        audit.record(s, actor=p.username, actor_id=p.user_id, ip=ip, action="pacs.viewer.launch", target_type="study",
                     target_id=st.id, details={"layout": eff, "source": source,
                                               "prior_study_id": prior["study_id"] if prior and eff == "compare"
                                               else None})
    return {"url": url, "layout": eff, "layout_name": LAYOUT_NAMES[eff], "source": source,
            "prior": prior if eff == "compare" else None, "priors": priors, "note": note,
            "study": {"study_id": str(st.id), "study_instance_uid": st.study_instance_uid, "modality": st.modality,
                      "study_date": st.study_date.isoformat() if st.study_date else None,
                      "description": st.description}}
