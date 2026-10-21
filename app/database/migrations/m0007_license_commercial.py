"""Migração 0007 — licenciamento comercial por assinatura.

* ``license_authorizations``: autorizações de uso recebidas (servidor online ou arquivo de renovação),
  com origem e responsável — reativações ficam registradas com data, origem e responsável.
* ``license_state_history``: histórico completo das transições de estado da licença e do estado
  comercial (ATIVA, PRÓXIMA DO VENCIMENTO, EM ATRASO, SUSPENSÃO PROGRAMADA, SUSPENSA, EXPIRADA,
  REATIVADA) e da conectividade com o License Server.
"""

VERSION = 7
NAME = "license_commercial"

SQL = r"""
CREATE TABLE license_authorizations (
    id               INTEGER PRIMARY KEY,
    authorization_id TEXT NOT NULL UNIQUE,
    license_id       TEXT NOT NULL,
    seq              INTEGER NOT NULL,
    source           TEXT NOT NULL,
    channel          TEXT NOT NULL,
    issued_at        TEXT NOT NULL,
    issued_by        TEXT,
    valid_until      TEXT NOT NULL,
    state            TEXT NOT NULL,
    applied_at       TEXT NOT NULL,
    applied_by       TEXT NOT NULL,
    raw              TEXT NOT NULL
);
CREATE INDEX ix_license_auth_license ON license_authorizations(license_id, seq);

CREATE TABLE license_state_history (
    id         INTEGER PRIMARY KEY,
    at         TEXT NOT NULL,
    license_id TEXT,
    kind       TEXT NOT NULL CHECK (kind IN ('license','commercial','connectivity')),
    from_state TEXT,
    to_state   TEXT NOT NULL,
    source     TEXT NOT NULL,
    actor      TEXT NOT NULL,
    detail     TEXT
);
CREATE INDEX ix_license_state_history_at ON license_state_history(at);
"""
