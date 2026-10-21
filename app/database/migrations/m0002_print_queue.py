"""Migração 0002 — fila de impressão (Fase 4).

* ``autoprint_pending``: instâncias recebidas aguardando o agrupamento por série para impressão
  automática. Fica no banco (e não só em memória) para que uma queda do processo entre o
  recebimento e a criação do trabalho não perca o pedido.
* ``jobs``: prioridade (usada pelas regras da Fase 6), nome do documento enviado ao spooler,
  caminho do arquivo gerado (impressora PDF) e último estado observado no spooler do Windows.
"""

VERSION = 2
NAME = "print_queue"

SQL = r"""
CREATE TABLE autoprint_pending (
    instance_id INTEGER PRIMARY KEY REFERENCES instances(id) ON DELETE CASCADE,
    group_key   TEXT NOT NULL,
    device_id   INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    source_ae   TEXT,
    modality    TEXT,
    received_at TEXT NOT NULL
);
CREATE INDEX ix_autoprint_group ON autoprint_pending(group_key, received_at);

ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN document_name TEXT;
ALTER TABLE jobs ADD COLUMN output_path TEXT;
ALTER TABLE jobs ADD COLUMN spool_status TEXT;
ALTER TABLE jobs ADD COLUMN spool_checked_at TEXT;
CREATE INDEX ix_jobs_queue ON jobs(state, priority, id);
"""
