"""Chaves **públicas** de emissão aceitas pelo VYONIX DICOM Print (nenhuma chave privada aqui).

Rotação de chaves: o VYONIX License Manager gera uma nova chave (Segurança → Chaves de emissão) e
exporta a linha pública no formato abaixo. A nova chave é acrescentada aqui e distribuída em uma
**atualização oficial**; as licenças antigas continuam válidas enquanto a chave anterior constar
da lista. Remover uma chave invalida todas as licenças assinadas por ela.

A chave de homologação ``hml-2026`` (formato 1) foi retirada: suas licenças não são aceitas.
"""

PUBLIC_KEYS: dict[str, str] = {
    # vyx-2026-01 — impressão digital 44DE:3181:0922:95DC:C478:0FDC
    "vyx-2026-01": "bfcfe838e8b1675d69df1d10f8fc314d81c0be64d73aeb70169cd9fffad0862a",
}
