"""Migração 0001 — modelo inicial completo.

ATENÇÃO: migrações aplicadas são imutáveis. O *checksum* deste SQL é gravado no
banco; alterá-lo depois de distribuído impede a inicialização. Mudanças de esquema
devem ser feitas em uma nova migração (m0002_..., m0003_...).
"""

VERSION = 1
NAME = "initial"

SQL = r"""
CREATE TABLE settings (
    key          TEXT PRIMARY KEY,
    value_json   TEXT NOT NULL CHECK (json_valid(value_json)),
    updated_at   TEXT NOT NULL,
    updated_by   TEXT NOT NULL
);

CREATE TABLE change_history (
    id           INTEGER PRIMARY KEY,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    field        TEXT NOT NULL,
    old_value    TEXT,
    new_value    TEXT,
    changed_at   TEXT NOT NULL,
    changed_by   TEXT NOT NULL,
    reason       TEXT
);
CREATE INDEX ix_change_history_entity ON change_history(entity_type, entity_id, changed_at);

CREATE TABLE events (
    id           INTEGER PRIMARY KEY,
    ts           TEXT NOT NULL,
    level        TEXT NOT NULL CHECK (level IN ('DEBUG','INFO','WARNING','ERROR','CRITICAL')),
    category     TEXT NOT NULL,
    action       TEXT NOT NULL,
    message      TEXT NOT NULL,
    device_id    INTEGER,
    job_id       INTEGER,
    actor        TEXT,
    details_json TEXT CHECK (details_json IS NULL OR json_valid(details_json))
);
CREATE INDEX ix_events_ts ON events(ts);
CREATE INDEX ix_events_category_ts ON events(category, ts);
CREATE INDEX ix_events_level_ts ON events(level, ts);
CREATE INDEX ix_events_device_ts ON events(device_id, ts);

CREATE TABLE printers (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL UNIQUE,
    driver_name       TEXT,
    is_default        INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
    capabilities_json TEXT CHECK (capabilities_json IS NULL OR json_valid(capabilities_json)),
    active            INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    last_status       TEXT,
    last_seen_at      TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE print_profiles (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,
    description      TEXT,
    paper_size       TEXT,
    orientation      TEXT CHECK (orientation IS NULL OR orientation IN ('portrait','landscape','auto')),
    layout           TEXT,
    margins_json     TEXT CHECK (margins_json IS NULL OR json_valid(margins_json)),
    calibration_json TEXT CHECK (calibration_json IS NULL OR json_valid(calibration_json)),
    copies           INTEGER CHECK (copies IS NULL OR copies BETWEEN 1 AND 99),
    annotations_json TEXT CHECK (annotations_json IS NULL OR json_valid(annotations_json)),
    active           INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE devices (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    manufacturer     TEXT,
    model            TEXT,
    modality         TEXT,
    ae_title         TEXT NOT NULL CHECK (length(ae_title) BETWEEN 1 AND 16),
    ip_address       TEXT,
    port             INTEGER CHECK (port IS NULL OR port BETWEEN 1 AND 65535),
    site             TEXT,
    department       TEXT,
    printer_id       INTEGER REFERENCES printers(id) ON DELETE SET NULL,
    print_profile_id INTEGER REFERENCES print_profiles(id) ON DELETE SET NULL,
    authorized       INTEGER NOT NULL DEFAULT 0 CHECK (authorized IN (0,1)),
    active           INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    comm_status      TEXT,
    notes            TEXT,
    last_seen_at     TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE UNIQUE INDEX ux_devices_ae_active ON devices(ae_title) WHERE active = 1;
CREATE INDEX ix_devices_last_seen ON devices(last_seen_at);

CREATE TABLE profile_bindings (
    id          INTEGER PRIMARY KEY,
    profile_id  INTEGER NOT NULL REFERENCES print_profiles(id) ON DELETE CASCADE,
    scope_type  TEXT NOT NULL CHECK (scope_type IN ('printer','device','modality')),
    scope_value TEXT NOT NULL,
    UNIQUE (scope_type, scope_value)
);

CREATE TABLE rules (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT,
    conditions_json TEXT NOT NULL CHECK (json_valid(conditions_json)),
    actions_json    TEXT NOT NULL CHECK (json_valid(actions_json)),
    priority        INTEGER NOT NULL DEFAULT 100,
    active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX ix_rules_active_priority ON rules(active, priority);

CREATE TABLE instances (
    id               INTEGER PRIMARY KEY,
    sop_instance_uid TEXT NOT NULL UNIQUE,
    sop_class_uid    TEXT NOT NULL,
    study_uid        TEXT NOT NULL,
    series_uid       TEXT NOT NULL,
    modality         TEXT,
    transfer_syntax  TEXT NOT NULL,
    file_path        TEXT NOT NULL,
    file_sha256      TEXT NOT NULL,
    file_size        INTEGER NOT NULL,
    number_of_frames INTEGER NOT NULL DEFAULT 1,
    source_ae        TEXT NOT NULL,
    source_ip        TEXT,
    device_id        INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    received_at      TEXT NOT NULL,
    purge_after      TEXT
);
CREATE INDEX ix_instances_study ON instances(study_uid, series_uid);
CREATE INDEX ix_instances_received ON instances(received_at);
CREATE INDEX ix_instances_purge ON instances(purge_after);

CREATE TABLE print_sessions (
    id               INTEGER PRIMARY KEY,
    association_id   TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('film_session','film_box','image_box','presentation_lut')),
    sop_instance_uid TEXT NOT NULL UNIQUE,
    parent_uid       TEXT,
    attributes_json  TEXT NOT NULL CHECK (json_valid(attributes_json)),
    device_id        INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX ix_print_sessions_assoc ON print_sessions(association_id);

CREATE TABLE jobs (
    id                   INTEGER PRIMARY KEY,
    uuid                 TEXT NOT NULL UNIQUE,
    idempotency_key      TEXT NOT NULL UNIQUE,
    source_type          TEXT NOT NULL CHECK (source_type IN ('dicom_print','storage','manual','test_page','reprint')),
    parent_job_id        INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    device_id            INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    source_ae            TEXT,
    modality             TEXT,
    printer_id           INTEGER REFERENCES printers(id) ON DELETE SET NULL,
    profile_id           INTEGER REFERENCES print_profiles(id) ON DELETE SET NULL,
    rule_id              INTEGER REFERENCES rules(id) ON DELETE SET NULL,
    state                TEXT NOT NULL CHECK (state IN ('received','validating','processing','waiting_print','spooled','completed','failed','cancelled','held')),
    state_reason         TEXT,
    settings_json        TEXT CHECK (settings_json IS NULL OR json_valid(settings_json)),
    settings_origin_json TEXT CHECK (settings_origin_json IS NULL OR json_valid(settings_origin_json)),
    page_count           INTEGER,
    copies               INTEGER NOT NULL DEFAULT 1 CHECK (copies BETWEEN 1 AND 99),
    attempts             INTEGER NOT NULL DEFAULT 0,
    max_attempts         INTEGER NOT NULL DEFAULT 3,
    next_attempt_at      TEXT,
    spool_job_id         INTEGER,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    submitted_at         TEXT,
    completed_at         TEXT
);
CREATE INDEX ix_jobs_state ON jobs(state, updated_at);
CREATE INDEX ix_jobs_created ON jobs(created_at);
CREATE INDEX ix_jobs_device ON jobs(device_id, created_at);

CREATE TABLE job_items (
    id          INTEGER PRIMARY KEY,
    job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    instance_id INTEGER REFERENCES instances(id) ON DELETE RESTRICT,
    frame_index INTEGER NOT NULL DEFAULT 0,
    position    INTEGER NOT NULL,
    UNIQUE (job_id, position)
);

CREATE TABLE job_state_history (
    id         INTEGER PRIMARY KEY,
    job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    from_state TEXT,
    to_state   TEXT NOT NULL,
    actor      TEXT NOT NULL,
    reason     TEXT,
    at         TEXT NOT NULL
);
CREATE INDEX ix_job_state_history_job ON job_state_history(job_id, at);

CREATE TABLE licenses (
    id              INTEGER PRIMARY KEY,
    license_id      TEXT NOT NULL UNIQUE,
    edition         TEXT NOT NULL,
    features_json   TEXT NOT NULL CHECK (json_valid(features_json)),
    licensee        TEXT NOT NULL,
    installation_id TEXT NOT NULL,
    issued_at       TEXT NOT NULL,
    expires_at      TEXT,
    signature       TEXT NOT NULL,
    raw             TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('active','superseded','revoked','invalid')),
    installed_at    TEXT NOT NULL
);
"""
