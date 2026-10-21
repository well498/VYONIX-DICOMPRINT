"""Localização de recursos somente-leitura distribuídos com a aplicação (logotipo, ícones).

Funciona tanto a partir do código-fonte quanto empacotado pelo PyInstaller
(``sys._MEIPASS``). Recursos nunca são gravados — dados vão para ``app.utils.paths``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle) if bundle else Path(__file__).resolve().parents[2]


def assets_dir() -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "assets"
    return Path(__file__).resolve().parents[2] / "assets"


def asset_path(name: str) -> Path:
    path = (assets_dir() / name).resolve()
    if assets_dir().resolve() not in path.parents:
        raise ValueError(f"Recurso fora da pasta de assets: {name}")
    return path
