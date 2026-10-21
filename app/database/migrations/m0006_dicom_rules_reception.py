"""Migração 0006 — Regras DICOM por destino (porta + Called AE) e VYONIX Reception.

* ``devices`` passa a representar as **Regras DICOM**: ``called_ae`` (AE Title de destino),
  ``listen_port`` (porta do VYONIX; NULL = porta padrão do serviço) e ``service`` (C-STORE ou
  DICOM Print). ``ae_title`` vira a restrição **opcional** de Calling AE Title (``*`` = qualquer) e
  ``ip_address`` a restrição opcional de IP/faixa. Cadastros existentes são convertidos sem perda:
  passam a ter o AE local como destino e mantêm o AE/IP antigos como restrições.
* ``exams``: estudos recebidos (dados de identificação para a recepção), situação de retirada e
  ``exam_events`` (histórico por exame).
* ``users``/``web_sessions``: perfis Administrador, Técnico, Supervisor da recepção e Recepcionista.
* ``print_requests``: pedidos de impressão da recepção (idempotência contra cliques repetidos).
"""

VERSION = 6
NAME = "dicom_rules_reception"

SQL = r"""
DROP INDEX IF EXISTS ux_devices_ae_ip_active;
ALTER TABLE devices ADD COLUMN called_ae TEXT;
ALTER TABLE devices ADD COLUMN listen_port INTEGER CHECK (listen_port IS NULL OR listen_port BETWEEN 1 AND 65535);
ALTER TABLE devices ADD COLUMN service TEXT NOT NULL DEFAULT 'store' CHECK (service IN ('store','print'));
UPDATE devices SET called_ae = COALESCE(
    (SELECT json_extract(value_json, '$') FROM settings WHERE key = 'dicom.storage.ae_title'), 'VYONIX');
CREATE INDEX ix_devices_route ON devices(service, called_ae, listen_port) WHERE active = 1;

ALTER TABLE jobs ADD COLUMN exam_id INTEGER;
ALTER TABLE jobs ADD COLUMN requested_by TEXT;
CREATE INDEX ix_jobs_exam ON jobs(exam_id);

CREATE TABLE exams (
    id                INTEGER PRIMARY KEY,
    study_uid         TEXT NOT NULL UNIQUE,
    source            TEXT NOT NULL DEFAULT 'storage' CHECK (source IN ('storage','dicom_print')),
    patient_name      TEXT,
    patient_id        TEXT,
    accession         TEXT,
    admission_id      TEXT,
    study_date        TEXT,
    study_desc        TEXT,
    modality          TEXT,
    device_id         INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    calling_ae        TEXT,
    called_ae         TEXT,
    source_ip         TEXT,
    instances         INTEGER NOT NULL DEFAULT 0,
    first_received_at TEXT NOT NULL,
    last_received_at  TEXT NOT NULL,
    pickup_state      TEXT NOT NULL DEFAULT 'aguardando_preparacao' CHECK (pickup_state IN
        ('aguardando_preparacao','em_preparacao','pronto','entregue','entrega_pendente','entrega_cancelada')),
    pickup_at         TEXT,
    pickup_by         TEXT,
    pickup_note       TEXT,
    delivered_to      TEXT,
    purged_at         TEXT
);
CREATE INDEX ix_exams_received ON exams(first_received_at);
CREATE INDEX ix_exams_patient ON exams(patient_name);
CREATE INDEX ix_exams_pid ON exams(patient_id);
CREATE INDEX ix_exams_acc ON exams(accession);
CREATE INDEX ix_exams_pickup ON exams(pickup_state);

CREATE TABLE exam_events (
    id       INTEGER PRIMARY KEY,
    exam_id  INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    at       TEXT NOT NULL,
    actor    TEXT NOT NULL,
    action   TEXT NOT NULL,
    detail   TEXT,
    job_ids  TEXT
);
CREATE INDEX ix_exam_events_exam ON exam_events(exam_id, at);

CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin','technician','supervisor','receptionist')),
    pw_hash       TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    failed        INTEGER NOT NULL DEFAULT 0,
    locked_until  TEXT,
    must_change   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE web_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    address    TEXT
);

CREATE TABLE print_requests (
    request_key TEXT PRIMARY KEY,
    exam_id     INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    actor       TEXT NOT NULL,
    at          TEXT NOT NULL,
    result_json TEXT NOT NULL
);
"""
