"""Resolução dos diretórios de dados.

Nada é gravado no diretório do executável. No Windows:

* dados da máquina (banco, imagens, cache, backups, logs do serviço):
  ``%ProgramData%\\VYONIX\\DICOM Print``
* dados do usuário (logs da interface, exportações):
  ``%LOCALAPPDATA%\\VYONIX\\DICOM Print``

Para desenvolvimento e testes, ``VYONIX_HOME`` (ou ``--data-dir``) isola tudo em
uma única pasta.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

COMPANY_DIR = "VYONIX"
PRODUCT_DIR = "DICOM Print"
ENV_HOME = "VYONIX_HOME"
DB_FILENAME = "vyonix.db"


@dataclass(frozen=True)
class AppPaths:
    machine_root: Path
    user_root: Path

    # --- máquina -----------------------------------------------------------
    @property
    def database_dir(self) -> Path:
        return self.machine_root / "database"

    @property
    def database_file(self) -> Path:
        return self.database_dir / DB_FILENAME

    @property
    def storage_dir(self) -> Path:
        return self.machine_root / "storage"

    @property
    def cache_dir(self) -> Path:
        return self.machine_root / "cache"

    @property
    def temp_dir(self) -> Path:
        return self.machine_root / "temp"

    @property
    def backups_dir(self) -> Path:
        return self.machine_root / "backups"

    @property
    def output_dir(self) -> Path:
        """PDFs gerados pela impressora VYONIX PDF e por impressoras de arquivo (ex.: Microsoft Print to PDF)."""
        return self.machine_root / "output"

    @property
    def service_logs_dir(self) -> Path:
        return self.machine_root / "logs"

    # --- usuário -----------------------------------------------------------
    @property
    def user_logs_dir(self) -> Path:
        return self.user_root / "logs"

    @property
    def exports_dir(self) -> Path:
        return self.user_root / "exports"

    def all_dirs(self) -> list[Path]:
        return [
            self.database_dir, self.storage_dir, self.cache_dir, self.temp_dir,
            self.backups_dir, self.output_dir, self.service_logs_dir, self.user_logs_dir, self.exports_dir,
        ]

    def ensure(self) -> "AppPaths":
        for d in self.all_dirs():
            d.mkdir(parents=True, exist_ok=True)
        return self

    def logs_dir_for(self, role: str) -> Path:
        """O serviço grava em ProgramData; a interface, no perfil do usuário."""
        return self.service_logs_dir if role == "service" else self.user_logs_dir


def resolve_paths(
    override: str | os.PathLike[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> AppPaths:
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform

    home = override if override is not None else env.get(ENV_HOME)
    if home:
        root = Path(home).expanduser().resolve()
        return AppPaths(machine_root=root / "machine", user_root=root / "user")

    if platform == "win32":
        program_data = env.get("PROGRAMDATA") or r"C:\ProgramData"
        local_app = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return AppPaths(
            machine_root=Path(program_data) / COMPANY_DIR / PRODUCT_DIR,
            user_root=Path(local_app) / COMPANY_DIR / PRODUCT_DIR,
        )

    # Linux/macOS: somente para desenvolvimento.
    base = Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "vyonix"
    return AppPaths(machine_root=base / "machine", user_root=base / "user")


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
