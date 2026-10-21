"""Prompt mestre atualizado — equipamentos independentes, calibração −5..+5, matriz 3 × 3, BMP 3000 × 206.

Cada teste referencia o critério de aceitação (seção 11) que cobre.
"""

import json
import unittest
from pathlib import Path

try:
    import numpy as np
    import PIL  # noqa: F401
    import pynetdicom  # noqa: F401
    HAS = True
except ImportError:
    HAS = False

from app.core.errors import SettingsValidationError, ValidationError
from tests.helpers import TempDirTestCase


class ToneTest(unittest.TestCase):
    def test_scale_steps_and_format(self):                     # critérios 3, 4, 5, 6
        from app.imaging import tone
        self.assertEqual(tone.step_value(0.0, +1), 0.5)
        self.assertEqual(tone.step_value(0.0, -1), -0.5)
        self.assertEqual(tone.step_value(4.8, +1), 5.0)          # limite superior
        self.assertEqual(tone.step_value(-5.0, -1), -5.0)        # limite inferior
        self.assertEqual(tone.step_value(1.0, +1, 0.1), 1.1)
        self.assertEqual(tone.step_value(1.0, -1, 0.2), 0.8)
        self.assertEqual([tone.fmt(v) for v in (-0.5, 0, 1.5)], ["−0,5", "0,0", "+1,5"])
        with self.assertRaises(ValidationError):
            tone.ToneControls(brightness=5.5).validate()
        with self.assertRaises(ValidationError):
            tone.ToneControls(gamma=0.25).validate()               # fora da grade de 0,1

    def test_math(self):                                         # critério 7
        from app.imaging import tone
        self.assertAlmostEqual(tone.gamma_real(-5), 0.5)
        self.assertAlmostEqual(tone.gamma_real(0), 1.0)
        self.assertAlmostEqual(tone.gamma_real(5), 2.0)
        self.assertAlmostEqual(tone.contrast_gain(0), 1.0)
        self.assertAlmostEqual(tone.brightness_offset(5), 0.25)
        v = np.array([0.0, 0.25, 0.5, 1.0], dtype=np.float32)
        np.testing.assert_allclose(tone.apply_float(v, tone.ToneControls()), v, atol=1e-6)   # 0 = neutro
        # Brilho: deslocamento; Contraste: ganho em torno de 0,5; Gama: v^(1/γ) (positivo clareia médios)
        np.testing.assert_allclose(tone.apply_float(v, tone.ToneControls(brightness=2)), np.clip(v + 0.1, 0, 1), atol=1e-6)
        out = tone.apply_float(v, tone.ToneControls(contrast=5))
        np.testing.assert_allclose(out, np.clip((v - 0.5) * 2 + 0.5, 0, 1), atol=1e-6)
        g = tone.apply_float(v, tone.ToneControls(gamma=5))
        self.assertAlmostEqual(float(g[1]), 0.25 ** 0.5, places=5)
        self.assertEqual((float(g[0]), float(g[3])), (0.0, 1.0))
        self.assertLess(float(tone.apply_float(v, tone.ToneControls(gamma=-5))[2]), 0.5)

    def test_pipeline_uses_same_transform(self):                 # critério 23 (base)
        from app.imaging import tone
        from app.imaging.pipeline import adjust
        t = tone.ToneControls(brightness=1.5, contrast=-2.0, gamma=0.5, invert=True)
        v = np.linspace(0, 1, 101, dtype=np.float32)
        a, _ = adjust(v, t.to_params())
        np.testing.assert_allclose(a, tone.apply_float(v, t), atol=1e-6)


