"""Protocolo de licenciamento VYONIX — único código compartilhado entre os dois aplicativos.

* ``codec``: JSON canônico e Base64 URL-safe.
* ``formats``: solicitação de ativação, licença, revalidação de horário, lista de revogação e
  diagnóstico — estrutura, campos obrigatórios e validação.
* ``crypto``: assinatura e verificação Ed25519 e verificação da prova de posse do TPM, sempre com a
  biblioteca ``cryptography`` (nenhuma primitiva criptográfica própria).

O VYONIX DICOM Print usa apenas as funções de **verificação**; a emissão (chave privada) existe
somente no VYONIX License Manager.
"""

PROTOCOL_VERSION = 2
