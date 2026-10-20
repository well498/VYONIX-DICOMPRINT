"""Controle de acesso administrativo (§16).

* Senha de administrador opcional, guardada como PBKDF2-HMAC-SHA256 (600 mil iterações, sal
  aleatório de 16 bytes); a senha em si nunca é gravada.
* Sem senha definida, a administração fica livre e o Dashboard mostra um alerta.
* Com senha, as funções protegidas exigem desbloqueio; o desbloqueio expira após
  ``security.lock_minutes`` sem uso.
* Cinco senhas erradas seguidas bloqueiam novas tentativas por 60 segundos.
* Todas as tentativas e alterações são auditadas.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from typing import Any, Callable

from app.core.errors import VyonixError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.database.repositories.settings_repo import SettingsRepository

KEY = "security.admin"
ITERATIONS = 600_000
MIN_LENGTH = 8
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60


class AccessDenied(VyonixError):
    """A operação exige desbloqueio administrativo."""


def _hash(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


class AdminAccess:
    def __init__(self, db: Database, events: EventRepository,
                 lock_minutes: Callable[[], int], clock: Callable[[], float] = time.monotonic) -> None:
        self.db = db
        self.repo = SettingsRepository(db)
        self.events = events
        self._lock_minutes = lock_minutes
        self._clock = clock
        self._lock = threading.Lock()
        self._unlocked_until = 0.0
        self._failures = 0
        self._blocked_until = 0.0

    # --------------------------------------------------------------- estado
    def has_password(self) -> bool:
        record = self.repo.get_raw(KEY)
        return bool(record and record.get("hash"))

    def is_unlocked(self) -> bool:
        if not self.has_password():
            return True
        with self._lock:
            return self._clock() < self._unlocked_until

    def touch(self) -> None:
        """Renova o desbloqueio em uso (chamado a cada operação protegida)."""
        with self._lock:
            if self._clock() < self._unlocked_until:
                self._unlocked_until = self._clock() + self._lock_minutes() * 60

    def require(self, action: str) -> None:
        if not self.is_unlocked():
            raise AccessDenied(f"A ação \"{action}\" exige a senha de administrador.")
        self.touch()

    def lock(self) -> None:
        with self._lock:
            self._unlocked_until = 0.0

    # --------------------------------------------------------------- senha
    def verify(self, password: str) -> bool:
        record: dict[str, Any] | None = self.repo.get_raw(KEY)
        if not record or not record.get("hash"):
            return True
        salt = bytes.fromhex(record["salt"])
        expected = bytes.fromhex(record["hash"])
        return hmac.compare_digest(_hash(password, salt, int(record["iterations"])), expected)

    def unlock(self, password: str, *, actor: str) -> bool:
        with self._lock:
            if self._clock() < self._blocked_until:
                raise AccessDenied("Muitas tentativas erradas. Aguarde um minuto e tente novamente.")
        ok = self.verify(password)
        with self._lock:
            if ok:
                self._failures = 0
                self._unlocked_until = self._clock() + self._lock_minutes() * 60
            else:
                self._failures += 1
                if self._failures >= MAX_FAILURES:
                    self._blocked_until = self._clock() + LOCKOUT_SECONDS
                    self._failures = 0
        self.events.add(level="INFO" if ok else "WARNING", category=Category.SECURITY,
                        action="admin.unlock" if ok else "admin.unlock_failed",
                        message="Administração desbloqueada." if ok else "Senha de administrador incorreta.",
                        actor=actor)
        return ok

    def set_password(self, new_password: str, *, current: str | None, actor: str) -> None:
        if self.has_password() and not self.verify(current or ""):
            self.events.add(level="WARNING", category=Category.SECURITY, action="admin.password_failed",
                            message="Tentativa de alterar a senha com a senha atual incorreta.", actor=actor)
            raise AccessDenied("Senha atual incorreta.")
        if len(new_password) < MIN_LENGTH:
            raise VyonixError(f"A senha deve ter pelo menos {MIN_LENGTH} caracteres.")
        salt = secrets.token_bytes(16)
        record = {"algorithm": "pbkdf2_sha256", "iterations": ITERATIONS, "salt": salt.hex(),
                  "hash": _hash(new_password, salt, ITERATIONS).hex()}
        with self.db.transaction():
            self.repo.upsert(KEY, record, actor)
            self.events.add(level="INFO", category=Category.SECURITY, action="admin.password_set",
                            message="Senha de administrador definida.", actor=actor)
        with self._lock:
            self._unlocked_until = self._clock() + self._lock_minutes() * 60

    def clear_password(self, *, current: str, actor: str) -> None:
        if not self.verify(current):
            raise AccessDenied("Senha atual incorreta.")
        with self.db.transaction():
            self.repo.delete(KEY)
            self.events.add(level="WARNING", category=Category.SECURITY, action="admin.password_removed",
                            message="Senha de administrador removida.", actor=actor)
