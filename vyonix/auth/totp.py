"""TOTP (RFC 6238: HMAC-SHA1, passo de 30 s, 6 dígitos), compatível com Google Authenticator,
Microsoft Authenticator e similares. Usa ``hmac``/``hashlib`` da biblioteca padrão; o segredo é
guardado cifrado (AES-256-GCM da biblioteca ``cryptography``) com a chave local do CORE."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

STEP = 30
DIGITS = 6


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret_b32: str) -> bytes:
    s = secret_b32.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret_b32: str, step: int) -> str:
    mac = hmac.new(_key(secret_b32), struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    n = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(n).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP)


def verify(secret_b32: str, code: str, *, last_step: int = 0, now: float | None = None, window: int = 1) -> int | None:
    """Passo aceito (para impedir reuso) ou ``None``. Aceita ±``window`` passos de diferença de relógio."""
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return None
    base = current_step(now)
    for step in range(base - window, base + window + 1):
        if step > last_step and hmac.compare_digest(code_at(secret_b32, step), code):
            return step
    return None


def provisioning_uri(secret_b32: str, account: str, issuer: str = "VYONIX") -> str:
    label = urllib.parse.quote(f"{issuer}:{account}")
    q = urllib.parse.urlencode({"secret": secret_b32, "issuer": issuer, "digits": DIGITS, "period": STEP})
    return f"otpauth://totp/{label}?{q}"


def seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def unseal(key: bytes, blob: bytes, aad: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key).decrypt(blob[:12], blob[12:], aad)
