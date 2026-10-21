"""Configuração do CORE.

Fontes, em ordem de prioridade: variáveis de ambiente ``VYONIX_*`` → arquivo ``config.json`` na pasta
de dados → padrões. Segredos (senhas do banco, chave de sessão) nunca ficam em texto claro no arquivo:
são guardados por ``vyonix.secrets`` (DPAPI no Windows; arquivo com permissão restrita nos demais).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MODES = ("edge", "cloud")


def default_data_dir() -> Path:
    env = os.environ.get("VYONIX_DATA_DIR")
    if env:
        return Path(env)
    if sys.platform == "win32":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "VYONIX" / "Platform"
    return Path("/var/lib/vyonix")


@dataclass
class Config:
    data_dir: Path
    mode: str = "edge"
    database_url: str = ""               # papel da aplicação (RLS aplicado)
    service_database_url: str = ""       # papel de serviço (worker, provisionamento; ignora RLS)
    owner_database_url: str = ""         # dono do esquema (migrações)
    bind: str = "0.0.0.0"
    port: int = 8444
    tls_cert: str | None = None
    tls_key: str | None = None
    session_minutes: int = 30
    licensing_dir: Path | None = None    # cofre de licenciamento compartilhado com o DICOM Print
    default_organization: str = "default"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def edge(self) -> bool:
        return self.mode == "edge"

    @property
    def licensing_state_dir(self) -> Path:
        if self.licensing_dir:
            return Path(self.licensing_dir)
        if sys.platform == "win32" and not os.environ.get("VYONIX_DATA_DIR"):
            return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "VYONIX" / "Licensing"
        return self.data_dir / "licensing"


def load(data_dir: Path | None = None, **overrides: Any) -> Config:
    d = Path(data_dir) if data_dir else default_data_dir()
    values: dict[str, Any] = {}
    f = d / "config.json"
    if f.exists():
        values.update(json.loads(f.read_text(encoding="utf-8")))
    env = {
        "mode": "VYONIX_MODE", "database_url": "VYONIX_DATABASE_URL",
        "service_database_url": "VYONIX_SERVICE_DATABASE_URL", "owner_database_url": "VYONIX_OWNER_DATABASE_URL",
        "bind": "VYONIX_BIND", "port": "VYONIX_PORT", "tls_cert": "VYONIX_TLS_CERT", "tls_key": "VYONIX_TLS_KEY",
        "licensing_dir": "VYONIX_LICENSING_DIR",
    }
    for key, var in env.items():
        if os.environ.get(var):
            values[key] = os.environ[var]
    values.update({k: v for k, v in overrides.items() if v is not None})
    known = {k for k in Config.__dataclass_fields__ if k not in ("data_dir", "extra")}
    cfg = Config(data_dir=d, **{k: v for k, v in values.items() if k in known},
                 extra={k: v for k, v in values.items() if k not in known})
    cfg.port = int(cfg.port)
    if cfg.mode not in MODES:
        raise ValueError(f"Modo inválido: {cfg.mode} (use edge ou cloud).")
    from vyonix import secrets as sec
    store = sec.SecretStore(d)
    for key in ("database_url", "service_database_url", "owner_database_url"):
        val = getattr(cfg, key)
        if val and "{secret:" in val:
            setattr(cfg, key, store.expand(val))
    if not cfg.service_database_url:
        cfg.service_database_url = cfg.database_url
    if not cfg.owner_database_url:
        cfg.owner_database_url = cfg.service_database_url
    return cfg
