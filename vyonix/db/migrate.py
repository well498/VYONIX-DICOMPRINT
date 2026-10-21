"""Migrações Alembic do CORE (um ramo por módulo; o CORE é o ramo ``core``)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine

from vyonix.db.session import _url

HERE = Path(__file__).resolve().parent


def alembic_config(owner_url: str, prefix: str = "vyonix") -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(HERE / "migrations"))
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("version_locations", str(HERE / "migrations" / "versions"))
    cfg.attributes["owner_url"] = owner_url
    cfg.attributes["role_prefix"] = prefix
    return cfg


def upgrade(owner_url: str, *, prefix: str = "vyonix", target: str = "heads") -> None:
    cfg = alembic_config(owner_url, prefix)
    eng = create_engine(_url(owner_url), future=True)
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, target)
    eng.dispose()


def current(owner_url: str) -> list[str]:
    from alembic.runtime.migration import MigrationContext
    eng = create_engine(_url(owner_url), future=True)
    with eng.connect() as conn:
        heads = list(MigrationContext.configure(conn, opts={"version_table_schema": "platform"}).get_current_heads())
    eng.dispose()
    return heads
