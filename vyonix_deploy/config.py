"""Opções de uma implantação (o que o administrador escolhe). Segredos nunca ficam aqui."""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from vyonix_deploy.errors import DeployError

ORG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")


@dataclass
class NetworkChoice:
    mode: str = "keep"                 # keep | static
    interface: str | None = None       # alias da interface (static)
    ip: str | None = None
    prefix: int | None = None
    gateway: str | None = None
    dns: list[str] = field(default_factory=list)
    confirmed: bool = False            # confirmação explícita da mudança de IP

    def validate(self) -> None:
        if self.mode not in ("keep", "static"):
            raise DeployError("Rede: escolha manter o IP atual ou IP fixo.")
        if self.mode == "static":
            if not (self.interface and self.ip and self.prefix and self.gateway):
                raise DeployError("IP fixo: informe interface, IP, prefixo e gateway.")
            try:
                net = ipaddress.ip_interface(f"{self.ip}/{self.prefix}")
                gw = ipaddress.ip_address(self.gateway)
                for d in self.dns:
                    ipaddress.ip_address(d)
            except ValueError as exc:
                raise DeployError(f"IP fixo: endereço inválido ({exc}).") from None
            if net.version != 4 or gw not in net.network:
                raise DeployError("IP fixo: o gateway precisa estar na mesma rede IPv4.")


@dataclass
class DeployConfig:
    organization: str = "clinica"
    organization_name: str = "Clínica"
    admin_user: str = "admin"
    https_port: int = 8444
    pg_port: int = 5544
    firewall_sources: list[str] = field(default_factory=list)      # vazio = rede local (perfis privado/domínio)
    tls_pfx: str | None = None                                      # certificado da instituição (.pfx)
    network: NetworkChoice = field(default_factory=NetworkChoice)
    modules: list[str] = field(default_factory=list)                # módulos a habilitar além do core
    shortcuts: bool = True
    restore_backup: str | None = None                               # só na execução "restore"
    pacs_backup_dir: str | None = None          # backup diário do PACS; vazio = ProgramData\VYONIX\Backups\PACS
    pacs_backup_hour: int = 2                   # hora local (0–23) a partir da qual o backup diário roda

    def validate(self) -> None:
        if not ORG_RE.match(self.organization):
            raise DeployError("Código da organização: minúsculas, números e hífen (2 a 40).")
        for p in (self.https_port, self.pg_port):
            if not 1024 <= int(p) <= 65535:
                raise DeployError(f"Porta inválida: {p} (use 1024–65535).")
        if self.https_port == self.pg_port:
            raise DeployError("As portas HTTPS e do banco precisam ser diferentes.")
        for s in self.firewall_sources:
            try:
                ipaddress.ip_network(s, strict=False)
            except ValueError:
                raise DeployError(f"Origem de firewall inválida: {s}") from None
        if not 0 <= int(self.pacs_backup_hour) <= 23:
            raise DeployError("Hora do backup do PACS: de 0 a 23.")
        self.network.validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DeployConfig":
        d = dict(d)
        net = NetworkChoice(**(d.pop("network", None) or {}))
        known = set(cls.__dataclass_fields__)
        unknown = set(d) - known
        if unknown:
            raise DeployError(f"Opções desconhecidas: {', '.join(sorted(unknown))}")
        return cls(network=net, **d)

    @classmethod
    def load(cls, path) -> "DeployConfig":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
