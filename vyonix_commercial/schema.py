"""Tabelas comerciais (mesma estrutura no License Manager e no License Server)."""

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS com_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS com_plans (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    months      INTEGER,                    -- NULL = personalizado/permanente
    price_cents INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS com_subscriptions (
    id                        INTEGER PRIMARY KEY,
    license_id                TEXT NOT NULL UNIQUE,
    customer_ref              TEXT,
    customer_name             TEXT NOT NULL,
    customer_document         TEXT,
    installation_id           TEXT NOT NULL,
    hardware_id               TEXT NOT NULL,
    site                      TEXT,
    plan_code                 TEXT NOT NULL,
    price_cents               INTEGER NOT NULL DEFAULT 0,
    validation                TEXT NOT NULL DEFAULT 'offline' CHECK (validation IN ('offline','online')),
    permanent                 INTEGER NOT NULL DEFAULT 0,
    paid_until                TEXT,
    maintenance_until         TEXT,
    warn_days                 INTEGER NOT NULL,
    grace_days                INTEGER NOT NULL,
    grace_extra_until         TEXT,
    suspend_at                TEXT,
    suspended_at              TEXT,
    suspension_reason         TEXT,
    auto_suspend              INTEGER NOT NULL DEFAULT 0,
    contract_allows_suspension INTEGER NOT NULL DEFAULT 1,
    operational_notes         TEXT,
    reactivated_at            TEXT,
    last_payment_at           TEXT,
    last_payment_cents        INTEGER,
    last_state                TEXT,
    last_contact_at           TEXT,
    last_contact_version      TEXT,
    auth_seq                  INTEGER NOT NULL DEFAULT 0,
    billing_provider          TEXT,
    active                    INTEGER NOT NULL DEFAULT 1,
    created_at                TEXT NOT NULL,
    updated_at                TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS com_charges (
    id              INTEGER PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES com_subscriptions(id),
    provider        TEXT NOT NULL,
    provider_ref    TEXT NOT NULL,
    our_number      TEXT,
    amount_cents    INTEGER NOT NULL,
    due_date        TEXT NOT NULL,
    periods         INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL CHECK (status IN ('issued','paid','overdue','cancelled','expired','manual_check')),
    provider_status TEXT,
    issued_at       TEXT NOT NULL,
    issued_by       TEXT NOT NULL,
    paid_at         TEXT,
    paid_cents      INTEGER,
    checked_at      TEXT,
    UNIQUE (provider, provider_ref)
);

CREATE TABLE IF NOT EXISTS com_payments (
    id              INTEGER PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES com_subscriptions(id),
    reference       TEXT NOT NULL UNIQUE,
    source          TEXT NOT NULL,
    amount_cents    INTEGER,
    periods         INTEGER NOT NULL,
    paid_at         TEXT NOT NULL,
    confirmed_by    TEXT NOT NULL,
    confirmed_at    TEXT NOT NULL,
    prev_paid_until TEXT,
    new_paid_until  TEXT NOT NULL,
    charge_id       INTEGER REFERENCES com_charges(id)
);

CREATE TABLE IF NOT EXISTS com_payment_events (
    id          INTEGER PRIMARY KEY,
    provider    TEXT NOT NULL,
    event_key   TEXT NOT NULL,
    received_at TEXT NOT NULL,
    payload     TEXT,
    result      TEXT,
    UNIQUE (provider, event_key)
);

CREATE TABLE IF NOT EXISTS com_history (
    id              INTEGER PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES com_subscriptions(id),
    at              TEXT NOT NULL,
    action          TEXT NOT NULL,
    from_state      TEXT,
    to_state        TEXT,
    actor           TEXT NOT NULL,
    source          TEXT NOT NULL,
    reason          TEXT,
    details         TEXT
);
CREATE INDEX IF NOT EXISTS ix_com_history_sub ON com_history(subscription_id, id);

CREATE TABLE IF NOT EXISTS com_notifications (
    id              INTEGER PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES com_subscriptions(id),
    at              TEXT NOT NULL,
    kind            TEXT NOT NULL,
    ref             TEXT NOT NULL,
    audience        TEXT NOT NULL,
    message         TEXT NOT NULL,
    UNIQUE (subscription_id, kind, ref)
);

CREATE TABLE IF NOT EXISTS com_authorizations (
    id               INTEGER PRIMARY KEY,
    authorization_id TEXT NOT NULL UNIQUE,
    subscription_id  INTEGER NOT NULL REFERENCES com_subscriptions(id),
    license_id       TEXT NOT NULL,
    seq              INTEGER NOT NULL,
    issued_at        TEXT NOT NULL,
    valid_until      TEXT NOT NULL,
    state            TEXT NOT NULL,
    source           TEXT NOT NULL,
    channel          TEXT NOT NULL,
    actor            TEXT NOT NULL,
    document         TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "warn_days": "5",                         # avisos começam N dias antes do vencimento
    "grace_days": "7",                        # carência após o vencimento
    "max_grace_extension_days": "30",         # prorrogação máxima por concessão
    "auth_ttl_days": "7",                     # validade de cada autorização online
    "online_tolerance_days": "10",            # tolerância a servidor/internet indisponível
    "auto_suspend": "0",                      # suspensão automática ao fim da carência (se o contrato prevê)
    "grace_roles": "admin,financial",         # perfis que podem conceder prorrogação de carência
    "confirm_actions": "suspend,schedule_suspension,reactivate",  # exigem confirmação de um administrador
    "server_url": "",                         # endereço do VYONIX License Server gravado nas licenças online
    "server_pin": "",                         # SHA-256 do certificado TLS do servidor (opcional)
}

DEFAULT_PLANS = [
    ("monthly", "Mensal", 1), ("quarterly", "Trimestral", 3), ("semiannual", "Semestral", 6),
    ("annual", "Anual", 12), ("custom", "Período personalizado", None), ("permanent", "Permanente", None),
]


def statements() -> list[str]:
    import sqlite3
    out, buf = [], []
    for line in SCHEMA.splitlines():
        buf.append(line)
        joined = "\n".join(buf)
        if joined.strip() and joined.rstrip().endswith(";") and sqlite3.complete_statement(joined):
            out.append(joined.strip())
            buf = []
    return out
