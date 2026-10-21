"""Pasta de dados do License Manager.

* **Portátil** (``VYONIX_License_Manager.exe`` executado de qualquer pasta): os dados ficam em
  ``VYONIX_License_Manager_Dados`` ao lado do executável — o pen drive/pasta inteira é levável. Se a
  pasta não for gravável (ex.: CD, pasta protegida), usa ``%APPDATA%\\VYONIX\\License Manager``.
* **Instalado** (``VYONIX_License_Manager_Setup.exe``, em Arquivos de Programas, com o marcador
  ``installed.flag``): ``%APPDATA%\\VYONIX\\License Manager`` do usuário administrador.
* ``--data-dir`` ou ``VYONIX_LM_HOME``: pasta explícita.

O banco do License Manager nunca é o banco do VYONIX DICOM Print.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

PORTABLE_DIR = "VYONIX_License_Manager_Dados"


@dataclass(frozen=True)
class LMPaths:
    root: Path
    mode: str                 # portable | installed | custom

    @property
    def db_file(self) -> Path:
        return self.root / "license_manager.db"

    @property
    def backups_dir(self) -> Path:
        return self.root / "backups"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exportados"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> "LMPaths":
        for p in (self.root, self.backups_dir, self.exports_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)
        return self


def exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _appdata() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "VYONIX" / "License Manager"


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".gravacao"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def resolve(data_dir: str | None = None) -> LMPaths:
    explicit = data_dir or os.environ.get("VYONIX_LM_HOME")
    if explicit:
        return LMPaths(Path(explicit).expanduser().resolve(), "custom")
    here = exe_dir()
    if (here / "installed.flag").exists():
        return LMPaths(_appdata(), "installed")
    if getattr(sys, "frozen", False) and _writable(here / PORTABLE_DIR):
        return LMPaths(here / PORTABLE_DIR, "portable")
    return LMPaths(_appdata(), "portable" if getattr(sys, "frozen", False) else "custom")
