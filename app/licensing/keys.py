"""Chaves **públicas** aceitas para verificar licenças (a chave privada nunca está aqui).

``hml-2026`` é a chave de homologação. Antes da distribuição comercial, gere a chave de produção com
``python -m license_admin keygen --key-id prod-1 --out <pasta segura>`` e acrescente a chave pública
abaixo (manter a anterior permite que licenças antigas continuem válidas; removê-la as revoga).
"""

PUBLIC_KEYS: dict[str, str] = {
    "hml-2026": "b64541ef476b3b75bdbfed2fc0d9c7a5cb4df6b7fda6fea04197387085a6de5a",
}
