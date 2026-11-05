-- Fila local do Gateway VYONIX (SQLite, fora do Core). Sem PHI além de UIDs DICOM. Rascunho A08 M3.
PRAGMA journal_mode = WAL;          -- leitores não bloqueiam o escritor; sobrevive a queda de energia com synchronous=FULL
PRAGMA synchronous = FULL;
PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;            -- versão do esquema (migração local simples, só aditiva)

CREATE TABLE IF NOT EXISTS instances (
  sop_uid        TEXT PRIMARY KEY,                        -- chave única: 1 linha por instância
  study_uid      TEXT NOT NULL,
  series_uid     TEXT NOT NULL,
  orthanc_id     TEXT NOT NULL,
  sha256         TEXT NOT NULL CHECK (length(sha256) = 64),
  size_bytes     INTEGER NOT NULL,
  calling_ae     TEXT,
  state          TEXT NOT NULL DEFAULT 'received' CHECK (state IN
                 ('received','queued','sending','sent','confirmed','integrity','conflict','failed')),
  request_id     TEXT NOT NULL,                           -- uuid5(gateway, sop_uid:sha256) => idempotente no central
  attempts       INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  lease_until    TEXT,                                    -- 'sending' expira: volta a 'queued' se o processo cair
  receipt_id     INTEGER,                                 -- id do recibo no central (pacs.ingest_receipts)
  remote_sha256  TEXT,
  last_error     TEXT,
  received_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  confirmed_at   TEXT,
  local_purge_eligible_at TEXT                            -- só preenchido após confirmed + manifesto 'complete'
) STRICT;
CREATE INDEX IF NOT EXISTS ix_due ON instances (state, next_attempt_at);
CREATE INDEX IF NOT EXISTS ix_study ON instances (study_uid);

-- transições permitidas (qualquer outra é recusada no próprio banco)
CREATE TABLE IF NOT EXISTS transitions (src TEXT NOT NULL, dst TEXT NOT NULL, PRIMARY KEY (src, dst)) STRICT;
INSERT OR IGNORE INTO transitions VALUES
 ('received','queued'),('received','integrity'),('queued','sending'),('sending','sent'),('sending','queued'),
 ('sending','integrity'),('sending','conflict'),('sending','failed'),('sent','confirmed'),('sent','queued'),
 ('sent','integrity'),('confirmed','queued'),('failed','queued'),('conflict','queued'),('integrity','queued'),('queued','integrity');
CREATE TRIGGER IF NOT EXISTS tr_state BEFORE UPDATE OF state ON instances
 WHEN NEW.state <> OLD.state AND NOT EXISTS (SELECT 1 FROM transitions WHERE src = OLD.state AND dst = NEW.state)
 BEGIN SELECT RAISE(ABORT, 'transição de estado inválida'); END;
-- confirmada só reabre por reconciliação (central declarou a instância ausente, ex.: após restauração)
CREATE TRIGGER IF NOT EXISTS tr_confirmed_final BEFORE UPDATE ON instances
 WHEN OLD.state = 'confirmed' AND (NEW.sha256 <> OLD.sha256 OR (NEW.state <> 'confirmed'
      AND NOT (NEW.state = 'queued' AND coalesce(NEW.last_error, '') LIKE 'reconcile:%')))
 BEGIN SELECT RAISE(ABORT, 'instância confirmada é final (só reabre por reconciliação)'); END;

CREATE TABLE IF NOT EXISTS studies (                      -- manifesto local por estudo
  study_uid TEXT PRIMARY KEY, manifest_sha256 TEXT, declared_at TEXT, central_status TEXT, checked_at TEXT) STRICT;

CREATE TABLE IF NOT EXISTS journal (                      -- diário local enxuto (sem PHI), rotacionado
  id INTEGER PRIMARY KEY, at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  sop_uid TEXT, src TEXT, dst TEXT, detail TEXT) STRICT;
CREATE TRIGGER IF NOT EXISTS tr_journal AFTER UPDATE OF state ON instances WHEN NEW.state <> OLD.state
 BEGIN INSERT INTO journal (sop_uid, src, dst, detail) VALUES (NEW.sop_uid, OLD.state, NEW.state, NEW.last_error); END;
