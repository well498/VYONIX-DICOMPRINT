"""Migração 0004 — configurações independentes por equipamento e calibração progressiva.

* ``devices``: o AE Title pode se repetir entre equipamentos **somente** com IPs diferentes (vários
  equipamentos de fábrica usam o mesmo AE Title); a origem é identificada por AE Title + IP.
* ``device_settings``: configurações gerais de impressão de cada equipamento (somente dele) e
  ``device_settings_versions`` com todas as versões anteriores (restauração).
* ``rules.device_id``: regras do equipamento (NULL = regra geral).
* ``calibration_rounds``: rodadas da calibração progressiva (matriz 3 × 3) e a escolha do técnico.
"""

VERSION = 4
NAME = "device_settings"

SQL = r"""
DROP INDEX IF EXISTS ux_devices_ae_active;
CREATE UNIQUE INDEX ux_devices_ae_ip_active ON devices(ae_title, COALESCE(ip_address, '')) WHERE active = 1;

CREATE TABLE device_settings (
    device_id     INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
    settings_json TEXT NOT NULL CHECK (json_valid(settings_json)),
    version       INTEGER NOT NULL DEFAULT 1,
    updated_at    TEXT NOT NULL,
    updated_by    TEXT NOT NULL
);

CREATE TABLE device_settings_versions (
    id            INTEGER PRIMARY KEY,
    device_id     INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    version       INTEGER NOT NULL,
    settings_json TEXT NOT NULL CHECK (json_valid(settings_json)),
    reason        TEXT,
    actor         TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE (device_id, version)
);

ALTER TABLE rules ADD COLUMN device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE;
CREATE INDEX ix_rules_device ON rules(device_id, active, priority);

CREATE TABLE calibration_rounds (
    id            INTEGER PRIMARY KEY,
    session_id    TEXT NOT NULL,
    device_id     INTEGER REFERENCES devices(id) ON DELETE CASCADE,
    round_no      INTEGER NOT NULL,
    mode          TEXT NOT NULL,
    step          REAL NOT NULL,
    center_json   TEXT NOT NULL CHECK (json_valid(center_json)),
    cells_json    TEXT NOT NULL CHECK (json_valid(cells_json)),
    source        TEXT NOT NULL,
    printer       TEXT,
    paper         TEXT,
    job_id        INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    chosen_index  INTEGER,
    notes         TEXT,
    actor         TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    chosen_at     TEXT
);
CREATE INDEX ix_calibration_rounds_device ON calibration_rounds(device_id, created_at);
"""
