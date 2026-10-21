"""Banco PostgreSQL real para os testes da plataforma.

Exige ``VYONIX_TEST_ADMIN_URL`` (superusuário ou papel com CREATEDB/CREATEROLE). Um banco temporário
é criado por processo, migrado e removido no fim. Sem a variável, os testes são pulados com motivo
explícito — nunca simulados.
"""

from __future__ import annotations

import atexit
import os
import secrets
import unittest
import uuid

ADMIN_URL = os.environ.get("VYONIX_TEST_ADMIN_URL", "")
_state: dict = {}


def require_db():
    if not ADMIN_URL:
        raise unittest.SkipTest("VYONIX_TEST_ADMIN_URL não definida (PostgreSQL de teste).")
    if "db" not in _state:
        from vyonix.db import migrate, provision
        from vyonix.db.session import Database
        name = f"vyx_t_{secrets.token_hex(4)}"
        prefix = f"vyxt{secrets.token_hex(3)}"
        urls = provision.provision(ADMIN_URL, name, prefix=prefix,
                                   passwords={k: secrets.token_urlsafe(16) for k in ("owner", "app", "service")})
        migrate.upgrade(urls.owner, prefix=prefix)
        db = Database(urls.app, service_url=urls.service)
        _state.update(db=db, urls=urls, name=name, prefix=prefix)

        def cleanup():
            db.dispose()
            if not os.environ.get("VYONIX_TEST_KEEP_DB"):
                provision.drop(ADMIN_URL, name, roles=[f"{prefix}_{r}" for r in ("owner", "app", "service")])
        atexit.register(cleanup)
    return _state["db"]


def urls():
    require_db()
    return _state["urls"]


ADMIN_PW = "Senha-Forte-123"


def new_org(db, code: str | None = None, **kw) -> uuid.UUID:
    from vyonix.tenancy import service as tenancy
    return tenancy.create_organization(db, code=code or f"org-{secrets.token_hex(4)}", name="Clínica Teste",
                                       admin_username="admin", admin_password=ADMIN_PW, **kw)
