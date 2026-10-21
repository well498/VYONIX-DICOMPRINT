"""Folha de teste de calibração 3 × 3 (nove versões da mesma imagem) e rodadas progressivas.

* Modos: Gama × Contraste, Brilho × Contraste, Gama × Brilho — o terceiro parâmetro fica fixo.
* Três níveis por eixo: centro − passo, centro, centro + passo (passo 0,1; 0,2; 0,5 ou 1,0). Perto
  dos limites (−5/+5) a janela é deslocada para manter três valores distintos, e isso é informado.
* Linhas = primeiro parâmetro do modo; colunas = segundo (ex.: linhas G, colunas C).
* Cada célula tem uma faixa própria para o rótulo ``IMAGEM 05 | B +0,5 | C +1,0 | G −0,5`` — o texto
  nunca é escrito sobre a imagem.
* Cada versão passa pelo **mesmo pipeline** da impressão real (``ImagingService.render`` com os
  controles tonais no estágio em ponto flutuante + calibração da impressora).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from app.core.contracts import ComposedPage, PresentationParams, RenderedImage
from app.core.errors import ValidationError
from app.imaging import tone
from app.imaging.calibration import CalibrationProfile, apply as apply_calibration
from app.printing.paper import PageGeometry

MODES: dict[str, tuple[str, str, str]] = {
    "gamma_contrast": ("gamma", "contrast", "Gama × Contraste"),
    "brightness_contrast": ("brightness", "contrast", "Brilho × Contraste"),
    "gamma_brightness": ("gamma", "brightness", "Gama × Brilho"),
}
STEPS = (0.1, 0.2, 0.5, 1.0)
SHORT = {"brightness": "B", "contrast": "C", "gamma": "G"}
TITLE = "VYONIX — Teste de Calibração"


def axis_values(center: float, step: float) -> tuple[list[float], bool]:
    """Três valores distintos em torno do centro; ``True`` se a janela precisou ser deslocada."""
    if step not in STEPS:
        raise ValidationError("Incremento deve ser 0,1; 0,2; 0,5 ou 1,0.")
    c = tone.snap(center)
    lo, hi = c - step, c + step
    shifted = False
    if lo < tone.MIN - 1e-9:
        lo, shifted = tone.MIN, True
    elif hi > tone.MAX + 1e-9:
        lo, shifted = tone.MAX - 2 * step, True
    return [tone.snap(lo + i * step) for i in range(3)], shifted


@dataclass(frozen=True)
class Cell:
    index: int           # 1..9
    row: int
    col: int
    tone: tone.ToneControls

    def label(self) -> str:
        t = self.tone
        return (f"IMAGEM {self.index:02d} | B {tone.fmt(t.brightness)} | C {tone.fmt(t.contrast)} | "
                f"G {tone.fmt(t.gamma)}")

    def to_json(self) -> dict[str, Any]:
        return {"index": self.index, "row": self.row, "col": self.col, **self.tone.to_json()}


@dataclass(frozen=True)
class Matrix:
    mode: str
    step: float
    center: tone.ToneControls
    cells: list[Cell]
    notes: list[str]

    @property
    def axes(self) -> tuple[str, str]:
        return MODES[self.mode][0], MODES[self.mode][1]

    def cell(self, index: int) -> Cell:
        for c in self.cells:
            if c.index == index:
                return c
        raise ValidationError("Escolha uma imagem de 1 a 9.")


def build_matrix(center: tone.ToneControls, mode: str, step: float) -> Matrix:
    if mode not in MODES:
        raise ValidationError("Modo de comparação inválido.")
    center = center.validate()
    row_key, col_key, _ = MODES[mode]
    rows, row_shift = axis_values(getattr(center, row_key), step)
    cols, col_shift = axis_values(getattr(center, col_key), step)
    notes = []
    for key, shifted in ((row_key, row_shift), (col_key, col_shift)):
        if shifted:
            notes.append(f"{tone.LABELS[key]} perto do limite: os três valores foram deslocados para "
                         f"permanecerem distintos dentro de −5,0 a +5,0.")
    cells = []
    for r, rv in enumerate(rows):
        for c, cv in enumerate(cols):
            cells.append(Cell(index=r * 3 + c + 1, row=r, col=c,
                              tone=center.with_(**{row_key: rv, col_key: cv})))
    return Matrix(mode=mode, step=step, center=center, cells=cells, notes=notes)


def compose(matrix: Matrix, render: Callable[[PresentationParams, int], RenderedImage], *, paper: str = "A4",
            orientation: str = "landscape", dpi: int = 200, info: dict[str, str] | None = None,
            calibration: CalibrationProfile | None = None, margin_mm: float = 10.0) -> ComposedPage:
    """Monta a folha. ``render(params, max_side_px)`` devolve a imagem já pelo pipeline real."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    def font(px: int):
        from app.utils.fonts import print_font
        return print_font(px)

    geom = PageGeometry.build(paper, orientation if orientation in ("portrait", "landscape") else "landscape")
    k = dpi / 25.4
    W, H = round(geom.width_mm * k), round(geom.height_mm * k)
    page = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(page)
    m = round(margin_mm * k)
    title_font, info_font, label_font = font(round(6 * k)), font(round(3.2 * k)), font(round(3.0 * k))
    d.text((m, m), TITLE, fill=0, font=title_font)
    info = info or {}
    line = " · ".join(f"{k_}: {v}" for k_, v in info.items() if v)
    d.text((m, m + round(8 * k)), line, fill=0, font=info_font)
    row_key, col_key, mode_label = MODES[matrix.mode]
    d.text((m, m + round(13 * k)),
           f"Modo {mode_label} · incremento {tone.fmt(matrix.step).lstrip('+')} · linhas: {tone.LABELS[row_key]} · "
           f"colunas: {tone.LABELS[col_key]} · fixo: " + ", ".join(
               f"{tone.LABELS[x]} {tone.fmt(getattr(matrix.center, x))}" for x in ("brightness", "contrast", "gamma")
               if x not in (row_key, col_key)), fill=0, font=info_font)
    top = m + round(19 * k)
    gap = round(3 * k)
    label_h = round(5.5 * k)
    cell_w = (W - 2 * m - 2 * gap) // 3
    cell_h = (H - top - m - 2 * gap) // 3
    img_h = cell_h - label_h
    if cell_w < 20 or img_h < 20:
        raise ValidationError("Papel pequeno demais para a folha 3 × 3.")
    max_side = max(cell_w, img_h)
    cal = calibration or CalibrationProfile()
    for cell in matrix.cells:
        x0 = m + cell.col * (cell_w + gap)
        y0 = top + cell.row * (cell_h + gap)
        rendered = render(cell.tone.to_params(), max_side)
        px = apply_calibration(rendered.pixels, cal)
        im = Image.fromarray(px)
        if im.mode != "L":
            im = im.convert("L")
        scale = min(cell_w / im.width, img_h / im.height)
        tw, th = max(1, round(im.width * scale)), max(1, round(im.height * scale))
        im = im.resize((tw, th), Image.Resampling.LANCZOS)
        page.paste(im, (x0 + (cell_w - tw) // 2, y0 + (img_h - th) // 2))
        d.rectangle([x0, y0, x0 + cell_w - 1, y0 + cell_h - 1], outline=0, width=max(1, round(0.2 * k)))
        # faixa do rótulo, separada da área da imagem
        d.rectangle([x0, y0 + img_h, x0 + cell_w - 1, y0 + cell_h - 1], fill=255, outline=0,
                    width=max(1, round(0.2 * k)))
        d.text((x0 + round(1.5 * k), y0 + img_h + round(1.2 * k)), cell.label(), fill=0, font=label_font)
    return ComposedPage(index=0, pixels=np.asarray(page), dpi=dpi)


def sheet_info(*, device: str | None, modality: str | None, printer: str | None, paper: str,
               when: datetime | None = None) -> dict[str, str]:
    return {"Equipamento": device or "—", "Modalidade": modality or "—", "Impressora": printer or "—",
            "Papel": paper, "Data": (when or datetime.now()).strftime("%d/%m/%Y %H:%M")}
