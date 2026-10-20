"""Registro ordenado das migrações. Novas migrações são apenas acrescentadas ao final."""

from __future__ import annotations

from app.database.migrations import m0001_initial
from app.database.migrator import Migration

MIGRATIONS: tuple[Migration, ...] = (
    Migration(m0001_initial.VERSION, m0001_initial.NAME, m0001_initial.SQL),
)