@unittest.skipUnless(HAS, "numpy/Pillow/pynetdicom não instalados")
class DeviceIndependenceTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from app.bootstrap import bootstrap
        from app.printing.backends.pdf import PDF_PRINTER
        self.PDF = PDF_PRINTER
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        self.ctx.printers.refresh()
        self.ctx.settings.update({"printing.default_printer": PDF_PRINTER, "printing.dpi": 150}, actor="t")
        self.philips = self.ctx.devices.create({"name": "Philips Brilliance 16", "ae_title": "CT_PHILIPS",
                                                "modality": "CT", "ip_address": "127.0.0.1"}, actor="t", authorized=True)
        self.siemens = self.ctx.devices.create({"name": "Siemens Emotion 16", "ae_title": "CT_SIEMENS",
                                                "modality": "CT", "ip_address": "10.0.0.2"}, actor="t", authorized=True)
        self.ds = self.ctx.device_settings
        self.ds.save(self.philips.id, {"paper": "A3", "layout": "3x3", "brightness": 0.5, "contrast": 1.0,
                                       "gamma": -0.5}, actor="t")
        self.ds.save(self.siemens.id, {"paper": "A4", "layout": "2x2", "brightness": -0.5, "contrast": 1.5,
                                       "gamma": 0.5}, actor="t")

    def tearDown(self):
        self.ctx.close()
        super().tearDown()

    def resolve(self, device, dicom=None, rules=True):
        ev = self.ctx.jobs.evaluate_rules(source_type="storage", source_ae=device.ae_title, device_id=device.id,
                                          modality="CT", items=[]) if rules else None
        return self.ctx.jobs.resolve_for(device_id=device.id, modality="CT", rules=ev, dicom=dicom)

    def test_two_ct_devices_have_independent_settings(self):          # critérios 1, 2
        a, b = self.resolve(self.philips), self.resolve(self.siemens)
        self.assertEqual((a.values["paper"], a.values["layout"], a.values["brightness"], a.values["gamma"]),
                         ("A3", "3x3", 0.5, -0.5))
        self.assertEqual((b.values["paper"], b.values["layout"], b.values["contrast"], b.values["gamma"]),
                         ("A4", "2x2", 1.5, 0.5))
        self.assertIn("Philips", a.origins["paper"])
        self.assertIn("Siemens", b.origins["gamma"])
        self.ds.save(self.philips.id, {**self.ds.get(self.philips.id), "gamma": -2.0}, actor="t")
        self.assertEqual(self.resolve(self.siemens).values["gamma"], 0.5)       # o outro não muda

    def test_versions_restore_duplicate_compare(self):                # critérios 14, usabilidade 3, 4, 7
        v1 = self.ds.version(self.philips.id)
        self.ds.save_tone(self.philips.id, __import__("app.imaging.tone", fromlist=["x"]).ToneControls(1.0, 2.0, 3.0),
                          actor="t", reason="calibração")
        self.assertEqual(self.ds.get(self.philips.id)["gamma"], 3.0)
        self.ds.revert_calibration(self.philips.id, actor="t")
        self.assertEqual(self.ds.get(self.philips.id)["gamma"], -0.5)
        self.ds.restore(self.philips.id, v1, actor="t")
        self.assertEqual(self.ds.get(self.philips.id)["layout"], "3x3")
        # duplicar = cópia independente
        self.ds.copy_from(self.philips.id, self.siemens.id, actor="t")
        self.assertEqual(self.ds.get(self.siemens.id), self.ds.get(self.philips.id))
        self.ds.save(self.philips.id, {**self.ds.get(self.philips.id), "copies": 7}, actor="t")
        self.assertNotIn("copies", self.ds.get(self.siemens.id))
        diff = {label: d for label, _a, _b, d in self.ds.compare(self.philips.id, self.siemens.id)}
        self.assertTrue(diff["Cópias"])
        self.assertFalse(diff["Papel"])
        with self.assertRaises(SettingsValidationError):
            self.ds.save(self.philips.id, {"brightness": 7}, actor="t")
        self.assertGreaterEqual(len(self.ds.versions(self.philips.id)), 4)

    def test_hierarchy_rules_dicom_policy(self):                       # seção 1.3
        from app.rules.engine import Rule
        dicom = {"layout": "1x2", "orientation": "landscape", "copies": 3, "keep_positions": True}
        # padrão: equipamento prevalece sobre o pedido; o pedido vence o padrão global
        r = self.resolve(self.philips, dicom)
        self.assertEqual((r.values["layout"], r.values["copies"]), ("3x3", 3))
        self.assertEqual(r.origins["copies"], "Pedido DICOM Print")
        self.assertFalse(r.values["keep_positions"])          # layout do pedido não aplicado
        # política do equipamento: pedido prevalece
        self.ds.save(self.philips.id, {**self.ds.get(self.philips.id), "dicom_policy": "dicom_first"}, actor="t")
        r = self.resolve(self.philips, dicom)
        self.assertEqual((r.values["layout"], r.values["keep_positions"]), ("1x2", True))
        # regra do equipamento acima das configurações gerais do equipamento; regra de outro equipamento não vale
        self.ctx.rules.save(Rule(id=None, name="Philips noite", conditions=[], actions={"paper": "A4", "gamma": 2.0,
                                                                                        "dicom_policy": "ignore_dicom"},
                                 device_id=self.philips.id), actor="t")
        self.ctx.rules.save(Rule(id=None, name="Geral", conditions=[], actions={"paper": "A3", "copies": 2}), actor="t")
        r = self.resolve(self.philips, dicom)
        self.assertEqual((r.values["paper"], r.values["gamma"], r.values["layout"]), ("A4", 2.0, "3x3"))
        self.assertEqual(r.values["copies"], 2)                 # pedido ignorado; regra geral define cópias
        self.assertIn("do equipamento", r.origins["paper"])
        s = self.resolve(self.siemens, dicom)
        self.assertEqual((s.values["paper"], s.values["gamma"]), ("A3", 0.5))

    def test_auto_print_off_holds_job(self):                           # regra item 14
        from app.jobs.states import JobState
        self.ds.save(self.philips.id, {**self.ds.get(self.philips.id), "auto_print": False}, actor="t")
        jid = self._job_for(self.philips)
        self.assertEqual(self.ctx.jobs.get_job(jid).state, JobState.HELD)

    def _job_for(self, device):
        from tests.dicom_helpers import make_ct
        path = make_ct(self.tmp / f"{device.id}.dcm", rows=64, cols=64)
        from app.dicom.storage import InstanceStore  # noqa: F401
        from app.core.contracts import AssociationPeer
        peer = AssociationPeer(calling_ae=device.ae_title, called_ae="VYONIX", address=device.ip_address, port=1)
        out = self.ctx.store.store(path.read_bytes(), peer, device.id, max_bytes=10**8)
        iid = self.ctx.db.connection().execute("SELECT id FROM instances WHERE sop_instance_uid=?",
                                               (out.instance.sop_instance_uid,)).fetchone()[0]
        jid, _ = self.ctx.jobs.create(source_type="storage", items=[(iid, 0)], device_id=device.id,
                                      source_ae=device.ae_title, modality="CT")
        return jid

    def test_preview_equals_printed_output_and_tone_applied(self):     # critérios 9, 23
        captured = []

        class Capture:
            name = "pdf"

            def list_printers(self):
                return []

            def submit(self, request):
                from app.core.contracts import SpoolResult
                captured.extend(p.pixels for p in request.pages())
                return SpoolResult(accepted=True, spool_job_id=None, confirmed=True, detail="ok")

            def job_status(self, *a):
                return None
        self.ds.save(self.siemens.id, {**self.ds.get(self.siemens.id), "layout": "1x1"}, actor="t")
        jid = self._job_for(self.siemens)
        preview, _ = self.ctx.worker.preview(jid)
        self.ctx.printers._by_name[self.PDF] = Capture()
        self.ctx.worker.process(self.ctx.worker._claim())
        self.assertEqual(len(captured), 1)
        np.testing.assert_array_equal(preview[0].pixels, captured[0])
        # sem calibração do equipamento a página é diferente (o ajuste foi aplicado)
        self.ds.save(self.siemens.id, {"layout": "1x1"}, actor="t")
        jid2 = self._job_for(self.siemens)
        plain, _ = self.ctx.worker.preview(jid2)
        self.assertFalse(np.array_equal(plain[0].pixels, captured[0]))

    def test_settings_survive_restart(self):                           # critério 22
        from app.bootstrap import bootstrap
        self.ctx.close()
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        self.assertEqual(self.ctx.device_settings.get(self.philips.id)["layout"], "3x3")

    def test_same_ae_title_requires_distinct_ips(self):                # seção 1.1 (conflitos)
        d = self.ctx.devices.create({"name": "CT 3", "ae_title": "CT_SIEMENS", "ip_address": "10.0.0.3"},
                                    actor="t", authorized=True)
        with self.assertRaises(SettingsValidationError):
            self.ctx.devices.create({"name": "CT 4", "ae_title": "CT_SIEMENS"}, actor="t")
        repo = self.ctx.devices.repo
        self.assertEqual(repo.match("CT_SIEMENS", "10.0.0.3")[0].id, d.id)
        self.assertEqual(repo.match("CT_SIEMENS", "10.0.0.2")[0].id, self.siemens.id)
        dev, conflict = repo.match("CT_SIEMENS", "10.0.0.9")
        self.assertIsNone(dev)
        self.assertIn("conflito", conflict)


