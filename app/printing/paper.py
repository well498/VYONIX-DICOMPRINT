"""Formatos de papel, filmes DICOM e layouts (§9)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.errors import ValidationError

# Tamanhos em milímetros (largura x altura, retrato).
PAPER_SIZES: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
    "A5": (148.0, 210.0),
    "Tabloid": (279.4, 431.8),
}
PAPER_LABELS = {"A4": "A4 (210 × 297 mm)", "A3": "A3 (297 × 420 mm)", "Letter": "Carta (216 × 279 mm)",
                "Legal": "Ofício (216 × 356 mm)", "A5": "A5 (148 × 210 mm)", "Tabloid": "Tabloide (279 × 432 mm)"}

# Film Size ID do DICOM Print (PS3.3 C.13.8) → milímetros.
FILM_SIZES: dict[str, tuple[float, float]] = {
    "8INX10IN": (203.2, 254.0), "8_5INX11IN": (215.9, 279.4), "10INX12IN": (254.0, 304.8),
    "10INX14IN": (254.0, 355.6), "11INX14IN": (279.4, 355.6), "11INX17IN": (279.4, 431.8),
    "14INX14IN": (355.6, 355.6), "14INX17IN": (355.6, 431.8), "24CMX24CM": (240.0, 240.0),
    "24CMX30CM": (240.0, 300.0), "A4": (210.0, 297.0), "A3": (297.0, 420.0),
}

# Windows DMPAPER_* (wingdi.h) para os formatos padrão.
DMPAPER = {"Letter": 1, "Legal": 5, "A3": 8, "A4": 9, "A5": 11, "Tabloid": 3}

LAYOUTS: tuple[str, ...] = ("1x1", "1x2", "2x1", "2x2", "2x3", "3x2", "3x3", "4x4")
_LAYOUT_RE = re.compile(r"^\s*(\d{1,2})\s*[xX×]\s*(\d{1,2})\s*$")


def parse_layout(value: str) -> tuple[int, int]:
    """'2x3' → (2 linhas, 3 colunas). Até 8 x 8."""
    m = _LAYOUT_RE.match(value or "")
    if not m:
        raise ValidationError(f"Layout inválido: {value!r} (use linhas x colunas, ex.: 2x3).")
    rows, cols = int(m[1]), int(m[2])
    if not (1 <= rows <= 8 and 1 <= cols <= 8):
        raise ValidationError("O layout deve ter de 1 a 8 linhas e de 1 a 8 colunas.")
    return rows, cols


def layout_label(value: str) -> str:
    r, c = parse_layout(value)
    return f"{r} × {c} ({r} {'linha' if r == 1 else 'linhas'}, {c} {'coluna' if c == 1 else 'colunas'})"


def paper_mm(name: str, custom: tuple[float, float] | None = None) -> tuple[float, float]:
    if name == "custom":
        if not custom or min(custom) < 50 or max(custom) > 1200:
            raise ValidationError("Papel personalizado: informe largura e altura entre 50 e 1200 mm.")
        return float(custom[0]), float(custom[1])
    if name in PAPER_SIZES:
        return PAPER_SIZES[name]
    if name in FILM_SIZES:
        return FILM_SIZES[name]
    raise ValidationError(f"Formato de papel desconhecido: {name}.")


def resolve_orientation(orientation: str, rows: int, cols: int, image_aspect: float | None = None) -> str:
    """'auto': paisagem quando a grade tem mais colunas que linhas (ou a imagem única é larga)."""
    if orientation in ("portrait", "landscape"):
        return orientation
    if rows == cols == 1 and image_aspect:
        return "landscape" if image_aspect > 1.05 else "portrait"
    return "landscape" if cols > rows else "portrait"


@dataclass(frozen=True)
class PageGeometry:
    width_mm: float
    height_mm: float
    orientation: str

    @classmethod
    def build(cls, paper: str, orientation: str, custom: tuple[float, float] | None = None) -> "PageGeometry":
        w, h = paper_mm(paper, custom)
        w, h = min(w, h), max(w, h)
        if orientation == "landscape":
            w, h = h, w
        return cls(w, h, orientation)
