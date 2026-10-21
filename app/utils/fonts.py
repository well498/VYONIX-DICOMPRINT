"""Fonte das páginas impressas (cabeçalho, rodapé, rótulos, padrão de teste).

Usa a DejaVu Sans distribuída com o programa (cobre acentos do português e o sinal de menos "−"); na
falta dela, a Arial do Windows; por último, a fonte embutida do Pillow (sem acentos).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from app.utils.resources import assets_dir


@lru_cache(maxsize=64)
def print_font(px: int, bold: bool = False):
    from PIL import ImageFont
    px = max(8, int(px))
    names = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    candidates = [assets_dir() / "fonts" / n for n in names]
    windir = os.environ.get("WINDIR")
    if windir:
        candidates.append(Path(windir) / "Fonts" / ("arialbd.ttf" if bold else "arial.ttf"))
    for path in candidates:
        try:
            if path.exists():
                return ImageFont.truetype(str(path), px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        return ImageFont.load_default()
