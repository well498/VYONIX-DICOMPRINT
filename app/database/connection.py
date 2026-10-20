"""Acesso ao SQLite.

* Uma conexão por *thread* (o SQLite não deve compartilhar conexões entre threads
  em uso simultâneo); todas são fechadas em ``close()``.
* Modo *autocommit* do driver (``isolation_level=None``) com transações explícitas
  via ``transaction()`` — inclusive aninhadas (``SAVEPOINT``).
* WAL + ``synchronous=FULL``: prioriza durabilidade da fila de trabalhos.
* ``json_valid`` (usada nas restrições CHECK do esquema) é garantida em qualquer SQLite: se a
  biblioteca SQLite não trouxer as funções JSON (caso de compilações antigas, como a do
  Python 3.8 para Windows), uma implementação equivalente em Python é registrada.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.core.errors import DatabaseError, DatabaseIntegrityError
from app.utils.logging_setup import get_logger

log = get_logger("database")

ENV_FORCE_PY_JSON = "VYONIX_FORCE_PY_JSON"  # testes: força a implementação em Python


def _json_valid(text) -> int:
    """Equivalente a ``json_valid(X)`` do SQLite para textos (NULL → NULL)."""
    if text is None:
        return None  # type: ignore[return-value]
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError:
            return 0
    if not isinstance(text, str):
        return 1 if isinstance(text, (int, float)) else 0
    try:
        json.loads(text)
        return 1
    except ValueError:
        return 0


def ensure_json_functions(conn: sqlite3.Connection, *, force_python: bool = False) -> str:
    """Garante ``json_valid`` na conexão. Retorna ``"native"`` ou ``"python"``."""
    if not force_python:
        try:
            conn.execute("SELECT json_valid('{}')").fetchone()
            return "native"
        except sqlite3.OperationalError:
            pass
    try:
        conn.create_function("json_valid", 1, _json_valid, deterministic=True)
    except (TypeError, sqlite3.NotSupportedError):  # SQLite muito antigo sem 'deterministic'
        conn.create_function("json_valid", 1, _json_valid)
    return "python"


class Database:
    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms
        self._local = threading.local()
        self._lock = threading.Lock()
        self._connections: list[sqlite3.Connection] = []
        self._closed = False
        self.json_mode = "unknown"

    # ------------------------------------------------------------------
    def connection(self) -> sqlite3.Connection:
        if self._closed:
            raise DatabaseError("Banco de dados já foi fechado.")
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._open()
            self._local.conn = conn
            self._local.depth = 0
            with self._lock:
                self._connections.append(conn)
        return conn

    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(
                str(self.path),
                timeout=self.busy_timeout_ms / 1000,
                isolation_level=None,
                check_same_thread=False,  # cada thread usa a sua; o fechamento é centralizado
            )
            conn.row_factory = sqlite3.Row
            self.json_mode = ensure_json_functions(
                conn, force_python=os.environ.get(ENV_FORCE_PY_JSON) == "1")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = FULL")
            return conn
        except sqlite3.OperationalError as exc:  # permissão, bloqueio, caminho inválido
            if conn is not None:
                conn.close()
            raise DatabaseError(f"Não foi possível abrir o banco {self.path}: {exc}") from exc
        except sqlite3.DatabaseError as exc:     # conteúdo do arquivo inválido
            if conn is not None:
                conn.close()
            raise DatabaseIntegrityError(
                f"O arquivo do banco {self.path} está corrompido ou não é um banco SQLite: {exc}. "
                "Restaure um backup da pasta 'backups'.") from exc

    # ------------------------------------------------------------------
    @contextmanager
    def transaction(self, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """Transação atômica. Chamadas aninhadas usam SAVEPOINT."""
        conn = self.connection()
        depth = self._local.depth
        savepoint = f"sp_{depth}"
        if depth == 0:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        else:
            conn.execute(f"SAVEPOINT {savepoint}")
        self._local.depth = depth + 1
        try:
            yield conn
        except BaseException:
            self._local.depth = depth
            if depth == 0:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
            else:
                conn.execute(f"ROLLBACK TO {savepoint}")
                conn.execute(f"RELEASE {savepoint}")
            raise
        else:
            self._local.depth = depth
            if depth == 0:
                conn.execute("COMMIT")
            else:
                conn.execute(f"RELEASE {savepoint}")

    # ------------------------------------------------------------------
    def quick_check(self) -> list[str]:
        rows = self.connection().execute("PRAGMA quick_check").fetchall()
        return [r[0] for r in rows]

    def assert_integrity(self) -> None:
        try:
            result = self.quick_check()
        except sqlite3.DatabaseError as exc:
            raise DatabaseIntegrityError(f"Banco de dados ilegível: {exc}") from exc
        if result != ["ok"]:
            raise DatabaseIntegrityError(
                "Falha na verificação de integridade do banco: " + "; ".join(result[:5])
            )

    def backup_to(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(destination))
        try:
            self.connection().backup(target)
        finally:
            target.close()
        log.info("Backup do banco gerado", extra={"backup_file": str(destination)})
        return destination

    def close_thread_connection(self) -> None:
        """Fecha a conexão da thread atual (threads de curta duração, ex.: associações DICOM)."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return
        with self._lock:
            if conn in self._connections:
                self._connections.remove(conn)
        try:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            conn.close()
        except sqlite3.Error:  # pragma: no cover
            pass
        self._local.conn = None
        self._local.depth = 0

    def open_connections(self) -> int:
        with self._lock:
            return len(self._connections)

    def close(self) -> None:
        with self._lock:
            for conn in self._connections:
                try:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    conn.close()
                except sqlite3.Error:  # pragma: no cover - melhor esforço no encerramento
                    pass
            self._connections.clear()
            self._closed = True
        self._local = threading.local()
