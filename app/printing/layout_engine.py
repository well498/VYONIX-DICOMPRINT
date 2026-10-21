"""Motor de layout (§9) — implementa ``core.contracts.LayoutEngine``.

* Páginas montadas **uma por vez** (gerador), em cinza de 8 bits; RGB só se houver imagem colorida
  (orçamento de memória do relatório de análise: A3 a 300 dpi = 16,6 MB por página em cinza).
* Grade linhas × colunas, margens, espaçamento, bordas, ordem de preenchimento (por linha ou por
  coluna), alinhamento, proporção preservada (ou esticada, se desligado).
* Cabeçalho (texto, logotipo, informações do exame) e rodapé (texto, numeração "Página i de n").
* Calibração: visual (LUT) aplicada só às imagens; geométrica (escala % e deslocamento em mm)
  aplicada a todo o conteúdo em torno do centro da página.
* A resolução (DPI) é a de **saída** no papel, nunca a resolução da imagem médica.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Sequence

from app.core.contracts import ComposedPage, RenderedImage
from app.core.errors import ValidationError
from app.imaging.calibration import CalibrationProfile, apply as apply_calibration
from app.printing.paper import PageGeometry, parse_layout, resolve_orientation

ALIGNMENTS = ("center", "top", "bottom", "left", "right", "top-left")


@dataclass(frozen=True)
class LayoutSpec:
    paper: str = "A4"
    custom_mm: tuple[float, float] | None = None
    orientation: str = "auto"
    layout: str = "1x1"
    margins_mm: tuple[float, float, float, float] = (10.0, 10.0, 10.0, 10.0)   # topo, direita, base, esquerda
    spacing_mm: float = 3.0
    border: bool = False
    border_mm: float = 0.3
    fill_order: str = "row"            # "row" (linha a linha) ou "column"
    align: str = "center"
    preserve_aspect: bool = True
    dpi: int = 300
    background: int = 255              # cor do papel nas áreas vazias (255 = branco)
    header_text: str = ""
    footer_text: str = ""
    logo_path: str | None = None
    exam_info: bool = True
    page_numbers: bool = True
    calibration: CalibrationProfile = field(default_factory=CalibrationProfile)

    def validate(self) -> "LayoutSpec":
        parse_layout(self.layout)
        if not 72 <= self.dpi <= 1200:
            raise ValidationError("Resolução de saída deve estar entre 72 e 1200 dpi.")
        if any(m < 0 or m > 60 for m in self.margins_mm):
            raise ValidationError("Margens devem estar entre 0 e 60 mm.")
        if not 0 <= self.spacing_mm <= 30:
            raise ValidationError("Espaçamento deve estar entre 0 e 30 mm.")
        if self.fill_order not in ("row", "column"):
            raise ValidationError("Ordem de preenchimento inválida.")
        if self.align not in ALIGNMENTS:
            raise ValidationError("Alinhamento inválido.")
        self.calibration.validate()
        return self


@dataclass(frozen=True)
class PageAnnotations:
    header_right: str = ""   # ex.: "CT · 20/10/2026 · Tomógrafo Sala 2"
    footer_left: str = ""


def _font(px: int):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=max(8, px))
    except TypeError:
        return ImageFont.load_default()


class Compositor:
    def __init__(self, spec: LayoutSpec, image_aspect: float | None = None) -> None:
        self.spec = spec.validate()
        self.rows, self.cols = parse_layout(spec.layout)
        orientation = resolve_orientation(spec.orientation, self.rows, self.cols, image_aspect)
        self.geom = PageGeometry.build(spec.paper, orientation, spec.custom_mm)
        self.px_per_mm = spec.dpi / 25.4
        self.width_px = round(self.geom.width_mm * self.px_per_mm)
        self.height_px = round(self.geom.height_mm * self.px_per_mm)
        self.cells = self.rows * self.cols

    @property
    def orientation(self) -> str:
        return self.geom.orientation

    def page_count(self, images: int) -> int:
        return max(1, math.ceil(images / self.cells))

    # -------------------------------------------------------------- geometria
    def _bands_mm(self) -> tuple[float, float]:
        s = self.spec
        header = 8.0 if (s.header_text or s.logo_path or s.exam_info) else 0.0
        footer = 6.0 if (s.footer_text or s.page_numbers) else 0.0
        return header, footer

    def cell_rects_mm(self) -> list[tuple[float, float, float, float]]:
        """Retângulos (x, y, w, h) em mm, na ordem de preenchimento."""
        s = self.spec
        top, right, bottom, left = s.margins_mm
        header, footer = self._bands_mm()
        x0, y0 = left, top + header
        w = self.geom.width_mm - left - right
        h = self.geom.height_mm - top - bottom - header - footer
        cw = (w - s.spacing_mm * (self.cols - 1)) / self.cols
        ch = (h - s.spacing_mm * (self.rows - 1)) / self.rows
        if cw <= 5 or ch <= 5:
            raise ValidationError("Margens e espaçamento não deixam espaço para as imagens neste papel.")
        order = ([(r, c) for r in range(self.rows) for c in range(self.cols)] if s.fill_order == "row"
                 else [(r, c) for c in range(self.cols) for r in range(self.rows)])
        return [(x0 + c * (cw + s.spacing_mm), y0 + r * (ch + s.spacing_mm), cw, ch) for r, c in order]

    def _to_px(self, x_mm: float, y_mm: float) -> tuple[int, int]:
        """Aplica a calibração geométrica (escala em torno do centro + deslocamento) e converte."""
        cal = self.spec.calibration
        k = cal.scale_percent / 100.0
        cx, cy = self.geom.width_mm / 2, self.geom.height_mm / 2
        x = cx + (x_mm - cx) * k + cal.offset_x_mm
        y = cy + (y_mm - cy) * k + cal.offset_y_mm
        return round(x * self.px_per_mm), round(y * self.px_per_mm)

    # -------------------------------------------------------------- montagem
    def compose_page(self, index: int, total: int, images: Sequence[RenderedImage | None],
                     annotations: PageAnnotations = PageAnnotations()) -> ComposedPage:
        import numpy as np
        from PIL import Image, ImageDraw

        s = self.spec
        color = any(img is not None and img.pixels.ndim == 3 for img in images)
        mode = "RGB" if color else "L"
        bg = (s.background,) * 3 if color else s.background
        page = Image.new(mode, (self.width_px, self.height_px), bg)
        draw = ImageDraw.Draw(page)
        ink = (0, 0, 0) if color else 0

        for img, (x, y, w, h) in zip(images, self.cell_rects_mm()):
            if img is None:      # célula vazia (ex.: Image Box sem imagem no DICOM Print)
                continue
            px = apply_calibration(img.pixels, s.calibration)
            pil = Image.fromarray(px)
            if pil.mode != mode:
                pil = pil.convert(mode)
            (cx0, cy0), (cx1, cy1) = self._to_px(x, y), self._to_px(x + w, y + h)
            cw, ch = max(1, cx1 - cx0), max(1, cy1 - cy0)
            if s.preserve_aspect:
                scale = min(cw / pil.width, ch / pil.height)
                tw, th = max(1, round(pil.width * scale)), max(1, round(pil.height * scale))
            else:
                tw, th = cw, ch
            pil = pil.resize((tw, th), Image.Resampling.LANCZOS)
            ox = {"left": 0, "top-left": 0, "right": cw - tw}.get(s.align, (cw - tw) // 2)
            oy = {"top": 0, "top-left": 0, "bottom": ch - th}.get(s.align, (ch - th) // 2)
            page.paste(pil, (cx0 + ox, cy0 + oy))
            if s.border:
                bw = max(1, round(s.border_mm * self.px_per_mm))
                draw.rectangle([cx0 + ox - bw, cy0 + oy - bw, cx0 + ox + tw + bw - 1, cy0 + oy + th + bw - 1],
                               outline=ink, width=bw)

        header, footer = self._bands_mm()
        top, right, bottom, left = s.margins_mm
        font = _font(round(3.2 * self.px_per_mm))
        if header:
            hx, hy = self._to_px(left, top)
            text_x = hx
            if s.logo_path and Path(s.logo_path).exists():
                try:
                    logo = Image.open(s.logo_path)
                    logo.thumbnail((round(30 * self.px_per_mm), round(6.5 * self.px_per_mm)))
                    page.paste(logo.convert(mode), (hx, hy))
                    text_x = hx + logo.width + round(3 * self.px_per_mm)
                except OSError:
                    pass
            if s.header_text:
                draw.text((text_x, hy), s.header_text, fill=ink, font=font)
            if s.exam_info and annotations.header_right:
                rx, _ = self._to_px(self.geom.width_mm - right, top)
                tw = draw.textlength(annotations.header_right, font=font)
                draw.text((rx - tw, hy), annotations.header_right, fill=ink, font=font)
        if footer:
            fx, fy = self._to_px(left, self.geom.height_mm - bottom - 4.5)
            left_text = " · ".join(t for t in (s.footer_text, annotations.footer_left) if t)
            if left_text:
                draw.text((fx, fy), left_text, fill=ink, font=font)
            if s.page_numbers:
                label = f"Página {index + 1} de {total}"
                rx, _ = self._to_px(self.geom.width_mm - right, 0)
                draw.text((rx - draw.textlength(label, font=font), fy), label, fill=ink, font=font)
        return ComposedPage(index=index, pixels=np.asarray(page), dpi=s.dpi)

    def iter_pages(self, count: int, get_image: Callable[[int], RenderedImage | None],
                   annotations: PageAnnotations = PageAnnotations()) -> Iterator[ComposedPage]:
        """Gera as páginas sob demanda; cada imagem é obtida (e liberada) dentro da sua página."""
        total = self.page_count(count)
        for p in range(total):
            idx = range(p * self.cells, min(count, (p + 1) * self.cells))
            yield self.compose_page(p, total, [get_image(i) for i in idx], annotations)


class LayoutEngine:
    """Implementação do contrato ``LayoutEngine`` (lista de páginas; para uso com poucas imagens)."""

    def __init__(self, spec: LayoutSpec) -> None:
        self.spec = spec

    def compose(self, images: Sequence[RenderedImage], page=None) -> list[ComposedPage]:
        aspect = images[0].pixels.shape[1] / images[0].pixels.shape[0] if images else None
        comp = Compositor(self.spec, aspect)
        return list(comp.iter_pages(len(images), lambda i: images[i]))
