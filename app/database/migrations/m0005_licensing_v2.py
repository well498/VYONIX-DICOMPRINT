"""Migração 0005 — licenciamento v2 (Hardware ID, Installation ID, DEMO, Time Integrity).

* ``licenses`` recriada com os novos estados (``ended``: ativação encerrada pela desinstalação) e
  as colunas do formato 2 (tipo, Hardware ID, data de ativação, emissão anterior).
* ``licensing_vault``: uma das cópias seladas do cofre de estado (``app/licensing/vault.py``).
* ``time_integrity_log``: histórico de integridade temporal (inícios, saltos, retrocessos,
  revalidações).
* ``license_printers``: impressoras ocupando as vagas autorizadas pela licença.
"""

VERSION = 5
NAME = "licensing_v2"

SQL = r"""
CREATE TABLE licenses_v2 (
    id              INTEGER PRIMARY KEY,
    license_id      TEXT NOT NULL UNIQUE,
    edition         TEXT NOT NULL,
    license_type    TEXT NOT NULL DEFAULT 'legacy',
    features_json   TEXT NOT NULL CHECK (json_valid(features_json)),
    licensee        TEXT NOT NULL,
    installation_id TEXT NOT NULL,
    hardware_id     TEXT,
    issued_at       TEXT NOT NULL,
    expires_at      TEXT,
    signature       TEXT NOT NULL,
    raw             TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('active','superseded','revoked','invalid','ended')),
    installed_at    TEXT NOT NULL,
    activated_at    TEXT,
    ended_at        TEXT,
    ended_reason    TEXT
);
INSERT INTO licenses_v2(id, license_id, edition, features_json, licensee, installation_id, issued_at, expires_at,
                        signature, raw, status, installed_at)
    SELECT id, license_id, edition, features_json, licensee, installation_id, issued_at, expires_at, signature, raw,
           CASE WHEN status = 'active' THEN 'superseded' ELSE status END, installed_at FROM licenses;
DROP TABLE licenses;
ALTER TABLE licenses_v2 RENAME TO licenses;

CREATE TABLE licensing_vault (
    name       TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE time_integrity_log (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,
    kind        TEXT NOT NULL,
    wall        TEXT NOT NULL,
    trusted     TEXT,
    delta_s     REAL,
    boot_id     TEXT,
    process     TEXT,
    detail      TEXT
);
CREATE INDEX ix_time_integrity_log_at ON time_integrity_log(at);

CREATE TABLE license_printers (
    id         INTEGER PRIMARY KEY,
    license_id TEXT NOT NULL,
    printer    TEXT NOT NULL,
    added_at   TEXT NOT NULL,
    added_by   TEXT NOT NULL,
    UNIQUE (license_id, printer)
);
"""
