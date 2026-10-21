"""Senhas com scrypt (``hashlib``, OpenSSL) e sal aleatório — mesmo esquema do License Manager."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from vyonix.errors import ValidationFailed

_N, _R, _P = 2 ** 14, 8, 1
MIN_LENGTH = 10


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        calc = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password(secrets.token_urlsafe(16))   # tempo constante para usuário inexistente


def validate_password(password: str) -> None:
    if len(password or "") < MIN_LENGTH:
        raise ValidationFailed(f"A senha deve ter pelo menos {MIN_LENGTH} caracteres.")
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        raise ValidationFailed("A senha deve misturar letras maiúsculas, minúsculas e números.")
