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


def heads(prefix: str = "vyonix") -> list[str]:
    """Revisões finais conhecidas por esta versão do código (o banco deve estar nelas)."""
    from alembic.script import ScriptDirectory
    return list(ScriptDirectory.from_config(alembic_config("", prefix)).get_heads())


def applied(current_revs: list[str], prefix: str = "vyonix") -> set[str]:
    """Todas as revisões já aplicadas, a partir das gravadas na tabela de versões.

    O Alembic grava só as revisões "de ponta": uma revisão que é ancestral ou dependência (``depends_on``)
    de outra aplicada não aparece (ex.: com ``pacs_0001`` dependendo de ``core_0001``, a tabela tem só
    ``pacs_0001``). Aqui o grafo é percorrido pelas revisões anteriores e pelas dependências."""
    from alembic.script import ScriptDirectory
    script = ScriptDirectory.from_config(alembic_config("", prefix))
    seen: set[str] = set()
    stack = list(current_revs)
    while stack:
        rid = stack.pop()
        if not rid or rid in seen:
            continue
        rev = script.get_revision(rid)
        if rev is None:
            continue
        seen.add(rev.revision)
        for attr in (rev.down_revision, rev.dependencies):
            if not attr:
                continue
            for x in ((attr,) if isinstance(attr, str) else attr):
                r = script.get_revision(x)          # aceita identificador ou rótulo de ramo
                if r is not None:
                    stack.append(r.revision)
    return seen


def up_to_date(current_revs: list[str], prefix: str = "vyonix") -> bool:
    """O banco tem todas as revisões finais desta versão do código (nada a migrar)."""
    return bool(current_revs) and set(heads(prefix)) <= applied(current_revs, prefix)
