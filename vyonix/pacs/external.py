"""Visualizadores externos: **Weasis** (aplicativo instalado no computador) e **Oviyam** (serviço web separado).

Weasis — mecanismo oficial: link ``weasis://?$dicom:get -w "<manifesto>"`` (associação de protocolo feita pelo
instalador do Weasis) e manifesto XML 2.5 (``arcQuery``/``Patient``/``Study``/``Series``/``Instance``) com WADO-URI.

1. O usuário logado pede a abertura (``launch``): o servidor confere permissão, escopo e organização e cria um
   **código de manifesto de uso único** (2 minutos). Só esse código vai no link ``weasis://`` — nenhuma credencial
   permanente na URL, nenhum link público.
2. O Weasis busca o manifesto por HTTPS: o código é consumido e o servidor entrega o manifesto com uma **credencial de
   acesso** de curta duração (``weasis_access_minutes``) no elemento ``httpTag`` (cabeçalho ``Authorization:
   Bearer``), presa àquele estudo, àquele usuário e àquela organização.
3. O Weasis baixa cada instância pelo WADO-URI do VYONIX com o cabeçalho; o servidor confere a credencial, o estudo,
   se o usuário continua ativo e com permissão, e a integridade (SHA-256) do arquivo. Identificadores DICOM originais
   não são alterados.

Oviyam: o VYONIX só **monta o endereço** (``viewer.html?studyUID=...&serverName=...``) quando o administrador
configurou e ligou — e o Oviyam usa o próprio controle de acesso e o próprio AE no PACS (não aplica as permissões do
VYONIX). Por isso vem desligado e marcado como não homologado (ver ``docs/platform/Visualizadores_Weasis_Oviyam.md``).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import quote, quote_plus, urlencode
from xml.sax.saxutils import quoteattr

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.db.base import utcnow
from vyonix.errors import Conflict, Forbidden, NotFound, Unauthorized
from vyonix.pacs.models import ViewerToken

MANIFEST_MINUTES = 2
VIEWERS = {"weasis": "Weasis — visualização avançada (aplicativo instalado)",
           "oviyam": "Oviyam — visualização web (serviço separado)"}


def settings_of(s: Session) -> dict[str, Any]:
    from vyonix.settings import service as settings
    return settings.get(s, "pacs", "external_viewers")


def availability(s: Session) -> dict[str, Any]:
    """Quais visualizadores estão disponíveis e, quando não, por quê (a interface mostra o motivo)."""
    cfg = settings_of(s)
    out = {"vyonix": {"available": True, "label": "VYONIX Viewer — no navegador", "reason": None}}
    out["weasis"] = {"available": bool(cfg["weasis_enabled"]), "label": VIEWERS["weasis"],
                     "reason": None if cfg["weasis_enabled"] else "Desativado pelo administrador (aguardando validação)."}
    ov_ok = bool(cfg["oviyam_enabled"] and cfg["oviyam_url"] and cfg["oviyam_server_name"])
    out["oviyam"] = {"available": ov_ok, "label": VIEWERS["oviyam"],
                     "reason": None if ov_ok else ("Não configurado." if cfg["oviyam_enabled"] else
                                                   "Desativado: não homologado (controle de acesso próprio do Oviyam).")}
    return out


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _new_token(s: Session, *, tenant_id: uuid.UUID, kind: str, viewer: str, study_uid: str, user_id: uuid.UUID,
               minutes: int) -> str:
    secret = secrets.token_urlsafe(32)
    s.add(ViewerToken(token_hash=_hash(secret), kind=kind, viewer=viewer, study_uid=study_uid, user_id=user_id,
                      expires_at=utcnow() + timedelta(minutes=minutes)))
    s.flush()
    return f"{tenant_id}.{secret}"


def split_token(token: str) -> tuple[uuid.UUID, str] | None:
    """``<organização>.<segredo>`` → (organização, segredo); qualquer outra forma = inválido."""
    try:
        tid, secret = token.split(".", 1)
        return uuid.UUID(tid), secret
    except (ValueError, AttributeError):
        return None


def _visible_study(s: Session, p, study_uid: str):
    from vyonix.pacs import viewing
    from vyonix.pacs.models import PacsStudy
    viewing.require_uid(s, p, study_uid)                     # escopo opcional por vínculo
    ps = s.execute(select(PacsStudy).where(PacsStudy.study_uid == study_uid)).scalar_one_or_none()
    if ps is None:
        raise NotFound("Estudo não encontrado.")
    return ps


def launch(s: Session, p, study_uid: str, viewer: str, *, base_url: str, ip=None) -> dict[str, Any]:
    """Link para abrir o estudo no visualizador escolhido (o usuário já está autenticado no VYONIX)."""
    av = availability(s)
    if viewer not in ("weasis", "oviyam"):
        raise NotFound("Visualizador desconhecido.")
    if not av[viewer]["available"]:
        raise Conflict(f"{VIEWERS[viewer].split(' —')[0]} indisponível: {av[viewer]['reason']}",
                       code="viewer_unavailable")
    ps = _visible_study(s, p, study_uid)
    if viewer == "weasis":
        code = _new_token(s, tenant_id=p.tenant_id, kind="manifest", viewer="weasis", study_uid=study_uid,
                          user_id=p.user_id, minutes=MANIFEST_MINUTES)
        manifest = f"{base_url.rstrip('/')}/api/v1/pacs/external/weasis/manifest/{quote(code, safe='.')}"
        uri = "weasis://?" + quote_plus(f'$dicom:get -w "{manifest}"')
        out = {"viewer": "weasis", "uri": uri, "expires_in_s": MANIFEST_MINUTES * 60,
               "help": ["Na primeira vez, instale o Weasis (weasis.org) neste computador: o instalador registra os "
                        "links weasis://.", "O navegador pode pedir confirmação para abrir o Weasis: permita.",
                        "O link vale uma vez e por 2 minutos; para abrir de novo, clique outra vez em “Abrir com Weasis”."]}
    else:
        cfg = settings_of(s)
        url = cfg["oviyam_url"].rstrip("/") + "/viewer.html?" + urlencode(
            {"studyUID": study_uid, "serverName": cfg["oviyam_server_name"]})
        out = {"viewer": "oviyam", "url": url,
               "help": ["O Oviyam pede o login próprio dele: o acesso às imagens ali não segue as permissões do VYONIX."]}
    audit.record(s, actor=p.username, actor_id=p.user_id, ip=ip, action="pacs.viewer.external", target_type="study",
                 target_id=ps.id, details={"viewer": viewer})
    return out


def _check(s: Session, token: str, *, kind: str) -> ViewerToken:
    parts = split_token(token)
    if parts is None:
        raise Unauthorized("Credencial do visualizador inválida.")
    row = s.execute(select(ViewerToken).where(ViewerToken.token_hash == _hash(parts[1]),
                                              ViewerToken.kind == kind)).scalar_one_or_none()
    now = utcnow()
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        raise Unauthorized("Credencial do visualizador inválida ou vencida. Abra o estudo de novo pelo VYONIX.")
    from vyonix.auth import service as auth
    if not auth.user_has(s, row.user_id, "pacs.studies.read"):
        raise Forbidden("O usuário não tem mais permissão para abrir estudos.")
    return row


def manifest(s: Session, tenant_id: uuid.UUID, code: str, *, base_url: str, ip=None) -> str:
    """Manifesto XML do Weasis (consome o código de uso único e emite a credencial de acesso do estudo)."""
    from vyonix.pacs.models import PacsInstance, PacsSeries, PacsStudy
    row = _check(s, code, kind="manifest")
    if row.used_at is not None:
        raise Unauthorized("Este link do Weasis já foi usado. Abra o estudo de novo pelo VYONIX.")
    row.used_at = utcnow()
    minutes = settings_of(s)["weasis_access_minutes"]
    access = _new_token(s, tenant_id=tenant_id, kind="access", viewer="weasis", study_uid=row.study_uid,
                        user_id=row.user_id, minutes=minutes)
    ps = s.execute(select(PacsStudy).where(PacsStudy.study_uid == row.study_uid)).scalar_one_or_none()
    if ps is None:
        raise NotFound("Estudo não encontrado.")
    d = lambda v: v.strftime("%Y%m%d") if v else None  # noqa: E731

    def tag(name: str, attrs: dict[str, Any], close: bool = False) -> str:
        body = " ".join(f"{k}={quoteattr(str(v))}" for k, v in attrs.items() if v not in (None, ""))
        return f"<{name} {body}{'/' if close else ''}>"
    out = ['<?xml version="1.0" encoding="UTF-8" ?>',
           '<manifest xmlns="http://www.weasis.org/xsd/2.5" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
           tag("arcQuery", {"arcId": "VYONIX", "baseUrl": base_url.rstrip("/") + "/api/v1/pacs/external/wado",
                            "requireOnlySOPInstanceUID": "false"}),
           tag("httpTag", {"key": "Authorization", "value": "Bearer " + access}, close=True),
           tag("Patient", {"PatientID": ps.patient_id, "PatientName": ps.patient_name,
                           "PatientBirthDate": d(ps.patient_birth_date), "PatientSex": ps.patient_sex}),
           tag("Study", {"StudyInstanceUID": ps.study_uid, "StudyDate": d(ps.study_date), "StudyTime": ps.study_time,
                         "AccessionNumber": ps.accession, "StudyDescription": ps.description,
                         "StudyID": ps.dicom_study_id, "ReferringPhysicianName": ps.referring_physician})]
    series = list(s.execute(select(PacsSeries).where(PacsSeries.study_id == ps.id)
                            .order_by(PacsSeries.series_number.nulls_last())).scalars())
    for se in series:
        out.append(tag("Series", {"SeriesInstanceUID": se.series_uid, "Modality": se.modality,
                                  "SeriesNumber": se.series_number, "SeriesDescription": se.description}))
        for it in s.execute(select(PacsInstance).where(PacsInstance.series_id == se.id)
                            .order_by(PacsInstance.instance_number.nulls_last())).scalars():
            out.append(tag("Instance", {"SOPInstanceUID": it.sop_uid, "InstanceNumber": it.instance_number},
                           close=True))
        out.append("</Series>")
    out += ["</Study>", "</Patient>", "</arcQuery>", "</manifest>"]
    audit.record(s, actor=f"weasis:{row.user_id}", actor_id=row.user_id, ip=ip, action="pacs.viewer.external.manifest",
                 target_type="study", target_id=ps.id, details={"series": len(series), "minutes": minutes})
    return "\n".join(out)


def wado_instance(s: Session, backend, token: str, *, study_uid: str, series_uid: str, sop_uid: str,
                  ip=None) -> bytes:
    """WADO-URI (``application/dicom``) para o Weasis: só o estudo da credencial."""
    from vyonix.pacs import service as pacs
    row = _check(s, token, kind="access")
    if study_uid != row.study_uid:
        raise Forbidden("A credencial do visualizador não vale para este estudo.")
    if row.used_at is None:                               # primeira imagem: registra a abertura (uma vez por credencial)
        row.used_at = utcnow()
        pacs.open_study(s, study_uid, actor=f"weasis:{row.user_id}", actor_id=row.user_id, ip=ip, purpose="weasis")
    return pacs.retrieve_instance(s, backend, study_uid, series_uid, sop_uid)


def revoke_user(s: Session, user_id: uuid.UUID) -> int:
    """Revoga as credenciais vigentes de um usuário (ex.: ao sair ou ao ser desativado)."""
    n = 0
    for row in s.execute(select(ViewerToken).where(ViewerToken.user_id == user_id,
                                                   ViewerToken.revoked_at.is_(None))).scalars():
        row.revoked_at = utcnow()
        n += 1
    s.flush()
    return n
