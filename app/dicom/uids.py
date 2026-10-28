"""Geração centralizada dos UIDs DICOM criados pelo próprio VYONIX DICOM Print (BKL-10).

Regras:

* **UIDs recebidos nunca são gerados nem alterados aqui**: os objetos que chegam por C-STORE são guardados byte a
  byte (``app/dicom/storage.py``) e os UIDs de instância informados pela modalidade no N-CREATE do Print são mantidos.
* Só objetos **novos** recebem UID: Film Session/Film Box/Presentation LUT quando a modalidade não informa o UID,
  Image Box, as imagens Secondary Capture derivadas do filme (SOP, série por filme e estudo por associação), o filme
  de teste da interface e a imagem do autoteste.
* Formato: ``2.25.<inteiro do UUID>`` (PS3.5 §B.2) — não depende de raiz registrada por terceiros, é único sem
  coordenação, funciona offline e tem no máximo 44 caracteres (limite DICOM: 64). Antes da correção os UIDs
  usavam a raiz ``1.2.826.0.1.3680043.8.498`` (registrada para o pydicom, não para a VYONIX) e chegavam a 64
  caracteres.
* UIDs de **classe SOP** (Basic Film Session, Secondary Capture etc.) são constantes do padrão e não passam por aqui.
"""

from __future__ import annotations

import re
import uuid

MAX_LEN = 64
_STRICT = re.compile(r"^(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*$")


def new_uid() -> str:
    """UID novo, único e conforme a PS3.5 (§9.1 e §B.2)."""
    return f"2.25.{uuid.uuid4().int}"


def is_strict(uid: str) -> bool:
    """Conformidade estrita com a PS3.5 §9.1 (inclusive sem zero à esquerda nos componentes)."""
    return bool(uid) and len(uid) <= MAX_LEN and bool(_STRICT.match(uid))
