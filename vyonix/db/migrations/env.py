from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, text

from vyonix.db.base import TENANT_SCHEMAS, Base
from vyonix.db import models  # noqa: F401 - registra os modelos
from vyonix.db.session import _url

config = context.config
target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in TENANT_SCHEMAS
    return True


def run(connection) -> None:
    for s in TENANT_SCHEMAS:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {s}"))
    context.configure(connection=connection, target_metadata=target_metadata, include_schemas=True,
                      include_name=include_name, version_table_schema="platform", compare_type=True)
    with context.begin_transaction():
        context.run_migrations(role_prefix=config.attributes.get("role_prefix", "vyonix"))


conn = config.attributes.get("connection")
if conn is not None:
    run(conn)
else:
    eng = create_engine(_url(config.attributes["owner_url"]), future=True)
    with eng.begin() as c:
        run(c)
