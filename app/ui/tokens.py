"""Tokens de cor dos temas claro e escuro (sem Qt — testáveis em qualquer ambiente).

Os tokens derivam da paleta oficial (``app.brand.COLORS``), que não é alterada. Onde a cor da
marca não atinge o contraste mínimo como **texto** (WCAG 2.2 AA: 4,5:1 para texto normal; 3:1
para bordas e elementos gráficos), o tema usa uma variante mais escura/clara só para o texto e
mantém a cor da marca nos preenchimentos (ex.: botão principal).

Pares de contraste verificados por ``tests/test_ui_tokens.py`` (``CONTRAST_PAIRS``).
"""

from __future__ import annotations

from app.brand import COLORS

LIGHT = {
    "bg": "#F4F6F9", "surface": "#FFFFFF", "surface_alt": COLORS["silver_light"],
    "text": "#14202E", "muted": "#5B6B7F", "border": "#D7DEE7", "border_strong": "#8795A8",
    "nav_bg": COLORS["navy"], "nav_text": "#C9D4E3", "nav_active": COLORS["blue"],
    "accent": COLORS["blue"], "accent_hover": COLORS["blue_dark"],
    "accent_fill": COLORS["blue"], "accent_fill_hover": COLORS["blue_dark"], "on_accent": "#FFFFFF",
    # verde e âmbar da marca têm 3,4:1 sobre branco — variantes escuras para texto
    "ok": "#0F7B0B", "warn": "#8F5B00", "err": COLORS["red"],
    "input_bg": "#FFFFFF", "disabled_text": "#8A97A8",
    "tooltip_bg": "#14202E", "tooltip_text": "#FFFFFF",
    "scroll_handle": "#768498", "scroll_handle_hover": "#5B6B7F",
}
DARK = {
    "bg": "#0E1520", "surface": "#162131", "surface_alt": "#1C2A3D",
    "text": "#E7EDF5", "muted": "#93A3B8", "border": "#2A3A50", "border_strong": "#5A6D87",
    "nav_bg": "#08111D", "nav_text": "#AEBBCD", "nav_active": COLORS["blue"],
    # o azul da marca tem 3,6:1 sobre o fundo escuro — texto em azul claro; botões continuam no azul da marca
    "accent": "#5C9AFF", "accent_hover": "#8AB6FF",
    "accent_fill": COLORS["blue"], "accent_fill_hover": COLORS["blue_dark"], "on_accent": "#FFFFFF",
    "ok": "#2DBE3A", "warn": "#E0A030", "err": "#F0614F",
    "input_bg": "#101A28", "disabled_text": "#6B7C93",
    "tooltip_bg": "#E7EDF5", "tooltip_text": "#0E1520",
    "scroll_handle": "#62779A", "scroll_handle_hover": "#8496B3",
}

THEMES = {"light": LIGHT, "dark": DARK}

# (primeiro plano, fundo, mínimo) — texto 4,5:1; bordas/elementos gráficos 3:1 (WCAG 2.2, 1.4.3 e 1.4.11)
_TEXT_BGS = ("bg", "surface", "surface_alt", "input_bg")
CONTRAST_PAIRS: tuple[tuple[str, str, float], ...] = (
    *((fg, bg, 4.5) for fg in ("text", "muted", "accent", "ok", "warn", "err") for bg in _TEXT_BGS),
    ("nav_text", "nav_bg", 4.5), ("on_accent", "accent_fill", 4.5), ("on_accent", "accent_fill_hover", 4.5),
    ("tooltip_text", "tooltip_bg", 4.5), ("text", "surface", 4.5),
    ("border_strong", "input_bg", 3.0), ("accent", "input_bg", 3.0),
    ("scroll_handle", "surface", 3.0), ("scroll_handle", "bg", 3.0),
)


def _channel(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    """Luminância relativa (WCAG 2.x)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"cor inválida: {hex_color}")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def contrast_failures(theme: dict[str, str]) -> list[str]:
    out = []
    for fg, bg, minimum in CONTRAST_PAIRS:
        r = contrast_ratio(theme[fg], theme[bg])
        if r < minimum:
            out.append(f"{fg} sobre {bg}: {r:.2f}:1 (mínimo {minimum}:1)")
    return out
