"""Banco de dados próprio do License Manager (SQLite), com migrações e verificação de integridade."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class DatabaseCorrupt(Exception):
    """O arquivo do banco está danificado (restaure um backup)."""


class DatabaseTooNew(Exception):
    """Banco criado por uma versão mais nova do License Manager."""


MIGRATIONS: list[tuple[int, str]] = [(1, r"""
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin','issuer','viewer')),
    pw_hash       TEXT NOT NULL,
    failed        INTEGER NOT NULL DEFAULT 0,
    locked_until  TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    must_change   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE customers (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    document      TEXT,
    contact       TEXT,
    email         TEXT,
    phone         TEXT,
    city          TEXT,
    state         TEXT,
    notes         TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    anonymized_at TEXT
);

CREATE TABLE products (
    id                   INTEGER PRIMARY KEY,
    product_id           TEXT NOT NULL UNIQUE,
    name                 TEXT NOT NULL,
    editions_json        TEXT NOT NULL,
    features_json        TEXT NOT NULL,
    default_max_devices  INTEGER,
    default_max_printers INTEGER,
    active               INTEGER NOT NULL DEFAULT 1,
    created_at           TEXT NOT NULL
);

CREATE TABLE signing_keys (
    id          INTEGER PRIMARY KEY,
    key_id      TEXT NOT NULL UNIQUE,
    public_hex  TEXT NOT NULL UNIQUE,
    private_pem BLOB NOT NULL,              -- PKCS#8 cifrado com a frase-senha (nunca em claro)
    status      TEXT NOT NULL CHECK (status IN ('active','standby','retired')),
    origin      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    note        TEXT
);

CREATE TABLE requests (
    id              INTEGER PRIMARY KEY,
    request_id      TEXT NOT NULL UNIQUE,
    raw             TEXT NOT NULL,
    hardware_id     TEXT NOT NULL,
    installation_id TEXT NOT NULL,
    hw_json         TEXT NOT NULL,
    tpm_status      TEXT NOT NULL,
    app_version     TEXT,
    site            TEXT,
    reason          TEXT,
    previous_license_id TEXT,
    demo_used       INTEGER,
    requested_at    TEXT,
    imported_at     TEXT NOT NULL,
    imported_by     TEXT NOT NULL,
    customer_id     INTEGER REFERENCES customers(id)
);

CREATE TABLE installations (
    id              INTEGER PRIMARY KEY,
    customer_id     INTEGER REFERENCES customers(id),
    hardware_id     TEXT NOT NULL,
    installation_id TEXT NOT NULL,
    hw_json         TEXT NOT NULL,
    site            TEXT,
    first_seen      TEXT NOT NULL,
    last_license_id TEXT,
    UNIQUE (hardware_id, installation_id)
);

CREATE TABLE licenses (
    id              INTEGER PRIMARY KEY,
    license_id      TEXT NOT NULL UNIQUE,
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    product_id      TEXT NOT NULL,
    edition         TEXT NOT NULL,
    type            TEXT NOT NULL,
    hardware_id     TEXT NOT NULL,
    installation_id TEXT NOT NULL,
    hw_json         TEXT NOT NULL,
    issued_at       TEXT NOT NULL,
    starts_at       TEXT,
    expires_at      TEXT,
    duration_hours  INTEGER,
    max_devices     INTEGER,
    max_printers    INTEGER,
    features_json   TEXT NOT NULL,
    notes           TEXT,
    status          TEXT NOT NULL CHECK (status IN ('active','superseded','replaced','revoked')),
    key_id          TEXT NOT NULL,
    document        TEXT NOT NULL,
    request_id      TEXT,
    reissue_of      TEXT,
    operation       TEXT NOT NULL,          -- issue | renew | reactivate | demo
    reason_code     TEXT,
    reason_text     TEXT,
    created_by      TEXT NOT NULL,
    revoked_at      TEXT,
    revoked_reason  TEXT
);
CREATE INDEX ix_licenses_customer ON licenses(customer_id);
CREATE INDEX ix_licenses_hw ON licenses(hardware_id);

