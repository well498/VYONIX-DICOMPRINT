"""JSON canônico (bytes estáveis para assinar) e Base64 URL-safe sem preenchimento."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64d(text: str) -> bytes:
    text = "".join(str(text).split())
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(obj: Any) -> bytes:
    return hashlib.sha256(canonical(obj)).digest()


def check_code(data: bytes) -> str:
    """Dígitos de conferência (detecção de erro de cópia, não é proteção)."""
    return hashlib.sha256(data).hexdigest()[:8].upper()
