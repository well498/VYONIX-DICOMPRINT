"""Provisionamento do banco: papéis com privilégio mínimo, banco e migrações.

Papéis (por instalação):

* ``<prefixo>_owner``   — dono do esquema; usado só pelas migrações (``BYPASSRLS``);
* ``<prefixo>_app``     — API do CORE; **não** é dono das tabelas, e o row level security é forçado;
* ``<prefixo>_service`` — processador de eventos e provisionamento (``BYPASSRLS``), sem DDL.

Executado pelo VYONIX DEPLOY (Fase 2) e pelos testes, com uma conexão administrativa.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

from sqlalchemy import create_engine, text

from vyonix.db.session import _url

_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


@dataclass
class DatabaseUrls:
    owner: str
    app: str
    service: str


def _with_user(admin_url: str, user: str, password: str, dbname: str) -> str:
    u = urlsplit(admin_url)
    host = u.hostname or "localhost"
    netloc = f"{quote(user)}:{quote(password)}@{host}" + (f":{u.port}" if u.port else "")
    return urlunsplit((u.scheme, netloc, "/" + dbname, u.query, ""))


def provision(admin_url: str, dbname: str, *, prefix: str = "vyonix", passwords: dict[str, str] | None = None
              ) -> DatabaseUrls:
    if not _IDENT.match(dbname) or not _IDENT.match(prefix):
        raise ValueError("Nome de banco ou prefixo inválido.")
    pw = dict(passwords or {})
    for r in ("owner", "app", "service"):
        pw.setdefault(r, secrets.token_urlsafe(24))
    eng = create_engine(_url(admin_url), isolation_level="AUTOCOMMIT", future=True)
    roles = {"owner": "LOGIN BYPASSRLS", "app": "LOGIN NOBYPASSRLS", "service": "LOGIN BYPASSRLS"}
    with eng.connect() as c:
        for r, attrs in roles.items():
            name = f"{prefix}_{r}"
            exists = c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": name}).first()
            lit = "'" + pw[r].replace("'", "''") + "'"           # DDL não aceita parâmetro
            c.execute(text(f"{'ALTER' if exists else 'CREATE'} ROLE {name} {attrs} NOSUPERUSER NOCREATEDB "
                           f"NOCREATEROLE PASSWORD {lit}".replace(":", "\\:")))
        if not c.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": dbname}).first():
            c.execute(text(f'CREATE DATABASE "{dbname}" OWNER {prefix}_owner ENCODING \'UTF8\' TEMPLATE template0'))
        c.execute(text(f'REVOKE ALL ON DATABASE "{dbname}" FROM PUBLIC'))
        c.execute(text(f'GRANT CONNECT, TEMPORARY ON DATABASE "{dbname}" TO {prefix}_app, {prefix}_service'))
    eng.dispose()
    u = urlsplit(admin_url)
    admin_db = urlunsplit((u.scheme, u.netloc, "/" + dbname, u.query, ""))
    eng = create_engine(_url(admin_db), isolation_level="AUTOCOMMIT", future=True)
    with eng.connect() as c:
        c.execute(text("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
        c.execute(text(f"GRANT ALL ON SCHEMA public TO {prefix}_owner"))
    eng.dispose()
    return DatabaseUrls(owner=_with_user(admin_url, f"{prefix}_owner", pw["owner"], dbname),
                        app=_with_user(admin_url, f"{prefix}_app", pw["app"], dbname),
                        service=_with_user(admin_url, f"{prefix}_service", pw["service"], dbname))


def drop(admin_url: str, dbname: str, *, roles: list[str] | None = None) -> None:
    """Remove o banco (e, se informados, os papéis — só usado em testes e desinstalação completa)."""
    eng = create_engine(_url(admin_url), isolation_level="AUTOCOMMIT", future=True)
    with eng.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        for r in roles or []:
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", r):
                raise ValueError(f"Nome de papel inválido: {r}")
            c.execute(text(f"DROP ROLE IF EXISTS {r}"))
    eng.dispose()
