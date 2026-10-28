"""Ponto de integração da futura assinatura digital **PAdES / ICP-Brasil** do laudo (BLK-14, ainda não implementada).

Três coisas distintas, que o VYONIX nunca apresenta como equivalentes:

1. **confirmação por senha** — identifica quem libera o laudo no sistema (implementada);
2. **imagem da assinatura manuscrita** — elemento visual autorizado pelo médico (implementada, ``signature.py``);
3. **assinatura digital PAdES com certificado ICP-Brasil** — validade jurídica do PDF (esta interface; depende do
   certificado do médico, A1 ou A3, de carimbo do tempo e de validação regulatória; **não disponível**).

Quando implementada, a assinatura PAdES será aplicada **sobre o PDF já gerado** (com ou sem a representação visual
da imagem manuscrita, conforme o modelo), sem alterar as versões imutáveis do laudo. Até lá, ``sign`` recusa.
"""

from __future__ import annotations

from dataclasses import dataclass

from vyonix.errors import Conflict

MODES = {
    "draft": "Rascunho — não finalizado, sem assinatura",
    "password": "Liberado com confirmação de senha (não é assinatura digital)",
    "handwritten_image": "Liberado com confirmação de senha + imagem da assinatura manuscrita (elemento visual; "
                         "não é assinatura digital)",
    "pades_icp": "Assinado digitalmente PAdES/ICP-Brasil (não disponível — BLK-14)",
}


@dataclass(frozen=True)
class PadesStatus:
    available: bool
    reason: str


def status() -> PadesStatus:
    return PadesStatus(False, "Assinatura digital PAdES/ICP-Brasil não implementada (BLK-14): exige certificado "
                              "ICP-Brasil do médico, carimbo do tempo e validação regulatória.")


def sign(pdf: bytes, *, physician_id, certificate=None) -> bytes:  # noqa: ARG001 - contrato futuro
    """Contrato futuro: devolve o PDF assinado (PAdES-B/T). Hoje sempre recusa, nunca finge assinar."""
    raise Conflict(status().reason, code="pades_not_available")


def mode_of(version: dict) -> str:
    """Classifica uma versão do laudo para exibição (nunca devolve ``pades_icp`` sem assinatura PAdES real)."""
    if version.get("kind") == "draft":
        return "draft"
    if version.get("pades"):
        return "pades_icp"
    return "handwritten_image" if version.get("signature_image_id") or version.get("has_signature_image") \
        else "password"
