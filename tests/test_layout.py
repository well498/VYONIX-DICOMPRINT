"""Fase 4 — papel, layouts e montagem de páginas."""

import unittest

try:
    import numpy as np
    import PIL  # noqa: F401
    HAS = True
except ImportError:
    HAS = False

from app.core.errors import ValidationError
from tests.helpers import TempDirTestCase


class PaperTest(unittest.TestCase):
    def test_layouts_and_papers(self):
        from app.printing.paper import LAYOUTS, PageGeometry, paper_mm, parse_layout, resolve_orientation
        self.assertEqual([parse_layout(x) for x in LAYOUTS][:3], [(1, 1), (1, 2), (2, 1)])
        self.assertEqual(parse_layout("4 × 4"), (4, 4))
        for bad in ("0x1", "9x1", "2-3", ""):
            with self.assertRaises(ValidationError):
                parse_layout(bad)
        self.assertEqual(paper_mm("A3"), (297.0, 420.0))
        self.assertEqual(paper_mm("14INX17IN"), (355.6, 431.8))
        with self.assertRaises(ValidationError):
            paper_mm("custom", (10, 10))
        self.assertEqual(resolve_orientation("auto", 1, 2), "landscape")
        self.assertEqual(resolve_orientation("auto", 2, 1), "portrait")
        self.assertEqual(resolve_orientation("auto", 1, 1, image_aspect=1.6), "landscape")
        g = PageGeometry.build("A4", "landscape")
        self.assertEqual((g.width_mm, g.height_mm), (297.0, 210.0))


@unittest.skipUnless(HAS, "numpy/Pillow não instalados")
class CompositorTest(TempDirTestCase):
    def img(self, h=100, w=80, value=0, color=False):
        from app.core.contracts import RenderedImage
        shape = (h, w, 3) if color else (h, w)
        return RenderedImage(pixels=np.full(shape, value, dtype=np.uint8), photometric="RGB" if color else "MONOCHROME2",
                             pixel_spacing_mm=None, applied={})

    def test_a4_and_a3_page_sizes_at_dpi(self):
        from app.printing.layout_engine import Compositor, LayoutSpec
        c = Compositor(LayoutSpec(paper="A4", orientation="portrait", dpi=150))
        self.assertEqual((c.width_px, c.height_px), (1240, 1754))
        c = Compositor(LayoutSpec(paper="A3", orientation="landscape", dpi=100))
        self.assertEqual((c.width_px, c.height_px), (1654, 1169))

    def test_grid_pages_and_gray_memory(self):
        from app.printing.layout_engine import Compositor, LayoutSpec
        c = Compositor(LayoutSpec(layout="2x2", dpi=100, exam_info=False, page_numbers=True))
        pages = list(c.iter_pages(5, lambda i: self.img(value=0)))
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0].pixels.ndim, 2)            # cinza, sem RGB desnecessário
        self.assertEqual(pages[0].pixels.dtype, np.uint8)
        # Página 2 tem só uma imagem: a área das demais células fica branca
        self.assertGreater(pages[1].pixels.mean(), pages[0].pixels.mean())

    def test_fill_order_column(self):
        from app.printing.layout_engine import Compositor, LayoutSpec
        row = Compositor(LayoutSpec(layout="2x2")).cell_rects_mm()
        col = Compositor(LayoutSpec(layout="2x2", fill_order="column")).cell_rects_mm()
        self.assertEqual(row[1][1], row[0][1])               # 2ª imagem ao lado
        self.assertEqual(col[1][0], col[0][0])               # 2ª imagem abaixo

    def test_preserve_aspect_and_margins(self):
        from app.printing.layout_engine import Compositor, LayoutSpec
        spec = LayoutSpec(layout="1x1", dpi=72, margins_mm=(20, 20, 20, 20), exam_info=False, page_numbers=False,
                          orientation="portrait")
        page = Compositor(spec).compose_page(0, 1, [self.img(h=100, w=100, value=0)]).pixels
        dark = np.argwhere(page < 128)
        h, w = dark.max(0) - dark.min(0) + 1
        self.assertAlmostEqual(h / w, 1.0, delta=0.02)       # imagem quadrada continua quadrada
        self.assertGreaterEqual(dark.min(0)[1], round(20 * 72 / 25.4) - 1)   # respeita a margem

    def test_color_page_only_when_needed(self):
        from app.printing.layout_engine import Compositor, LayoutSpec
        c = Compositor(LayoutSpec(layout="1x2", dpi=72))
        page = c.compose_page(0, 1, [self.img(), self.img(color=True, value=200)])
        self.assertEqual(page.pixels.ndim, 3)

    def test_geometric_calibration_scales_content(self):
        from app.imaging.calibration import CalibrationProfile
        from app.printing.layout_engine import Compositor, LayoutSpec
        base = LayoutSpec(layout="1x1", dpi=72, exam_info=False, page_numbers=False, orientation="portrait")

        def extent(spec):
            px = Compositor(spec).compose_page(0, 1, [self.img(h=100, w=100)]).pixels
            d = np.argwhere(px < 128)
            return (d.max(0) - d.min(0) + 1)[1]
        normal = extent(base)
        smaller = extent(LayoutSpec(**{**base.__dict__, "calibration": CalibrationProfile(scale_percent=90)}))
        self.assertAlmostEqual(smaller / normal, 0.9, delta=0.02)

    def test_annotations_and_visual_calibration(self):
        from app.imaging.calibration import CalibrationProfile
        from app.printing.layout_engine import Compositor, LayoutSpec, PageAnnotations
        spec = LayoutSpec(layout="1x1", dpi=100, header_text="Clínica Teste", footer_text="Rodapé",
                          calibration=CalibrationProfile(black_level=0.2))
        page = Compositor(spec).compose_page(0, 1, [self.img(value=0)], PageAnnotations(header_right="CT · 20/10/2026")).pixels
        self.assertEqual(int(np.median(page[page.shape[0] // 2])), round(0.2 * 255))   # preto calibrado
        self.assertEqual(int(page[: round(18 * 100 / 25.4)].min()), 0)                 # texto do cabeçalho em preto

    def test_invalid_specs(self):
        from app.printing.layout_engine import Compositor, LayoutSpec
        for spec in (LayoutSpec(dpi=10), LayoutSpec(margins_mm=(0, 0, 0, 99)), LayoutSpec(layout="2x"),
                     LayoutSpec(paper="A5", layout="8x8", spacing_mm=30)):
            with self.assertRaises(ValidationError):
                Compositor(spec).cell_rects_mm()