CREATE TABLE reactivations (
    id             INTEGER PRIMARY KEY,
    customer_id    INTEGER NOT NULL REFERENCES customers(id),
    old_license_id TEXT,
    new_license_id TEXT NOT NULL,
    reason_code    TEXT NOT NULL,
    reason_text    TEXT,
    old_hardware_id TEXT,
    new_hardware_id TEXT,
    actor          TEXT NOT NULL,
    at             TEXT NOT NULL
);

CREATE TABLE revocation_lists (
    seq       INTEGER PRIMARY KEY,
    issued_at TEXT NOT NULL,
    count     INTEGER NOT NULL,
    document  TEXT NOT NULL,
    actor     TEXT NOT NULL
);

CREATE TABLE revalidations (
    id              INTEGER PRIMARY KEY,
    request_id      TEXT NOT NULL UNIQUE,
    customer_id     INTEGER REFERENCES customers(id),
    hardware_id     TEXT NOT NULL,
    installation_id TEXT NOT NULL,
    diagnostic      TEXT NOT NULL,
    actions         TEXT NOT NULL,
    reason          TEXT NOT NULL,
    document        TEXT NOT NULL,
    actor           TEXT NOT NULL,
    at              TEXT NOT NULL
);

CREATE TABLE audit (
    id        INTEGER PRIMARY KEY,
    at        TEXT NOT NULL,
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    target    TEXT,
    details   TEXT,
    prev_hash TEXT NOT NULL,
    hash      TEXT NOT NULL
);
""")]


def _migration_2() -> str:
    """Revisão 4: perfis comerciais (operador financeiro, suporte técnico) e Gestão Comercial."""
    from vyonix_commercial.schema import DEFAULT_PLANS, DEFAULT_SETTINGS, SCHEMA

    def q(v) -> str:
        return "NULL" if v is None else ("'" + str(v).replace("'", "''") + "'")
    seeds = "".join(f"INSERT OR IGNORE INTO com_settings(key, value) VALUES ({q(k)}, {q(v)});\n"
                    for k, v in DEFAULT_SETTINGS.items())
    seeds += "".join(f"INSERT OR IGNORE INTO com_plans(code, name, months) VALUES ({q(c)}, {q(n)}, {q(m)});\n"
                     for c, n, m in DEFAULT_PLANS)
    return r"""
CREATE TABLE users_v2 (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin','financial','support','issuer','viewer')),
    pw_hash       TEXT NOT NULL,
    failed        INTEGER NOT NULL DEFAULT 0,
    locked_until  TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    must_change   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);
INSERT INTO users_v2 SELECT id, username, display_name, role, pw_hash, failed, locked_until, active, must_change,
                            created_at, last_login_at FROM users;
DROP TABLE users;
ALTER TABLE users_v2 RENAME TO users;
""" + SCHEMA + seeds


MIGRATIONS.append((2, _migration_2()))

SCHEMA_VERSION = MIGRATIONS[-1][0]


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

    def check_integrity(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        try:
            r = self.conn().execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            self.close()
            raise DatabaseCorrupt(f"Banco de dados ilegível: {exc}") from exc
        if r != "ok":
            self.close()
            raise DatabaseCorrupt(f"Banco de dados danificado: {r}")

    def version(self) -> int:
        return int(self.conn().execute("PRAGMA user_version").fetchone()[0])

    def migrate(self) -> list[int]:
        self.check_integrity()
        cur = self.version()
        if cur > SCHEMA_VERSION:
            raise DatabaseTooNew(f"Banco criado por versão mais nova (esquema {cur}; esta versão: {SCHEMA_VERSION}).")
        applied = []
        c = self.conn()
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
            applied.append(ver)
        return applied

    def tx(self):
        return _Tx(self.conn())


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


class _Tx:
    def __init__(self, c: sqlite3.Connection) -> None:
        self.c = c

    def __enter__(self):
        self.c.execute("BEGIN IMMEDIATE")
        return self.c

    def __exit__(self, et, ev, tb):
        self.c.execute("COMMIT" if et is None else "ROLLBACK")
        return False
