"""Migração 0008 — pausa operacional do sistema (Prompt Mestre §19).

``operation_state`` guarda uma única linha: se o sistema está pausado, desde quando, por quem e
por quê. Fica no banco (e não em memória) porque a interface e o serviço Windows são processos
diferentes: a interface pausa e o processador da fila, no serviço, obedece.
"""

VERSION = 8
NAME = "operation_control"

SQL = r"""
CREATE TABLE operation_state (
    id     INTEGER PRIMARY KEY CHECK (id = 1),
    paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
    since  TEXT,
    actor  TEXT,
    reason TEXT
);
INSERT INTO operation_state(id, paused) VALUES (1, 0);
"""
