"""Banco de dados do VYONIX License Server (SQLite, migrações, auditoria encadeada)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from vyonix_protocol.codec import canonical
from vyonix_commercial.schema import DEFAULT_PLANS, DEFAULT_SETTINGS, SCHEMA


def _q(v) -> str:
    return "NULL" if v is None else ("'" + str(v).replace("'", "''") + "'")


MIGRATIONS: list[tuple[int, str]] = [(1, r"""
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin','financial','support','viewer')),
    pw_hash       TEXT NOT NULL,
    failed        INTEGER NOT NULL DEFAULT 0,
    locked_until  TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip         TEXT
);
CREATE TABLE licenses (
    id              INTEGER PRIMARY KEY,
    license_id      TEXT NOT NULL UNIQUE,
    document        TEXT NOT NULL,
    key_id          TEXT NOT NULL,
    customer        TEXT NOT NULL,
    type            TEXT NOT NULL,
    installation_id TEXT NOT NULL,
    hardware_id     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','replaced','revoked')),
    revoked_reason  TEXT,
    registered_at   TEXT NOT NULL,
    registered_by   TEXT NOT NULL
);
CREATE TABLE nonces (
    nonce      TEXT PRIMARY KEY,
    license_id TEXT NOT NULL,
    at         TEXT NOT NULL
);
CREATE INDEX ix_nonces_at ON nonces(at);
CREATE TABLE audit (
    id        INTEGER PRIMARY KEY,
    at        TEXT NOT NULL,
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    target    TEXT,
    details   TEXT,
    ip        TEXT,
    prev_hash TEXT NOT NULL,
    hash      TEXT NOT NULL
);
""" + SCHEMA + "".join(f"INSERT OR IGNORE INTO com_settings(key, value) VALUES ({_q(k)}, {_q(v)});\n"
                       for k, v in DEFAULT_SETTINGS.items())
    + "".join(f"INSERT OR IGNORE INTO com_plans(code, name, months) VALUES ({_q(c)}, {_q(n)}, {_q(m)});\n"
              for c, n, m in DEFAULT_PLANS))]

SCHEMA_VERSION = MIGRATIONS[-1][0]


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._local = threading.local()

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(self.path, timeout=15, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            c.execute("PRAGMA journal_mode = WAL")
            c.execute("PRAGMA synchronous = FULL")
            self._local.c = c
        return c

    def close(self) -> None:
        c = getattr(self._local, "c", None)
        if c is not None:
            c.close()
            self._local.c = None

    def migrate(self) -> list[int]:
        c = self.conn()
        r = c.execute("PRAGMA integrity_check").fetchone()[0]
        if r != "ok":
            raise RuntimeError(f"Banco de dados danificado: {r}")
        cur = int(c.execute("PRAGMA user_version").fetchone()[0])
        if cur > SCHEMA_VERSION:
            raise RuntimeError("Banco criado por uma versão mais nova do License Server.")
        done = []
        for ver, sql in MIGRATIONS:
            if ver <= cur:
                continue
            c.execute("BEGIN IMMEDIATE")
            try:
                for stmt in _statements(sql):
                    c.execute(stmt)
                c.execute(f"PRAGMA user_version = {ver}")
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
            done.append(ver)
        return done

    @contextmanager
    def tx(self):
        c = self.conn()
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
        except BaseException:
            c.execute("ROLLBACK")
            raise
        c.execute("COMMIT")

    # ------------------------------------------------------------------ auditoria encadeada
    def audit(self, actor: str, action: str, target: str | None = None, details: dict | None = None, c=None,
              ip: str | None = None) -> None:
        c = c or self.conn()
        prev = c.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = prev["hash"] if prev else "0" * 64
        at = iso_now()
        det = json.dumps(details or {}, ensure_ascii=False, sort_keys=True, default=str)
        h = hashlib.sha256(canonical([prev_hash, at, actor, action, target, det, ip])).hexdigest()
        c.execute("INSERT INTO audit(at, actor, action, target, details, ip, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?)",
                  (at, actor, action, target, det, ip, prev_hash, h))

    def verify_audit(self) -> list[int]:
        bad, prev = [], "0" * 64
        for r in self.conn().execute("SELECT * FROM audit ORDER BY id"):
            h = hashlib.sha256(canonical([prev, r["at"], r["actor"], r["action"], r["target"], r["details"],
                                          r["ip"]])).hexdigest()
            if r["prev_hash"] != prev or r["hash"] != h:
                bad.append(r["id"])
            prev = r["hash"]
        return bad


def _statements(sql: str) -> list[str]:
    out, buf = [], []
    for line in sql.splitlines():
        if line.strip().startswith("--") and not buf:
            continue
        buf.append(line)
        joined = "\n".join(buf)
        if joined.rstrip().endswith(";") and sqlite3.complete_statement(joined):
            out.append(joined.strip())
            buf = []
    if "".join(buf).strip():
        out.append("\n".join(buf))
    return out
