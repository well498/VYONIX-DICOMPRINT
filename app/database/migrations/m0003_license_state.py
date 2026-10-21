"""Migração 0003 — estado do licenciamento (Fase 8).

``license_state`` guarda o maior horário já observado (detecção de relógio atrasado de propósito
para estender uma licença com validade) e o resultado da última verificação.
"""

VERSION = 3
NAME = "license_state"

SQL = r"""
CREATE TABLE license_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
