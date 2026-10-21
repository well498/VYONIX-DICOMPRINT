"""Engine, sessões e contexto da clínica (tenant).

Cada transação começa com ``set_config('vyonix.tenant_id', <tenant>, true)``. As políticas de row
level security das tabelas (``FORCE``) só mostram e só aceitam linhas desse tenant; sem tenant
definido, nada é visível. O papel de serviço (``vyonix_service``, ``BYPASSRLS``) é usado apenas pelo
processador de eventos e pelo provisionamento.
"""

from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_tenant: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar("vyonix_tenant", default=None)


def current_tenant() -> uuid.UUID | None:
    return _tenant.get()


@contextmanager
def tenant_scope(tenant_id: uuid.UUID | str | None) -> Iterator[None]:
    tok = _tenant.set(uuid.UUID(str(tenant_id)) if tenant_id else None)
    try:
        yield
    finally:
        _tenant.reset(tok)


def _url(url: str) -> str:
    # driver psycopg 3; aceita postgresql://… e postgres://…
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Database:
    def __init__(self, url: str, *, service_url: str | None = None, pool_size: int = 10) -> None:
        self.engine: Engine = create_engine(_url(url), pool_size=pool_size, max_overflow=10, pool_pre_ping=True,
                                            future=True)
        self.service_engine: Engine = create_engine(_url(service_url or url), pool_size=4, pool_pre_ping=True,
                                                    future=True)
        self._factory = sessionmaker(self.engine, expire_on_commit=False)
        self._service_factory = sessionmaker(self.service_engine, expire_on_commit=False)
        for f in (self._factory, self._service_factory):
            event.listen(f, "after_begin", _set_tenant)

    @contextmanager
    def session(self, tenant_id: uuid.UUID | str | None = None) -> Iterator[Session]:
        """Sessão da aplicação (RLS). Confirma no fim; desfaz em erro."""
        with tenant_scope(tenant_id) if tenant_id is not None else _keep():
            s = self._factory()
            s.info["tenant_id"] = current_tenant()
            try:
                yield s
                s.commit()
            except BaseException:
                s.rollback()
                raise
            finally:
                s.close()

    @contextmanager
    def service_session(self, tenant_id: uuid.UUID | str | None = None) -> Iterator[Session]:
        """Sessão do papel de serviço (sem RLS): processador de eventos e provisionamento."""
        with tenant_scope(tenant_id) if tenant_id is not None else _keep():
            s = self._service_factory()
            s.info["tenant_id"] = current_tenant()
            try:
                yield s
                s.commit()
            except BaseException:
                s.rollback()
                raise
            finally:
                s.close()

    def dispose(self) -> None:
        self.engine.dispose()
        self.service_engine.dispose()


@contextmanager
def _keep() -> Iterator[None]:
    yield


def _set_tenant(session: Session, transaction, connection) -> None:
    tid = session.info.get("tenant_id") or current_tenant()
    connection.execute(text("SELECT set_config('vyonix.tenant_id', :t, true)"), {"t": str(tid) if tid else ""})