@unittest.skipUnless(HAS, "numpy/Pillow/pynetdicom não instalados")
class CalibrationSourcesAndMatrixTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from app.bootstrap import bootstrap
        from app.printing.backends.pdf import PDF_PRINTER
        self.PDF = PDF_PRINTER
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        self.ctx.printers.refresh()
        self.ctx.settings.update({"printing.default_printer": PDF_PRINTER}, actor="t")
        self.dev = self.ctx.devices.create({"name": "Philips", "ae_title": "CT_P", "modality": "CT"}, actor="t",
                                           authorized=True)

    def tearDown(self):
        self.ctx.close()
        super().tearDown()

    def test_load_dicom_and_common_images(self):                      # critério 8
        from PIL import Image
        from app.core.contracts import PresentationParams
        from app.imaging.decoder import DecodeError
        from app.imaging import tone
        from tests.dicom_helpers import make_ct
        dcm = make_ct(self.tmp / "semextensao", rows=32, cols=32)
        for ext, img in ((".jpg", Image.new("RGB", (40, 30), (90, 90, 90))), (".png", Image.new("L", (40, 30), 90)),
                         (".bmp", Image.new("RGB", (40, 30), (10, 200, 30)))):
            path = self.tmp / f"img{ext}"
            img.save(path)
            r = self.ctx.imaging.render(str(path), PresentationParams(), max_side=None)
            self.assertEqual(r.pixels.shape[:2], (30, 40))
        r = self.ctx.imaging.render(str(dcm), tone.ToneControls(brightness=2).to_params(), max_side=None)
        self.assertEqual(r.pixels.shape, (32, 32))
        bad = self.tmp / "texto.txt"
        bad.write_text("não é imagem")
        with self.assertRaisesRegex(DecodeError, "Formato não reconhecido"):
            self.ctx.imaging.render(str(bad), PresentationParams())
        r = self.ctx.imaging.render("pattern", PresentationParams(), max_side=400)
        self.assertLessEqual(max(r.pixels.shape), 400)

    def test_matrix_values_labels_and_edges(self):                    # critérios 10, 11
        from app.imaging import tone
        from app.printing import calibration_sheet as cs
        m = cs.build_matrix(tone.ToneControls(brightness=0.5, contrast=0.0, gamma=0.0), "gamma_contrast", 0.5)
        self.assertEqual(len(m.cells), 9)
        self.assertEqual(len({(c.tone.gamma, c.tone.contrast) for c in m.cells}), 9)
        self.assertEqual([c.tone.gamma for c in m.cells[:3]], [-0.5, -0.5, -0.5])       # linha = gama
        self.assertEqual([c.tone.contrast for c in m.cells[:3]], [-0.5, 0.0, 0.5])      # coluna = contraste
        self.assertTrue(all(c.tone.brightness == 0.5 for c in m.cells))                 # fixo
        self.assertEqual(m.cell(5).label(), "IMAGEM 05 | B +0,5 | C 0,0 | G 0,0")
        edge = cs.build_matrix(tone.ToneControls(gamma=5.0, contrast=-4.8), "gamma_contrast", 0.5)
        self.assertEqual(sorted({c.tone.gamma for c in edge.cells}), [4.0, 4.5, 5.0])
        self.assertEqual(sorted({c.tone.contrast for c in edge.cells}), [-5.0, -4.5, -4.0])
        self.assertEqual(len(edge.notes), 2)
        for mode in cs.MODES:
            self.assertEqual(len(cs.build_matrix(tone.ToneControls(), mode, 0.2).cells), 9)
        with self.assertRaises(ValidationError):
            cs.build_matrix(tone.ToneControls(), "gamma_contrast", 0.3)

    def test_progressive_rounds_print_choose_save(self):              # critérios 10–14
        from app.imaging import tone
        from app.jobs.states import JobState
        cal = self.ctx.calibration
        session = cal.new_session()
        rid, jid, m = cal.print_round(device_id=self.dev.id, session_id=session, center=tone.ToneControls(),
                                      mode="gamma_contrast", step=0.5, source="pattern", printer=self.PDF,
                                      paper="A4", actor="t", device_name="Philips", modality="CT")
        w = self.ctx.worker
        w.process(w._claim())
        job = self.ctx.jobs.get_job(jid)
        self.assertEqual(job.state, JobState.COMPLETED, job.state_reason)
        self.assertTrue(Path(job.output_path).exists())
        chosen = cal.choose(rid, 9, actor="t")
        self.assertEqual((chosen.gamma, chosen.contrast), (0.5, 0.5))
        rid2, jid2, m2 = cal.print_round(device_id=self.dev.id, session_id=session, center=chosen,
                                         mode="gamma_contrast", step=0.1, source="pattern", printer=self.PDF,
                                         paper="A3", actor="t")
        self.assertEqual(sorted({c.tone.gamma for c in m2.cells}), [0.4, 0.5, 0.6])
        rounds = cal.rounds(self.dev.id)
        self.assertEqual([r["round_no"] for r in rounds], [2, 1])
        self.assertEqual(rounds[1]["chosen_index"], 9)
        self.ctx.device_settings.save_tone(self.dev.id, chosen, actor="t", reason="calibração progressiva")
        self.assertEqual(self.ctx.device_settings.tone(self.dev.id), chosen)

    def test_sheet_page_has_nine_cells_and_reserved_label_band(self):
        from app.core.contracts import PresentationParams  # noqa: F401
        from app.imaging import tone
        from app.printing import calibration_sheet as cs
        m = cs.build_matrix(tone.ToneControls(), "brightness_contrast", 1.0)

        def render(params, max_side):
            return self.ctx.imaging.render("pattern", params, max_side=max_side)
        page = cs.compose(m, render, paper="A4", orientation="landscape", dpi=100,
                          info=cs.sheet_info(device="Philips", modality="CT", printer="X", paper="A4"))
        self.assertEqual(page.pixels.shape, (827, 1169))
        self.assertLess(int(page.pixels.min()), 50)

    def test_file_source_is_copied_for_the_service(self):
        from PIL import Image
        src = self.tmp / "minha.png"
        Image.new("L", (20, 20), 128).save(src)
        stored = self.ctx.calibration.stage_source(str(src))
        self.assertTrue(stored.startswith("file:"))
        path = Path(stored[5:])
        self.assertTrue(path.exists())
        self.assertIn("calibration_sources", str(path))


