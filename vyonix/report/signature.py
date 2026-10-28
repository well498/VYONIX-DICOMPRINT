"""Imagem da assinatura manuscrita digitalizada do médico (elemento **somente visual**).

Ciclo de vida: ``pending`` (enviada, aguardando a confirmação do médico) → ``active`` → ``replaced`` / ``deleted``.
Uma imagem só fica ativa com a **confirmação do próprio médico**; só é aplicada nos laudos se ele **autorizou o uso**
(``use_signature_image``, revogável) e apenas na **liberação** de laudo dele (a versão liberada registra a imagem).

Quem pode enviar: o próprio médico ou o administrador que **o médico designou** (``signature_delegate_user_id``).
O envio do administrador fica pendente até o médico confirmar. Ninguém mais envia, vê ou usa a imagem; ela nunca
tem URL pública. Visualização pelo administrador designado (só da imagem pendente que ele enviou) é auditada.

Arquivos: JPG/JPEG, PNG ou WEBP, validados pelo conteúdo, até 5 MB; tratamento no servidor (recorte, brilho,
contraste, remoção opcional do fundo branco) e gravação como PNG cifrado com AES-GCM (chave do cofre local, dado
associado = organização + médico). Excluir apaga os bytes, exceto quando a imagem já está em laudo liberado (o
documento emitido precisa continuar reproduzível); nesse caso fica inutilizável para novos laudos.

Nada disso é assinatura digital: a confirmação por senha, a imagem e a futura assinatura PAdES/ICP-Brasil
(``vyonix/report/pades.py``, BLK-14) são coisas distintas e aparecem com nomes distintos na tela e no PDF.
"""

from __future__ import annotations

import hashlib
import io
import os
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.db.base import utcnow
from vyonix.errors import Conflict, Forbidden, NotFound, ValidationFailed
from vyonix.report.models import Physician, ReportVersion, SignatureImage

MAX_BYTES = 5 * 1024 * 1024
MAX_OUT_W = 1200
KEY_NAME = "report_signature_key"


# ------------------------------------------------------------------ tratamento da imagem
def sniff(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValidationFailed("Use JPG, JPEG, PNG ou WEBP (o conteúdo do arquivo não é uma imagem aceita).")


def process(data: bytes, *, crop: tuple[float, float, float, float] | None = None, brightness: float = 1.0,
            contrast: float = 1.0, remove_background: bool = False, threshold: int = 225) -> tuple[bytes, int, int]:
    """Recorte (frações 0–1: esquerda, topo, direita, base), brilho, contraste e remoção do fundo claro → PNG RGBA."""
    from PIL import Image, ImageEnhance, ImageOps
    if not data or len(data) > MAX_BYTES:
        raise ValidationFailed("Imagem vazia ou acima de 5 MB.")
    sniff(data)
    if not (0.3 <= brightness <= 3 and 0.3 <= contrast <= 3 and 100 <= threshold <= 254):
        raise ValidationFailed("Ajustes fora dos limites (brilho e contraste 0,3–3; limiar do fundo 100–254).")
    try:
        Image.MAX_IMAGE_PIXELS = 40_000_000
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)                            # fotos de celular na orientação certa
        im.load()
    except ValidationFailed:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValidationFailed(f"Imagem inválida ou danificada ({type(exc).__name__}).") from None
    if crop is not None:
        l, t, r, b = crop
        if not (0 <= l < r <= 1 and 0 <= t < b <= 1):
            raise ValidationFailed("Recorte inválido.")
        w, h = im.size
        im = im.crop((round(l * w), round(t * h), round(r * w), round(b * h)))
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, (255, 255, 255))          # transparência vira papel branco
        flat.paste(im, mask=im.getchannel("A"))
        im = flat
    im = im.convert("RGB")
    if brightness != 1:
        im = ImageEnhance.Brightness(im).enhance(brightness)
    if contrast != 1:
        im = ImageEnhance.Contrast(im).enhance(contrast)
    if im.width > MAX_OUT_W:
        im = im.resize((MAX_OUT_W, max(1, round(im.height * MAX_OUT_W / im.width))))
    rgba = im.convert("RGBA")
    if remove_background:
        px = rgba.getdata()
        rgba.putdata([(r_, g_, b_, 0) if min(r_, g_, b_) >= threshold else (r_, g_, b_, a_) for r_, g_, b_, a_ in px])
    if rgba.width < 20 or rgba.height < 10:
        raise ValidationFailed("Imagem pequena demais depois do recorte.")
    out = io.BytesIO()
    rgba.save(out, "PNG", optimize=True)
    return out.getvalue(), rgba.width, rgba.height


# ------------------------------------------------------------------ autorização
def _physician_of(s: Session, user_id: uuid.UUID) -> Physician:
    p = s.execute(select(Physician).where(Physician.user_id == user_id)).scalar_one_or_none()
    if p is None:
        raise Forbidden("Somente o próprio médico gerencia a imagem da assinatura.", code="physician_required")
    return p


