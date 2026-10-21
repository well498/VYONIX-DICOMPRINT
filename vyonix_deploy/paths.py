"""Locais da instalação."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _program_data() -> Path:
    return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))


def _program_files() -> Path:
    return Path(os.environ.get("ProgramW6432") or os.environ.get("PROGRAMFILES", r"C:\Program Files"))


@dataclass(frozen=True)
class Paths:
    install_dir: Path          # binários (Program Files\VYONIX\Platform)
    data_dir: Path             # dados do Core (ProgramData\VYONIX\Platform)
    deploy_dir: Path           # banco do DEPLOY, relatórios (ProgramData\VYONIX\Deploy)
    pg_data: Path              # cluster PostgreSQL (ProgramData\VYONIX\PostgreSQL\17\data)
    backups: Path              # backups antes de atualizar (ProgramData\VYONIX\Backups)
    licensing: Path            # cofre compartilhado com o DICOM Print

    @property
    def reports(self) -> Path:
        return self.deploy_dir / "relatorios"

    @property
    def db_file(self) -> Path:
        return self.deploy_dir / "deploy.db"

    @property
    def pg_bin(self) -> Path:
        return self.install_dir / "pgsql" / "bin"

    @property
    def core_exe(self) -> Path:
        return self.install_dir / "VyonixPlatform.exe"

    def all(self) -> dict[str, str]:
        return {k: str(getattr(self, k)) for k in ("install_dir", "data_dir", "deploy_dir", "pg_data", "backups",
                                                   "licensing")}


def default_paths(root: Path | None = None) -> Paths:
    """Padrão do Windows. ``root`` (ou ``VYONIX_DEPLOY_ROOT``) isola tudo numa pasta (testes)."""
    root = root or (Path(os.environ["VYONIX_DEPLOY_ROOT"]) if os.environ.get("VYONIX_DEPLOY_ROOT") else None)
    if root is not None:
        return Paths(root / "Platform", root / "data" / "Platform", root / "data" / "Deploy",
                     root / "data" / "PostgreSQL" / "17" / "data", root / "data" / "Backups",
                     root / "data" / "Licensing")
    if sys.platform != "win32":
        base = Path("/var/lib/vyonix")
        return Paths(Path("/opt/vyonix"), base / "platform", base / "deploy", base / "postgresql" / "17" / "data",
                     base / "backups", base / "licensing")
    pd = _program_data() / "VYONIX"
    return Paths(_program_files() / "VYONIX" / "Platform", pd / "Platform", pd / "Deploy",
                 pd / "PostgreSQL" / "17" / "data", pd / "Backups", pd / "Licensing")