@unittest.skipUnless(HAS, "numpy/Pillow não instalados")
class PrintIdentityTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from app.printing.templates import TemplateStore
        self.store = TemplateStore(self.tmp / "machine")
        self.store.ensure()

    def test_default_templates(self):                                 # critério 17
        from app.printing import templates as t
        for kind in ("header", "footer"):
            info = self.store.info(kind)
            self.assertEqual((info.width, info.height, info.mode, info.format), (3000, 206, "RGB", "BMP"))
            data = self.store.path(kind).read_bytes()
            self.assertEqual(int.from_bytes(data[28:30], "little"), 24)       # 24 bits por pixel
            self.assertEqual(len(data), 54 + 3000 * 206 * 3)
        bundled = t.bundled_dir()
        for name in ("header.bmp", "footer.bmp"):
            self.assertTrue(t.inspect(bundled / name).is_standard)

    def test_custom_template_survives_update_startup(self):           # teste obrigatório 10
        """Atualização: o programa novo inicia e chama ensure(); a arte do cliente não é substituída."""
        import hashlib
        from PIL import Image
        from app.printing.templates import TemplateStore
        art = Image.new("RGB", (3000, 206), (255, 255, 255))
        art.paste((200, 0, 0), (0, 0, 1500, 206))
        src = self.tmp / "arte.bmp"
        art.save(src, "BMP")
        self.store.install("header", src)
        before = hashlib.sha256(self.store.path("header").read_bytes()).hexdigest()
        TemplateStore(self.tmp / "machine").ensure()                 # nova versão abrindo a mesma pasta
        after = hashlib.sha256(self.store.path("header").read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_custom_bmp_conversion_preserves_proportion(self):        # critérios 18, 19
        from PIL import Image
        from app.printing.templates import NeedsConversion
        art = Image.new("RGB", (600, 200), (255, 255, 255))
        art.paste((0, 0, 0), (0, 0, 600, 200))
        src = self.tmp / "logo.bmp"
        art.save(src)
        with self.assertRaises(NeedsConversion):
            self.store.install("header", src)
        info = self.store.install("header", src, convert=True)
        self.assertTrue(info.is_standard)
        img = np.asarray(Image.open(self.store.path("header")).convert("L"))
        ys, xs = np.where(img < 128)
        w, h = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        self.assertAlmostEqual(w / h, 3.0, delta=0.05)                    # 600:200 preservado
        self.assertEqual(h, 206)                                        # sem corte
        self.assertEqual(int(img[0, 0]), 255)                           # fundo branco
        self.assertTrue((self.tmp / "machine/print_templates/header.anterior.bmp").exists())
        png = self.tmp / "logo.png"
        art.save(png)
        with self.assertRaises(ValidationError):
            self.store.install("header", png, convert=True)
        self.store.restore_original("header")
        self.assertEqual(int(np.asarray(Image.open(self.store.path("header")).convert("L")).min()), 255)

    def test_missing_or_corrupt_template_is_reported(self):          # seção 7.6
        self.store.path("footer").write_bytes(b"lixo")
        img, warning = self.store.load("footer")
        self.assertIsNone(img)
        self.assertIn("corrompido", warning)
        self.store.path("footer").unlink()
        self.assertIn("ausente", self.store.load("footer")[1])

    def test_layout_a4_a3_portrait_landscape(self):                    # critérios 15, 16, 20
        from PIL import Image
        from app.core.contracts import RenderedImage
        from app.printing.layout_engine import Compositor, LayoutSpec
        art = Image.new("RGB", (3000, 206), (255, 255, 255))
        art.paste((0, 0, 0), (0, 0, 3000, 206))                         # arte preta ocupa a faixa toda
        img = RenderedImage(pixels=np.full((100, 100), 128, np.uint8), photometric="MONOCHROME2",
                            pixel_spacing_mm=None, applied={})
        for paper in ("A4", "A3"):
            for orient in ("portrait", "landscape"):
                spec = LayoutSpec(paper=paper, orientation=orient, dpi=72, exam_info=False, page_numbers=False,
                                  header_image=True, footer_image=True, margins_mm=(10, 10, 10, 10))
                comp = Compositor(spec, header_img=art, footer_img=art)
                page = comp.compose_page(0, 1, [img]).pixels
                dark_rows = np.where((page < 20).sum(axis=1) > page.shape[1] * 0.5)[0]
                band_w_mm, band_h_mm = comp.identity_box_mm()
                self.assertAlmostEqual(band_w_mm, comp.geom.width_mm - 20, delta=0.01)
                self.assertAlmostEqual(band_w_mm / band_h_mm, 3000 / 206, delta=0.01)
                self.assertTrue(dark_rows.min() < page.shape[0] * 0.2)      # cabeçalho no topo
                self.assertTrue(dark_rows.max() > page.shape[0] * 0.8)      # rodapé embaixo
                x, y, w, h = comp.cell_rects_mm()[0]
                self.assertGreater(y, 10 + band_h_mm)                    # imagens não sobrepõem o cabeçalho
                self.assertLess(y + h, comp.geom.height_mm - 10 - band_h_mm)
        off = Compositor(LayoutSpec(dpi=72, header_image=False, footer_image=True), header_img=art, footer_img=art)
        self.assertIsNone(off.header_img)                               # ativação independente
        capped = Compositor(LayoutSpec(dpi=72, header_image=True, identity_max_height_mm=8), header_img=art)
        w, h = capped.identity_box_mm()
        self.assertAlmostEqual(h, 8.0)
        self.assertAlmostEqual(w / h, 3000 / 206, delta=0.01)

    def test_hardware_margins_and_low_resolution_warning(self):       # seção 8
        from app.core.contracts import RenderedImage
        from app.printing.layout_engine import Compositor, LayoutSpec
        spec = LayoutSpec(dpi=150, margins_mm=(2, 2, 2, 2), hardware_margins_mm=(5, 4, 6, 4), min_effective_dpi=100,
                          exam_info=False, page_numbers=False)
        comp = Compositor(spec)
        self.assertEqual(comp.margins(), (5, 4, 6, 4))
        small = RenderedImage(pixels=np.zeros((50, 50), np.uint8), photometric="MONOCHROME2", pixel_spacing_mm=None,
                              applied={})
        comp.compose_page(0, 1, [small])
        self.assertTrue(comp.warnings and "dpi efetivos" in comp.warnings[0])


@unittest.skipUnless(HAS, "numpy/Pillow/pynetdicom não instalados")
class BackupTest(TempDirTestCase):
    def test_backup_restore_roundtrip(self):                          # seção 9
        from app.bootstrap import bootstrap
        from app.database.migrations import MIGRATIONS
        from app.services import backup as bk
        ctx = bootstrap(data_dir=self.tmp / "d")
        dev = ctx.devices.create({"name": "CT", "ae_title": "CT1"}, actor="t")
        ctx.device_settings.save(dev.id, {"paper": "A3"}, actor="t")
        b = ctx.backups.create(label="manual")
        self.assertIsNone(bk.verify(b))
        ctx.device_settings.save(dev.id, {"paper": "A4"}, actor="t")
        db_file = ctx.paths.database_file
        backups_dir = ctx.paths.backups_dir
        ctx.close()
        previous = bk.restore(b, db_file, backups_dir, max_schema=MIGRATIONS[-1].version)
        self.assertTrue(previous.exists())
        ctx = bootstrap(data_dir=self.tmp / "d")
        self.assertEqual(ctx.device_settings.get(dev.id)["paper"], "A3")
        ctx.close()
        with self.assertRaisesRegex(ValidationError, "mais nova"):
            bk.restore(b, db_file, backups_dir, max_schema=1)
        junk = self.tmp / "x.db"
        junk.write_bytes(b"x" * 100)
        with self.assertRaises(ValidationError):
            bk.restore(junk, db_file, backups_dir, max_schema=99)
        self.assertNotIn("PACIENTE", json.dumps([p.name for p in backups_dir.iterdir()]))
