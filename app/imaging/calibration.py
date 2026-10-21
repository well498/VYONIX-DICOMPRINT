"""Calibração de impressão (§7).

Separação exigida pela especificação:

* **Calibração visual** (este módulo): brilho, contraste, gama, inversão e níveis de preto e
  branco da saída, aplicados por uma LUT de 256 entradas sobre a imagem já apresentada (8 bits).
  Corrige a resposta de cada impressora "a olho", com o padrão de teste.
* **Calibração geométrica**: escala física (%) e deslocamento (mm), usados pelo motor de layout
  (Fase 4) para que 10 cm na imagem saiam com 10 cm no papel.
* **Calibração instrumental** (densitômetro, curva GSDF/PS3.14): procedimento físico externo,
  fora do escopo deste módulo — o VYONIX não afirma conformidade com a GSDF.

O padrão de teste é gerado em memória (nenhum arquivo fixo como ``last_image.png``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

from app.core.errors import ValidationError

LIMITS = {
    "brightness": (-0.5, 0.5), "contrast": (0.25, 3.0), "gamma": (0.3, 3.0),
    "black_level": (0.0, 0.4), "white_level": (0.6, 1.0),
    "scale_percent": (80.0, 120.0), "offset_x_mm": (-30.0, 30.0), "offset_y_mm": (-30.0, 30.0),
}


@dataclass(frozen=True)
class CalibrationProfile:
    brightness: float = 0.0
    contrast: float = 1.0
    gamma: float = 1.0
    invert: bool = False
    black_level: float = 0.0      # menor nível de saída (0 = preto total)
    white_level: float = 1.0      # maior nível de saída (1 = branco do papel)
    scale_percent: float = 100.0
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0

    def validate(self) -> "CalibrationProfile":
        errors = []
        for name, (lo, hi) in LIMITS.items():
            value = float(getattr(self, name))
            if not lo <= value <= hi:
                errors.append(f"{name} deve estar entre {lo:g} e {hi:g}")
        if self.black_level >= self.white_level:
            errors.append("o nível de preto deve ser menor que o de branco")
        if errors:
            raise ValidationError("Perfil de calibração inválido: " + "; ".join(errors))
        return self

    def is_identity(self) -> bool:
        return self.visual_dict() == CalibrationProfile().visual_dict()

    def visual_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("scale_percent", "offset_x_mm", "offset_y_mm"):
            d.pop(k)
        return d

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> "CalibrationProfile":
        if not data:
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known}).validate()


def lut(profile: CalibrationProfile):
    """LUT uint8[256] da calibração visual (ordem: inversão, contraste, brilho, gama, níveis)."""
    import numpy as np
    v = np.arange(256, dtype=np.float32) / 255.0
    if profile.invert:
        v = 1.0 - v
    v = (v - 0.5) * np.float32(profile.contrast) + 0.5 + np.float32(profile.brightness)
    v = np.clip(v, 0.0, 1.0)
    if profile.gamma != 1.0:
        v = np.power(v, np.float32(1.0 / profile.gamma))
    v = profile.black_level + v * (profile.white_level - profile.black_level)
    return (np.clip(v, 0, 1) * 255.0 + 0.5).astype(np.uint8)


def apply(img, profile: CalibrationProfile):
    """Aplica a calibração visual a uma imagem uint8 (cinza ou RGB)."""
    if profile.is_identity():
        return img
    return lut(profile)[img]


def test_pattern(width_px: int = 1600, height_px: int = 1200, dpi: int = 150, *, title: str = "VYONIX"):
    """Padrão de teste em tons de cinza (uint8), com régua em mm calculada pelo DPI.

    Contém: escala de 21 degraus identificados (0–100% a cada 5%), gradiente contínuo, retalhos de
    baixo contraste nos extremos (0/2/5% e 95/98/100%), barras de resolução, elementos geométricos
    (círculo, quadrado, triângulo), régua de 10 cm nos dois eixos e mira central.
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("L", (width_px, height_px), 255)
    d = ImageDraw.Draw(img)
    from app.utils.fonts import print_font
    font = print_font(max(12, height_px // 60))
    m = width_px // 40
    mm = dpi / 25.4

    # Escala de 21 degraus
    top, h = m * 3, height_px // 7
    step_w = (width_px - 2 * m) / 21
    for i in range(21):
        level = round(255 * i / 20)
        x0 = m + i * step_w
        d.rectangle([x0, top, x0 + step_w, top + h], fill=level)
        d.text((x0 + 2, top + h + 4), f"{i * 5}", fill=0, font=font)
    # Gradiente contínuo
    gtop = top + h + m * 2
    grad = np.tile(np.linspace(0, 255, width_px - 2 * m, dtype=np.float32), (h // 2, 1)).astype(np.uint8)
    img.paste(Image.fromarray(grad, "L"), (m, gtop))
    # Baixo contraste nos extremos
    ptop = gtop + h // 2 + m
    pw = (width_px - 2 * m) // 6
    for i, level in enumerate((0, 5, 13, 242, 250, 255)):   # 0, 2, 5, 95, 98, 100 %
        d.rectangle([m + i * pw, ptop, m + (i + 1) * pw, ptop + h // 2], fill=level)
    # Barras de resolução (1 a 4 px)
    btop = ptop + h // 2 + m
    x = m
    for px in (1, 2, 3, 4):
        for k in range(10):
            d.rectangle([x, btop, x + px - 1, btop + h // 2], fill=0 if k % 2 == 0 else 255)
            x += px
        x += m
    # Elementos geométricos (círculo, quadrado e triângulo) para conferir proporção e nitidez de bordas
    gsize = h // 2
    gx = max(x + m, width_px // 2)
    if gx + 3 * (gsize + m) < width_px - 2 * m:
        d.ellipse([gx, btop, gx + gsize, btop + gsize], outline=0, width=max(2, gsize // 25))
        gx += gsize + m
        d.rectangle([gx, btop, gx + gsize, btop + gsize], outline=0, width=max(2, gsize // 25))
        d.rectangle([gx + gsize // 4, btop + gsize // 4, gx + 3 * gsize // 4, btop + 3 * gsize // 4], fill=128)
        gx += gsize + m
        d.polygon([(gx + gsize // 2, btop), (gx, btop + gsize), (gx + gsize, btop + gsize)], outline=0, fill=64)
    # Réguas de 10 cm (marcas a cada 1 cm e 1 mm)
    rx0, ry = m, height_px - m * 2
    length = int(100 * mm)
    if rx0 + length < width_px - m:
        d.line([rx0, ry, rx0 + length, ry], fill=0, width=2)
        for i in range(101):
            tick = (m // 2) if i % 10 == 0 else (m // 5)
            xx = rx0 + round(i * mm)
            d.line([xx, ry, xx, ry - tick], fill=0, width=1)
        d.text((rx0, ry + 4), "10 cm", fill=0, font=font)
    rx = width_px - m * 2
    if top + length < height_px - m * 3:
        d.line([rx, top, rx, top + length], fill=0, width=2)
        for i in range(101):
            tick = (m // 2) if i % 10 == 0 else (m // 5)
            yy = top + round(i * mm)
            d.line([rx, yy, rx - tick, yy], fill=0, width=1)
    # Mira central e título
    cx, cy = width_px // 2, height_px // 2
    d.line([cx - m, cy, cx + m, cy], fill=0, width=1)
    d.line([cx, cy - m, cx, cy + m], fill=0, width=1)
    d.text((m, m), f"{title} — padrão de teste de impressão · {dpi} dpi", fill=0, font=font)
    return np.asarray(img, dtype=np.uint8)
