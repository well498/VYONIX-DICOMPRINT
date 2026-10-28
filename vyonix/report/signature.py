"""TELELAUDO T5 — imagem da assinatura manuscrita (elemento **somente visual**).

Regras:
* Só o **próprio médico** envia, troca, autoriza ou revoga (a API usa sempre o médico do usuário autenticado; não
  há parâmetro de médico). Administradores não enviam, não trocam, não baixam e não aplicam a imagem de outro.
* Cifrada em repouso com AES-GCM (chave ``report_signature_key`` do cofre local; dado associado = organização +
  médico), sem URL e sem download pela API; decifrada só para desenhar o PDF de laudo que ele mesmo liberou.
* Aplicada apenas se o médico autorizou (``use_signature_image``) **no momento da liberação**: a versão liberada
  registra qual imagem foi usada. Revogar não altera laudos já liberados; vale para os próximos.
* Nunca substitui a liberação com confirmação de senha (nem a assinatura digital futura, BLK-14).
"""

from __future__ import annotations

import hashlib
import io
import os
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.errors import Forbidden, NotFound, ValidationFailed
from vyonix.report.models import Physician, SignatureImage

MAX_BYTES = 512 * 1024
KEY_NAME = "report_signature_key"


def _aad(img_tenant: uuid.UUID, physician_id: uuid.UUID) -> bytes:
    return b"vyonix-signature:" + str(img_tenant).encode() + b":" + str(physician_id).encode()


def _own(s: Session, user_id: uuid.UUID) -> Physician:
    p = s.execute(select(Physician).where(Physician.user_id == user_id)).scalar_one_or_none()
    if p is None:
        raise Forbidden("Somente o próprio médico gerencia a imagem da assinatura.", code="physician_required")
    return p


def upload(s: Session, user_id: uuid.UUID, data: bytes, *, key: bytes, actor: str, ip=None) -> SignatureImage:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from PIL import Image
    p = _own(s, user_id)
    if not data or len(data) > MAX_BYTES:
        raise ValidationFailed("Imagem vazia ou acima de 512 KB.")
    if not (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"):
        raise ValidationFailed("Use PNG ou JPEG (de preferência PNG com fundo transparente).")
    try:
        Image.MAX_IMAGE_PIXELS = 4000 * 4000
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            im.load()
    except Exception as exc:  # noqa: BLE001
        raise ValidationFailed(f"Imagem inválida ou danificada ({type(exc).__name__}).") from None
    for old in s.execute(select(SignatureImage).where(SignatureImage.physician_id == p.id,
                                                      SignatureImage.active.is_(True))).scalars():
        old.active = False
    nonce = os.urandom(12)
    img = SignatureImage(physician_id=p.id, nonce=nonce, sha256=hashlib.sha256(data).hexdigest(), width=w, height=h,
                         active=True, ciphertext=b"")
    s.add(img)
    s.flush()
    img.ciphertext = AESGCM(key).encrypt(nonce, data, _aad(img.tenant_id, p.id))
    s.flush()
    audit.record(s, actor=actor, actor_id=user_id, ip=ip, action="report.signature.upload", target_type="physician",
                 target_id=p.id, details={"sha256": img.sha256})
    return img


def set_consent(s: Session, user_id: uuid.UUID, allow: bool, *, actor: str, ip=None) -> Physician:
    p = _own(s, user_id)
    if allow and _active(s, p.id) is None:
        raise ValidationFailed("Envie a imagem da assinatura antes de autorizar o uso.")
    p.use_signature_image = bool(allow)
    s.flush()
    audit.record(s, actor=actor, actor_id=user_id, ip=ip, action="report.signature.consent", target_type="physician",
                 target_id=p.id, details={"allow": bool(allow)})
    return p


def _active(s: Session, physician_id: uuid.UUID) -> SignatureImage | None:
    return s.execute(select(SignatureImage).where(SignatureImage.physician_id == physician_id,
                                                  SignatureImage.active.is_(True))).scalar_one_or_none()


def status(s: Session, user_id: uuid.UUID) -> dict[str, Any]:
    p = _own(s, user_id)
    img = _active(s, p.id)
    return {"has_image": img is not None, "use_signature_image": p.use_signature_image,
            "uploaded_at": img.created_at.isoformat() if img else None}


def for_release(s: Session, physician: Physician) -> uuid.UUID | None:
    """Imagem a registrar na versão liberada: só se o médico autorizou e tem imagem ativa."""
    if not physician.use_signature_image:
        return None
    img = _active(s, physician.id)
    return img.id if img else None


def decrypt(s: Session, image_id: uuid.UUID, *, key: bytes) -> tuple[bytes, int, int]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    img = s.get(SignatureImage, image_id)
    if img is None:
        raise NotFound("Imagem de assinatura não encontrada.")
    data = AESGCM(key).decrypt(img.nonce, img.ciphertext, _aad(img.tenant_id, img.physician_id))
    if hashlib.sha256(data).hexdigest() != img.sha256:
        raise ValidationFailed("Imagem de assinatura com integridade violada.")
    return data, img.width, img.height
