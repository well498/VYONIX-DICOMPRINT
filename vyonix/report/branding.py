"""TELELAUDO T2 — identidade visual do laudo por organização e por unidade.

* Cada gravação cria uma **versão imutável** (organização: ``site_id`` nulo; unidade: ``site_id``). A unidade herda da
  organização campo a campo (só sobrescreve o que definiu).
* Imagens (logomarca e papel timbrado) só PNG ou JPEG, conferidos pelo conteúdo (não pela extensão), decodificados
  com o Pillow, com limite de tamanho e de pixels; guardados no banco com SHA-256 (sem caminho de arquivo nem URL
  pública). PDF/SVG não são aceitos (podem conter conteúdo ativo).
* Sem identidade: aparência neutra do sistema, sem logomarca. Nunca usa a identidade de outra organização (RLS).
* O laudo liberado registra as versões usadas; a reemissão do PDF usa as mesmas versões.
"""

from __future__ import annotations

import hashlib
import io
import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.errors import NotFound, ValidationFailed
from vyonix.report.models import Asset, BrandingVersion

MAX_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 6000 * 6000
FONTS = ("Sans", "Serif")
DEFAULTS: dict[str, Any] = {"margin_top_mm": 16, "margin_bottom_mm": 16, "margin_left_mm": 18, "margin_right_mm": 18,
                            "font": "Sans", "font_size": 10.5, "accent_color": "#12313F", "header_text": "",
                            "footer_text": "", "page_numbers": True, "logo_height_mm": 14}
LIMITS = {"margin_top_mm": (5, 60), "margin_bottom_mm": (5, 60), "margin_left_mm": (5, 40), "margin_right_mm": (5, 40),
          "font_size": (8, 14), "logo_height_mm": (6, 40)}


def _clean(settings: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (settings or {}).items():
        if k not in DEFAULTS:
            raise ValidationFailed(f"Configuração desconhecida: {k}.")
        if v is None:
            continue                                          # não definido: herda
        if k in LIMITS:
            lo, hi = LIMITS[k]
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ValidationFailed(f"{k}: número inválido.") from None
            if not lo <= v <= hi:
                raise ValidationFailed(f"{k}: entre {lo} e {hi}.")
        elif k == "font":
            if v not in FONTS:
                raise ValidationFailed(f"Fonte: use {', '.join(FONTS)}.")
        elif k == "accent_color":
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(v)):
                raise ValidationFailed("Cor: formato #RRGGBB.")
            v = str(v).upper()
        elif k in ("header_text", "footer_text"):
            v = str(v)[:300]
        elif k == "page_numbers":
            v = bool(v)
        out[k] = v
    return out


def store_asset(s: Session, kind: str, data: bytes, *, actor: str, actor_id=None, ip=None) -> Asset:
    from PIL import Image
    if kind not in ("logo", "letterhead"):
        raise ValidationFailed("Tipo de imagem inválido.")
    if not data or len(data) > MAX_BYTES:
        raise ValidationFailed("Imagem vazia ou acima de 2 MB.")
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        media = "image/png"
    elif data[:3] == b"\xff\xd8\xff":
        media = "image/jpeg"
    else:
        raise ValidationFailed("Use PNG ou JPEG (o conteúdo do arquivo não é uma imagem aceita).")
    try:
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            im.load()
    except Exception as exc:  # noqa: BLE001 - arquivo corrompido, bomba de descompressão etc.
        raise ValidationFailed(f"Imagem inválida ou danificada ({type(exc).__name__}).") from None
    a = Asset(kind=kind, media_type=media, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), width=w,
              height=h, data=data, created_by=actor[:120])
    s.add(a)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.asset.upload", target_type="report_asset",
                 target_id=a.id, details={"kind": kind, "sha256": a.sha256, "size": a.size_bytes})
    return a


def _latest(s: Session, site_id: uuid.UUID | None) -> BrandingVersion | None:
    q = select(BrandingVersion).where(BrandingVersion.site_id.is_(None) if site_id is None
                                      else BrandingVersion.site_id == site_id)
    return s.execute(q.order_by(BrandingVersion.version.desc()).limit(1)).scalar_one_or_none()


