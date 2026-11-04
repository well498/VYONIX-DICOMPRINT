"""Montagem da plataforma em execução: configuração, banco, licenciamento, eventos e chaves locais."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vyonix.config import Config
from vyonix.db.session import Database
from vyonix.events.bus import Bus
from vyonix.licensing.service import Licensing
from vyonix.secrets import SecretStore


@dataclass
class Platform:
    cfg: Config
    db: Database
    bus: Bus
    mfa_key: bytes
    licensing: Licensing | None = None    # legado: sem uso pela plataforma (mantido para compatibilidade)
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def edge(self) -> bool:
        return self.cfg.edge


def build_bus() -> Bus:
    from vyonix.clinical import service as clinical
    from vyonix.pacs import forward
    from vyonix.ris import service as ris
    bus = Bus()
    clinical.register_consumers(bus)
    ris.register_consumers(bus)
    forward.register_consumers(bus)
    return bus


def build(cfg: Config, *, licensing: Licensing | None = None, db: Database | None = None) -> Platform:
    if not cfg.database_url and db is None:
        raise RuntimeError("Banco de dados não configurado (database_url). Execute 'vyonix-core init'.")
    db = db or Database(cfg.database_url, service_url=cfg.service_database_url)
    store = SecretStore(cfg.data_dir)
    # A plataforma não depende de licença (decisão de 04/11/2026): não monta o licenciamento nem lê/grava o cofre,
    # o Installation ID, o Hardware ID ou o horário confiável compartilhados com o VYONIX DICOM Print.
    return Platform(cfg=cfg, db=db, licensing=licensing, bus=build_bus(), mfa_key=store.get_or_create("mfa_key", 32))
