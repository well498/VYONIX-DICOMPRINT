"""Usuários e perfis do VYONIX (VYONIX Reception e ações técnicas).

Perfis:

* **Administrador** — tudo, inclusive usuários.
* **Técnico** — configurações técnicas no programa (regras DICOM, impressoras, calibração) e a
  recepção.
* **Supervisor da recepção** — recepção, reimpressões (impressão duplicada), cancelamento de
  entrega e relatórios.
* **Recepcionista** — pesquisa, impressão do exame (primeira impressão / sob demanda), IMPRIMIR
  AGORA e controle de retirada.

Senhas com ``hashlib.scrypt`` e sal aleatório; bloqueio de 15 minutos após 5 tentativas erradas.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from app.core.errors import ValidationError
from app.utils.timeutil import from_iso, to_iso, utc_now, utc_now_iso

ROLES = {"admin": "Administrador", "technician": "Técnico", "supervisor": "Supervisor da recepção",
         "receptionist": "Recepcionista"}
PERMS = {
    "reception": {"admin", "technician", "supervisor", "receptionist"},
    "print": {"admin", "technician", "supervisor", "receptionist"},
    "print_now": {"admin", "technician", "supervisor", "receptionist"},
    "reprint": {"admin", "technician", "supervisor"},
    "pickup": {"admin", "technician", "supervisor", "receptionist"},
    "pickup_cancel": {"admin", "supervisor"},
    "reports": {"admin", "technician", "supervisor"},
    "technical": {"admin", "technician"},
    "users": {"admin"},
}
MAX_FAILED = 5
LOCK_MINUTES = 15
_N, _R, _P = 2 ** 14, 8, 1


class AuthError(ValidationError):
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
    if len(password or "") < 8:
        raise ValidationError("A senha deve ter pelo menos 8 caracteres.")
    if password.isdigit() or password.isalpha():
        raise ValidationError("A senha deve misturar letras e números.")


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str
    role: str
    must_change: bool = False

    @property
    def role_label(self) -> str:
        return ROLES[self.role]

    def can(self, perm: str) -> bool:
        return self.role in PERMS.get(perm, set())

    def require(self, perm: str) -> None:
        if not self.can(perm):
            raise ValidationError(f"Seu perfil ({self.role_label}) não permite esta operação.")

    @property
    def actor(self) -> str:
        return f"usuario:{self.username}"

    def public(self) -> dict[str, Any]:
        return {"username": self.username, "name": self.display_name, "role": self.role, "role_label": self.role_label,
                "must_change": self.must_change,
                "perms": sorted(p for p, roles in PERMS.items() if self.role in roles)}


class UserService:
    def __init__(self, db, events) -> None:
        self.db = db
        self.events = events

    def _row(self, r) -> User:
        return User(r["id"], r["username"], r["display_name"], r["role"], bool(r["must_change"]))

    def list(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.connection().execute(
            "SELECT id, username, display_name, role, active, must_change, created_at, last_login_at FROM users "
            "ORDER BY username")]

    def get(self, user_id: int) -> User | None:
        r = self.db.connection().execute("SELECT * FROM users WHERE id = ? AND active = 1", (user_id,)).fetchone()
        return self._row(r) if r else None

    def count(self) -> int:
        return int(self.db.connection().execute("SELECT COUNT(*) FROM users WHERE active = 1").fetchone()[0])

    def create(self, username: str, display_name: str, role: str, password: str, *, actor: str,
               must_change: bool = True) -> int:
        username = (username or "").strip()
        if not username or len(username) > 40 or any(c.isspace() for c in username):
            raise ValidationError("Usuário inválido (sem espaços, até 40 caracteres).")
        if role not in ROLES:
            raise ValidationError("Perfil inválido.")
        validate_password(password)
        try:
            cur = self.db.connection().execute(
                """INSERT INTO users(username, display_name, role, pw_hash, must_change, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (username, (display_name or username).strip(), role, hash_password(password), int(must_change),
                 utc_now_iso()))
        except Exception as exc:  # noqa: BLE001
            if "UNIQUE" in str(exc):
                raise ValidationError("Já existe um usuário com esse nome.") from exc
            raise
        self.events.add(level="INFO", category="security", action="user.create",
                        message=f"Usuário {username} ({ROLES[role]}) criado.", actor=actor)
        return int(cur.lastrowid)

    def update(self, user_id: int, *, role: str | None = None, active: bool | None = None,
               display_name: str | None = None, actor: str) -> None:
        conn = self.db.connection()
        r = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if r is None:
            raise ValidationError("Usuário não encontrado.")
        new_role = role or r["role"]
        if new_role not in ROLES:
            raise ValidationError("Perfil inválido.")
        new_active = r["active"] if active is None else int(active)
        if r["role"] == "admin" and (new_role != "admin" or not new_active):
            n = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND id <> ?",
                             (user_id,)).fetchone()[0]
            if n == 0:
                raise ValidationError("Mantenha pelo menos um administrador ativo.")
        conn.execute("UPDATE users SET role = ?, active = ?, display_name = ? WHERE id = ?",
                     (new_role, new_active, display_name or r["display_name"], user_id))
        if not new_active:
            conn.execute("DELETE FROM web_sessions WHERE user_id = ?", (user_id,))
        self.events.add(level="INFO", category="security", action="user.update",
                        message=f"Usuário {r['username']}: perfil {ROLES[new_role]}, "
                                f"{'ativo' if new_active else 'inativo'}.", actor=actor)

    def set_password(self, user_id: int, password: str, *, actor: str, must_change: bool) -> None:
        validate_password(password)
        conn = self.db.connection()
        conn.execute("UPDATE users SET pw_hash = ?, must_change = ?, failed = 0, locked_until = NULL WHERE id = ?",
                     (hash_password(password), int(must_change), user_id))
        conn.execute("DELETE FROM web_sessions WHERE user_id = ?", (user_id,))
        self.events.add(level="INFO", category="security", action="user.password",
                        message=f"Senha do usuário #{user_id} alterada.", actor=actor)

    def authenticate(self, username: str, password: str, *, address: str | None = None) -> User:
        conn = self.db.connection()
        r = conn.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),)).fetchone()
        if r is None or not r["active"]:
            self.events.add(level="WARNING", category="security", action="login.failed",
                            message=f"Acesso negado: usuário inexistente ou inativo ({address or '—'}).",
                            actor=f"usuario:{username}")
            raise AuthError("Usuário ou senha incorretos.")
        if r["locked_until"] and from_iso(r["locked_until"]) > utc_now():
            raise AuthError("Usuário bloqueado temporariamente por tentativas incorretas.")
        if not check_password(password or "", r["pw_hash"]):
            failed = r["failed"] + 1
            locked = to_iso(utc_now() + timedelta(minutes=LOCK_MINUTES)) if failed >= MAX_FAILED else None
            conn.execute("UPDATE users SET failed = ?, locked_until = ? WHERE id = ?",
                         (0 if locked else failed, locked, r["id"]))
            self.events.add(level="WARNING", category="security", action="login.failed",
                            message=f"Senha incorreta para {r['username']} ({address or '—'})"
                                    + ("; usuário bloqueado por 15 minutos" if locked else "") + ".",
                            actor=f"usuario:{r['username']}")
            raise AuthError("Usuário ou senha incorretos." + (" Usuário bloqueado por 15 minutos." if locked else ""))
        conn.execute("UPDATE users SET failed = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
                     (utc_now_iso(), r["id"]))
        self.events.add(level="INFO", category="security", action="login",
                        message=f"Acesso de {r['username']} ({ROLES[r['role']]}) a partir de {address or '—'}.",
                        actor=f"usuario:{r['username']}")
        return self._row(r)