def _target_for_upload(s: Session, uploader_id: uuid.UUID, physician_id: uuid.UUID | None) -> Physician:
    if physician_id is None:
        return _physician_of(s, uploader_id)
    p = s.get(Physician, physician_id)
    if p is None:
        raise NotFound("Médico não encontrado.")
    if p.user_id != uploader_id and p.signature_delegate_user_id != uploader_id:
        raise Forbidden("Sem autorização do médico para enviar a imagem da assinatura dele.",
                        code="signature_not_delegated")
    return p


def _aad(tenant: uuid.UUID, physician_id: uuid.UUID) -> bytes:
    return b"vyonix-signature:" + str(tenant).encode() + b":" + str(physician_id).encode()


def _encrypt(img: SignatureImage, data: bytes, key: bytes) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    img.nonce = os.urandom(12)
    img.ciphertext = AESGCM(key).encrypt(img.nonce, data, _aad(img.tenant_id, img.physician_id))


def decrypt(s: Session, image_id: uuid.UUID, *, key: bytes) -> tuple[bytes, int, int]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    img = s.get(SignatureImage, image_id)
    if img is None or not img.ciphertext:
        raise NotFound("Imagem de assinatura não disponível.")
    data = AESGCM(key).decrypt(img.nonce, img.ciphertext, _aad(img.tenant_id, img.physician_id))
    if hashlib.sha256(data).hexdigest() != img.sha256:
        raise ValidationFailed("Imagem de assinatura com integridade violada.")
    return data, img.width, img.height


def _set(img: SignatureImage, status: str) -> None:
    img.status, img.active = status, status == "active"
    if status in ("replaced", "deleted", "rejected"):
        img.ended_at = utcnow()


def _latest(s: Session, physician_id: uuid.UUID, status: str) -> SignatureImage | None:
    return s.execute(select(SignatureImage).where(SignatureImage.physician_id == physician_id,
                                                  SignatureImage.status == status)
                     .order_by(SignatureImage.created_at.desc()).limit(1)).scalar_one_or_none()


# ------------------------------------------------------------------ operações
def upload(s: Session, uploader_id: uuid.UUID, data: bytes, *, key: bytes, actor: str,
           physician_id: uuid.UUID | None = None, ip=None, **params) -> SignatureImage:
    """Envia (tratada) e deixa **pendente** até a confirmação do médico. Uma pendente anterior é descartada."""
    p = _target_for_upload(s, uploader_id, physician_id)
    png, w, h = process(data, **params)
    for old in s.execute(select(SignatureImage).where(SignatureImage.physician_id == p.id,
                                                      SignatureImage.status == "pending")).scalars():
        _set(old, "rejected")
        old.ciphertext = b""
    img = SignatureImage(physician_id=p.id, nonce=b"", ciphertext=b"", sha256=hashlib.sha256(png).hexdigest(),
                         width=w, height=h, active=False, status="pending", media_type=sniff(data),
                         uploaded_by=actor[:120], uploaded_by_id=uploader_id,
                         processing={k: v for k, v in params.items() if v is not None},
                         created_at=utcnow())                       # relógio real: ordem do histórico na transação
    s.add(img)
    s.flush()
    _encrypt(img, png, key)
    s.flush()
    by_self = p.user_id == uploader_id
    audit.record(s, actor=actor, actor_id=uploader_id, ip=ip, action="report.signature.upload",
                 target_type="physician", target_id=p.id,
                 details={"sha256": img.sha256, "by": "médico" if by_self else "administrador designado",
                          "processing": img.processing})
    return img


def confirm(s: Session, user_id: uuid.UUID, *, actor: str, ip=None) -> SignatureImage:
    """O médico confirma que a imagem pendente é a assinatura dele: ela passa a ativa (a anterior é substituída)."""
    p = _physician_of(s, user_id)
    pend = _latest(s, p.id, "pending")
    if pend is None:
        raise Conflict("Não há imagem pendente de confirmação.")
    old = _latest(s, p.id, "active")
    if old is not None:
        _set(old, "replaced")
    _set(pend, "active")
    pend.confirmed_at = utcnow()
    s.flush()
    audit.record(s, actor=actor, actor_id=user_id, ip=ip, action="report.signature.confirm", target_type="physician",
                 target_id=p.id, details={"sha256": pend.sha256, "replaced": old.sha256 if old else None})
    return pend


def delete(s: Session, user_id: uuid.UUID, *, actor: str, ip=None) -> None:
    """Exclui a imagem ativa e a pendente; o uso fica desautorizado. Bytes apagados, salvo se já em laudo liberado."""
    p = _physician_of(s, user_id)
    gone = 0
    for img in s.execute(select(SignatureImage).where(SignatureImage.physician_id == p.id,
                                                      SignatureImage.status.in_(("active", "pending")))).scalars():
        used = s.execute(select(func.count()).select_from(ReportVersion)
                         .where(ReportVersion.signature_image_id == img.id)).scalar() or 0
        _set(img, "deleted")
        if not used:
            img.ciphertext = b""
        gone += 1
    if not gone:
        raise Conflict("Não há imagem para excluir.")
    p.use_signature_image = False
    s.flush()
    audit.record(s, actor=actor, actor_id=user_id, ip=ip, action="report.signature.delete", target_type="physician",
                 target_id=p.id, details={"images": gone})