def _at(s: Session, site_id: uuid.UUID | None, version: int | None) -> BrandingVersion | None:
    if not version:
        return None
    q = select(BrandingVersion).where(BrandingVersion.version == version,
                                      BrandingVersion.site_id.is_(None) if site_id is None
                                      else BrandingVersion.site_id == site_id)
    return s.execute(q).scalar_one_or_none()


def save(s: Session, *, site_id: uuid.UUID | None, settings: dict[str, Any], logo_asset_id: uuid.UUID | None = None,
         letterhead_asset_id: uuid.UUID | None = None, keep_images: bool = True, actor: str, actor_id=None,
         ip=None) -> BrandingVersion:
    """Nova versão da identidade (organização ou unidade). ``keep_images``: imagens não informadas continuam as da
    versão anterior do mesmo escopo."""
    from vyonix.tenancy.models import Site
    if site_id and s.get(Site, site_id) is None:
        raise NotFound("Unidade não encontrada nesta organização.")
    for aid, kind in ((logo_asset_id, "logo"), (letterhead_asset_id, "letterhead")):
        if aid:
            a = s.get(Asset, aid)
            if a is None or a.kind != kind:
                raise NotFound("Imagem não encontrada nesta organização.")
    prev = _latest(s, site_id)
    if keep_images and prev is not None:
        logo_asset_id = logo_asset_id or prev.logo_asset_id
        letterhead_asset_id = letterhead_asset_id or prev.letterhead_asset_id
    v = BrandingVersion(site_id=site_id, version=(prev.version + 1) if prev else 1, settings=_clean(settings),
                        logo_asset_id=logo_asset_id, letterhead_asset_id=letterhead_asset_id, created_by=actor[:120])
    s.add(v)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.branding.save", target_type="branding",
                 target_id=v.id, details={"site_id": str(site_id) if site_id else None, "version": v.version})
    return v


def effective(s: Session, site_id: uuid.UUID | None, *, org_version: int | None = None,
              site_version: int | None = None) -> dict[str, Any]:
    """Identidade final: padrão do sistema ← organização ← unidade (campo a campo). Com versões informadas (laudo
    liberado), usa exatamente essas; senão, as mais recentes."""
    org = _at(s, None, org_version) if org_version else _latest(s, None)
    site = (_at(s, site_id, site_version) if site_version else _latest(s, site_id)) if site_id else None
    cfg = dict(DEFAULTS)
    origin = {k: "sistema" for k in DEFAULTS}
    logo = letterhead = None
    for scope, v in (("organização", org), ("unidade", site)):
        if v is None:
            continue
        for k, val in v.settings.items():
            cfg[k], origin[k] = val, scope
        if v.logo_asset_id:
            logo, origin["logo"] = v.logo_asset_id, scope
        if v.letterhead_asset_id:
            letterhead, origin["letterhead"] = v.letterhead_asset_id, scope
    return {"settings": cfg, "origin": origin, "logo": s.get(Asset, logo) if logo else None,
            "letterhead": s.get(Asset, letterhead) if letterhead else None,
            "org_version": org.version if org else None, "site_version": site.version if site else None}


def describe(s: Session) -> dict[str, Any]:
    from vyonix.tenancy.models import Site
    out = []
    scopes = [(None, "Organização")] + [(x.id, x.name) for x in s.execute(select(Site).order_by(Site.name)).scalars()]
    for sid, name in scopes:
        v = _latest(s, sid)
        n = s.execute(select(func.count()).select_from(BrandingVersion).where(
            BrandingVersion.site_id.is_(None) if sid is None else BrandingVersion.site_id == sid)).scalar() or 0
        out.append({"site_id": str(sid) if sid else None, "name": name, "versions": n,
                    "current": None if v is None else {"version": v.version, "settings": v.settings,
                                                       "logo": bool(v.logo_asset_id),
                                                       "letterhead": bool(v.letterhead_asset_id),
                                                       "created_by": v.created_by,
                                                       "created_at": v.created_at.isoformat()}})
    return {"scopes": out, "defaults": DEFAULTS}
