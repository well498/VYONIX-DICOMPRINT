"""Autenticação administrativa e controle de permissões do License Manager.

Senhas: ``hashlib.scrypt`` (OpenSSL) com sal aleatório; bloqueio temporário após tentativas
erradas. Papéis:

* ``admin`` (administrador comercial) — tudo, inclusive chaves de emissão, usuários, revogação,
  políticas comerciais, backup e restauração;
* ``financial`` (operador financeiro) — Gestão Comercial: pagamentos, cobranças, carência, suspensão
  e reativação (as ações configuradas exigem a confirmação de um administrador comercial);
* ``support`` (suporte técnico) — reativação por troca de hardware/reinstalação, revalidação e
  autorizações offline; sem ações financeiras;
* ``issuer`` (emissor) — clientes, solicitações, emissão, renovação, reativação e revalidação;
* ``viewer`` (consulta) — somente leitura.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

ROLES = {"admin": "Administrador comercial", "financial": "Operador financeiro", "support": "Suporte técnico",
         "issuer": "Emissor", "viewer": "Consulta"}
PERMS = {
    "view": {"admin", "financial", "support", "issuer", "viewer"},
    "customers": {"admin", "issuer", "financial"},
    "issue": {"admin", "issuer", "support"},
    "revalidate": {"admin", "issuer", "support"},
    "revoke": {"admin"},
    "products": {"admin"},
    "keys": {"admin"},
    "users": {"admin"},
    "backup": {"admin"},
    "restore": {"admin"},
    "anonymize": {"admin"},
}
MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 10
_N, _R, _P = 2 ** 14, 8, 1


class AuthError(Exception):
    pass


class PermissionDenied(Exception):
    pass


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


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"A senha deve ter pelo menos {MIN_PASSWORD} caracteres.")
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        raise AuthError("A senha deve misturar letras maiúsculas, minúsculas e números.")


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str
    role: str
    must_change: bool = False

    def can(self, perm: str) -> bool:
        return self.role in PERMS.get(perm, set())

    def require(self, perm: str) -> None:
        if not self.can(perm):
            raise PermissionDenied(f"O usuário {self.username} ({ROLES[self.role]}) não tem permissão para esta "
                                   "operação.")


def now() -> datetime:
    return datetime.now(timezone.utc)


def lock_until() -> datetime:
    return now() + timedelta(minutes=LOCK_MINUTES)