def set_consent(s: Session, user_id: uuid.UUID, allow: bool, *, actor: str, ip=None) -> Physician:
    p = _physician_of(s, user_id)
    if allow and _latest(s, p.id, "active") is None:
        raise ValidationFailed("Envie e confirme a imagem da assinatura antes de autorizar o uso.")
    p.use_signature_image = bool(allow)
    s.flush()
    audit.record(s, actor=actor, actor_id=user_id, ip=ip, action="report.signature.consent", target_type="physician",
                 target_id=p.id, details={"allow": bool(allow)})
    return p


MANAGE = "report.physicians.manage"


def delegate_candidates(s: Session, *, exclude: uuid.UUID | None = None) -> list[dict[str, Any]]:
    """Administradores que o médico pode designar: usuários ativos com a permissão de cadastro de médicos."""
    from vyonix.auth.models import RolePermission, User, UserRole
    q = (select(User).join(UserRole, UserRole.user_id == User.id)
         .join(RolePermission, RolePermission.role_id == UserRole.role_id)
         .where(RolePermission.permission == MANAGE, User.active.is_(True)).distinct().order_by(User.username))
    return [{"id": str(u.id), "username": u.username, "display_name": u.display_name}
            for u in s.execute(q).scalars() if u.id != exclude]


def set_delegate(s: Session, user_id: uuid.UUID, delegate_user_id: uuid.UUID | None, *, actor: str,
                 ip=None) -> Physician:
    """O médico designa (ou remove) o administrador que pode enviar a imagem por ele (sempre pendente de confirmação)."""
    from vyonix.auth.models import User
    p = _physician_of(s, user_id)
    if delegate_user_id is not None and (delegate_user_id == user_id or s.get(User, delegate_user_id) is None or
                                         str(delegate_user_id) not in {c["id"] for c in delegate_candidates(s)}):
        raise ValidationFailed("Usuário designado inválido (precisa ser administrador do cadastro de médicos).")
    p.signature_delegate_user_id = delegate_user_id
    s.flush()
    audit.record(s, actor=actor, actor_id=user_id, ip=ip, action="report.signature.delegate", target_type="physician",
                 target_id=p.id, details={"delegate_user_id": str(delegate_user_id) if delegate_user_id else None})
    return p


def image_for(s: Session, requester_id: uuid.UUID, *, which: str = "active", physician_id: uuid.UUID | None = None,
              key: bytes, actor: str, ip=None) -> bytes:
    """Pré-visualização: o médico vê as próprias (ativa ou pendente); o administrador designado vê só a pendente que
    ele mesmo enviou (auditado). Ninguém mais."""
    if physician_id is None:
        p = _physician_of(s, requester_id)
        img = _latest(s, p.id, which if which in ("active", "pending") else "active")
        admin_view = False
    else:
        p = s.get(Physician, physician_id)
        if p is None:
            raise NotFound("Médico não encontrado.")
        img = _latest(s, p.id, "pending")
        if p.signature_delegate_user_id != requester_id or img is None or img.uploaded_by_id != requester_id:
            raise Forbidden("Sem autorização para ver a imagem da assinatura deste médico.", code="signature_forbidden")
        admin_view = True
    if img is None:
        raise NotFound("Nenhuma imagem.")
    data, _w, _h = decrypt(s, img.id, key=key)
    if admin_view:
        audit.record(s, actor=actor, actor_id=requester_id, ip=ip, action="report.signature.admin_view",
                     target_type="physician", target_id=p.id, details={"sha256": img.sha256})
    return data


def status(s: Session, user_id: uuid.UUID) -> dict[str, Any]:
    p = _physician_of(s, user_id)
    act, pend = _latest(s, p.id, "active"), _latest(s, p.id, "pending")
    hist = s.execute(select(SignatureImage).where(SignatureImage.physician_id == p.id)
                     .order_by(SignatureImage.created_at.desc()).limit(20)).scalars()
    return {"has_image": act is not None, "use_signature_image": p.use_signature_image,
            "uploaded_at": act.created_at.isoformat() if act else None,
            "pending": None if pend is None else {"uploaded_by": pend.uploaded_by,
                                                  "uploaded_at": pend.created_at.isoformat()},
            "delegate_user_id": str(p.signature_delegate_user_id) if p.signature_delegate_user_id else None,
            "history": [{"status": h.status, "uploaded_by": h.uploaded_by, "uploaded_at": h.created_at.isoformat(),
                         "confirmed_at": h.confirmed_at.isoformat() if h.confirmed_at else None,
                         "ended_at": h.ended_at.isoformat() if h.ended_at else None, "sha256": h.sha256[:12]}
                        for h in hist]}


def for_release(s: Session, physician: Physician) -> uuid.UUID | None:
    """Imagem a registrar na versão liberada: só a **ativa** do próprio médico e só com o uso autorizado."""
    if not physician.use_signature_image:
        return None
    img = _latest(s, physician.id, "active")
    return img.id if img else None
