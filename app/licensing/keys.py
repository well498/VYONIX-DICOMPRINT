"""Chaves **públicas** de emissão aceitas pelo VYONIX DICOM Print (nenhuma chave privada aqui).

Rotação de chaves: o VYONIX License Manager gera uma nova chave (Segurança → Chaves de emissão) e
exporta a linha pública no formato abaixo. A nova chave é acrescentada aqui e distribuída em uma
**atualização oficial**; as licenças antigas continuam válidas enquanto a chave anterior constar
da lista. Remover uma chave invalida todas as licenças assinadas por ela.

Escopo: cada chave só é aceita para os documentos do seu escopo (``KEY_SCOPES``). A chave do
VYONIX License Server assina somente autorizações de uso (validação online); ela não emite licenças,
revalidações nem listas de revogação — o vazamento dessa chave não permite criar licenças.

A chave de homologação ``hml-2026`` (formato 1) foi retirada: suas licenças não são aceitas.
"""

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
