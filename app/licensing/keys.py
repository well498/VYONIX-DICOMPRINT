"""Chaves **públicas** de emissão aceitas pelo VYONIX DICOM Print (nenhuma chave privada aqui).

Rotação de chaves: o VYONIX License Manager gera uma nova chave (Segurança → Chaves de emissão) e
exporta a linha pública no formato abaixo. A nova chave é acrescentada aqui e distribuída em uma
**atualização oficial**; as licenças antigas continuam válidas enquanto a chave anterior constar
da lista. Remover uma chave invalida todas as licenças assinadas por ela.

Escopo: cada chave só é aceita para os documentos do seu escopo (``KEY_SCOPES``). A chave do
VYONIX License Server assina somente autorizações de uso (validação online); ela não emite licenças,
revalidações nem listas de revogação — o vazamento dessa chave não permite criar licenças.

A chave de homologação ``hml-2026`` (formato 1) foi retirada: suas licenças não são aceitas.

Chave comprometida (procedimento de incidente, ``docs/security/``): sem invalidar os clientes, a chave
entra em ``RESTRICTED_KEYS`` com a lista dos SHA-256 dos documentos que ela realmente assinou (exportada
pelo License Manager em Segurança → Chaves de emissão → "Exportar documentos legítimos"). A partir da
versão que traz a lista, um documento novo assinado por essa chave — mesmo com assinatura válida — é
recusado; os documentos legítimos continuam aceitos até serem substituídos pelos da chave nova.
Hashes não são segredo: podem ficar no código.
"""

import hashlib

PUBLIC_KEYS: dict[str, str] = {
    # vyx-2026-01 — VYONIX License Manager — impressão digital 44DE:3181:0922:95DC:C478:0FDC
    "vyx-2026-01": "bfcfe838e8b1675d69df1d10f8fc314d81c0be64d73aeb70169cd9fffad0862a",
    # vyx-srv-2026-01 — VYONIX License Server — impressão digital 7265:AF0F:E7A8:B327:084F:7BDC
    "vyx-srv-2026-01": "f5085a8d0146ae48264178d73e846de93a68cc80c5b0a5025da7fe9f545443a3",
}

KEY_SCOPES: dict[str, tuple[str, ...]] = {
    "vyx-2026-01": ("license", "authorization", "revalidation", "revocation"),
    "vyx-srv-2026-01": ("authorization",),
}

# chave → SHA-256 (hex) do conteúdo assinado (``SignedDoc.signed``) de cada documento legítimo.
# Vazio = nenhuma chave sob restrição.
RESTRICTED_KEYS: dict[str, frozenset[str]] = {}


def signed_digest(signed: bytes) -> str:
    return hashlib.sha256(signed).hexdigest()


def key_policy_error(key_id: str, signed: bytes,
                     restricted: dict[str, frozenset[str]] | None = None) -> str | None:
    """Motivo da recusa quando a chave está sob restrição e o documento não é um dos legítimos."""
    table = RESTRICTED_KEYS if restricted is None else restricted
    allowed = table.get(key_id)
    if allowed is None:
        return None
    if signed_digest(signed) in allowed:
        return None
    return (f"A chave {key_id} foi retirada por segurança e este documento não consta da lista de documentos "
            "legítimos emitidos por ela. Peça ao fornecedor um documento emitido com a chave atual.")
