"""Fase 3 — decodificação, pipeline de apresentação, calibração, padrão de teste e cache."""

import unittest

try:
    import numpy as np
    import PIL  # noqa: F401
    import pydicom  # noqa: F401
    HAS_IMG = True
except ImportError:
    HAS_IMG = False

from tests.helpers import TempDirTestCase


def ds_file(path, *, photometric="MONOCHROME2", pixels=None, rows=4, cols=4, frames=1, bits=16, signed=0,
            slope=None, intercept=None, wc=None, ww=None, voi_function=None, shape=None, spp=1,
            planar=0, ts=None):
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ts or ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "OT"
    ds.Rows, ds.Columns = rows, cols
    ds.SamplesPerPixel = spp
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated = bits
    ds.BitsStored = bits if bits == 8 else 12
    ds.HighBit = ds.BitsStored - 1
    ds.PixelRepresentation = signed
    if spp == 3:
        ds.PlanarConfiguration = planar
    if frames > 1:
        ds.NumberOfFrames = frames
    for k, val in (("RescaleSlope", slope), ("RescaleIntercept", intercept), ("WindowCenter", wc),
                   ("WindowWidth", ww), ("VOILUTFunction", voi_function), ("PresentationLUTShape", shape)):
        if val is not None:
            setattr(ds, k, val)
    ds.PixelData = pixels.tobytes()
    ds.save_as(str(path), enforce_file_format=True)
    return path


@unittest.skipUnless(HAS_IMG, "numpy/Pillow/pydicom não instalados")
class PipelineTest(TempDirTestCase):
    def render(self, path, **params):
        from app.core.contracts import PresentationParams
        from app.imaging.pipeline import PresentationPipeline
        return PresentationPipeline().render(path, PresentationParams(**params))

    def test_rescale_and_file_window_match_dicom_formula(self):
        # Valores de TC: armazenado 1024 + intercept -1024 = 0 HU; janela C=40 W=400
        raw = np.array([[0, 1024, 1064, 2048]], dtype=np.uint16).repeat(4, 0)
        f = ds_file(self.tmp / "ct.dcm", pixels=raw, slope=1, intercept=-1024, wc=40, ww=400)
        out = self.render(f)
        self.assertEqual(out.pixels.dtype, np.uint8)
        self.assertEqual(out.applied["voi"], "janela do arquivo")
        # HU -1024 → preto; 0 → (0-39.5)/399+0.5 = 0.401 → 102; 40 → 128; 1024 → branco
        self.assertEqual(list(out.pixels[0]), [0, 102, 128, 255])

    def test_window_override_and_full_range(self):
        raw = np.array([[0, 100, 200, 300]], dtype=np.uint16).repeat(4, 0)
        f = ds_file(self.tmp / "a.dcm", pixels=raw)
        self.assertEqual(list(self.render(f).pixels[0]), [0, 85, 170, 255])        # faixa completa
        out = self.render(f, window_center=100, window_width=2)
        self.assertEqual(list(out.pixels[0]), [0, 255, 255, 255])

    def test_sigmoid_and_linear_exact(self):
        from app.imaging.pipeline import window
        v = np.array([0, 50, 100], dtype=np.float32)
        s = window(v, 50, 100, "SIGMOID")
        self.assertAlmostEqual(float(s[1]), 0.5, places=5)
        e = window(v, 50, 100, "LINEAR_EXACT")
        self.assertEqual([round(float(x), 3) for x in e], [0.0, 0.5, 1.0])

    def test_monochrome1_and_presentation_lut_inverse(self):
        raw = np.array([[0, 4095]], dtype=np.uint16).repeat(2, 0)
        m1 = ds_file(self.tmp / "m1.dcm", pixels=raw, rows=2, cols=2, photometric="MONOCHROME1")
        self.assertEqual(list(self.render(m1).pixels[0]), [255, 0])
        inv = ds_file(self.tmp / "inv.dcm", pixels=raw, rows=2, cols=2, shape="INVERSE")
        self.assertEqual(list(self.render(inv).pixels[0]), [255, 0])
        ident = ds_file(self.tmp / "id.dcm", pixels=raw, rows=2, cols=2, shape="IDENTITY")
        self.assertEqual(list(self.render(ident).pixels[0]), [0, 255])

    def test_explicit_adjustments_only_when_requested(self):
        raw = np.array([[0, 2048, 4095]], dtype=np.uint16).repeat(3, 0)
        f = ds_file(self.tmp / "b.dcm", pixels=raw, rows=3, cols=3)
        base = self.render(f)
        self.assertNotIn("gamma", base.applied)
        self.assertEqual(list(self.render(f, invert=True).pixels[0]), [255, 127, 0])
        self.assertGreater(int(self.render(f, brightness=0.2).pixels[0][1]), int(base.pixels[0][1]))
        self.assertGreater(int(self.render(f, gamma=2.0).pixels[0][1]), int(base.pixels[0][1]))

    def test_geometry(self):
        raw = np.arange(12, dtype=np.uint16).reshape(3, 4) * 100
        f = ds_file(self.tmp / "g.dcm", pixels=raw, rows=3, cols=4)
        self.assertEqual(self.render(f, rotate_degrees=90).pixels.shape, (4, 3))
        a = self.render(f).pixels
        self.assertTrue((self.render(f, flip_horizontal=True).pixels == a[:, ::-1]).all())
        self.assertEqual(self.render(f, crop=(1, 1, 2, 2)).pixels.shape, (2, 2))

    def test_multiframe_reads_selected_frame(self):
        raw = np.stack([np.full((4, 4), v, dtype=np.uint16) for v in (0, 1000, 4000)])
        f = ds_file(self.tmp / "mf.dcm", pixels=raw, frames=3, wc=2000, ww=4000)
        self.assertLess(int(self.render(f, frame_index=0).pixels.mean()), int(self.render(f, frame_index=2).pixels.mean()))
        from app.imaging.decoder import DecodeError
        with self.assertRaises(DecodeError):
            self.render(f, frame_index=5)

    def test_rgb(self):
        raw = np.zeros((4, 4, 3), dtype=np.uint8)
        raw[..., 0] = 255
        f = ds_file(self.tmp / "rgb.dcm", pixels=raw, photometric="RGB", spp=3, bits=8)
        out = self.render(f)
        self.assertEqual(out.photometric, "RGB")
        self.assertEqual(tuple(out.pixels[0, 0]), (255, 0, 0))

    def test_rle_compressed(self):
        from pydicom import dcmread
        from pydicom.uid import RLELossless
        raw = np.array([[0, 1000, 2000, 4000]], dtype=np.uint16).repeat(4, 0)
        f = ds_file(self.tmp / "rle.dcm", pixels=raw)
        ds = dcmread(f)
        ds.compress(RLELossless)
        ds.save_as(self.tmp / "rle2.dcm")
        self.assertEqual(list(self.render(self.tmp / "rle2.dcm").pixels[0]), [0, 64, 128, 255])

    def test_invalid_and_missing(self):
        from app.imaging.decoder import DecodeError
        bad = self.tmp / "bad.dcm"
        bad.write_bytes(b"nao e dicom" * 10)
        with self.assertRaises(DecodeError):
            self.render(bad)
        with self.assertRaises(DecodeError):
            self.render(self.tmp / "inexistente.dcm")


@unittest.skipUnless(HAS_IMG, "numpy/Pillow não instalados")
class CalibrationTest(TempDirTestCase):
    def test_lut(self):
        from app.imaging.calibration import CalibrationProfile, apply, lut
        self.assertTrue((lut(CalibrationProfile()) == np.arange(256)).all())
        inv = lut(CalibrationProfile(invert=True))
        self.assertEqual((int(inv[0]), int(inv[255])), (255, 0))
        lv = lut(CalibrationProfile(black_level=0.1, white_level=0.9))
        self.assertEqual((int(lv[0]), int(lv[255])), (26, 230))
        img = np.array([[0, 128, 255]], dtype=np.uint8)
        self.assertIs(apply(img, CalibrationProfile()), img)          # identidade não copia

    def test_validation_and_json(self):
        from app.core.errors import ValidationError
        from app.imaging.calibration import CalibrationProfile
        with self.assertRaises(ValidationError):
            CalibrationProfile(gamma=9).validate()
        with self.assertRaises(ValidationError):
            CalibrationProfile(black_level=0.3, white_level=0.6).validate().__class__(black_level=0.7).validate()
        p = CalibrationProfile(gamma=1.4, scale_percent=98.5)
        self.assertEqual(CalibrationProfile.from_json(p.to_json()), p)

    def test_test_pattern_has_true_scale_ruler(self):
        from app.imaging.calibration import test_pattern
        px = test_pattern(2000, 1500, dpi=150)
        self.assertEqual(px.shape, (1500, 2000))
        self.assertEqual(px.dtype, np.uint8)
        self.assertEqual(int(px.min()), 0)
        self.assertEqual(int(px.max()), 255)
        # A régua horizontal de 10 cm a 150 dpi tem ~591 px
        m = 2000 // 40
        row = px[1500 - m * 2]
        dark = np.where(row[:1200] < 50)[0]
        self.assertAlmostEqual(int(dark.max() - dark.min()), round(100 * 150 / 25.4), delta=3)


@unittest.skipUnless(HAS_IMG, "numpy/Pillow não instalados")
class ImagingServiceTest(TempDirTestCase):
    def test_cache_and_profiles(self):
        from app.bootstrap import bootstrap
        from app.core.contracts import PresentationParams
        from app.imaging.calibration import CalibrationProfile
        from app.printing.profiles import PrintProfile
        from tests.dicom_helpers import make_ct
        ctx = bootstrap(data_dir=self.tmp / "d")
        try:
            f = make_ct(self.tmp / "ct.dcm", rows=64, cols=64)
            conn = ctx.db.connection()
            conn.execute("INSERT INTO instances(sop_instance_uid, sop_class_uid, study_uid, series_uid,"
                         " transfer_syntax, file_path, file_sha256, file_size, source_ae, received_at, modality)"
                         " VALUES ('1.9', '1.2', '1.2', '1.2', '1.2.840.10008.1.2.1', ?, 'abc', 1, 'CT1', 't', 'CT')",
                         (str(f),))
            iid = conn.execute("SELECT id FROM instances").fetchone()[0]
            r1 = ctx.imaging.render(iid, PresentationParams(), max_side=32)
            self.assertEqual(max(r1.pixels.shape), 32)
            r2 = ctx.imaging.render(iid, PresentationParams(), max_side=32)
            self.assertTrue(r2.applied.get("cache"))
            pattern = ctx.imaging.render("pattern", PresentationParams(invert=True), max_side=400)
            self.assertEqual(max(pattern.pixels.shape), 400)
            recent = ctx.imaging.recent_instances()
            self.assertEqual(recent[0]["modality"], "CT")
            self.assertNotIn("PatientName", " ".join(map(str, recent[0].keys())))
            # Perfis
            p = ctx.profiles.save(PrintProfile(id=None, name="Laser sala 1",
                                               calibration=CalibrationProfile(gamma=1.2)), actor="t")
            ctx.profiles.bind(p.id, "modality", "CT", actor="t")
            self.assertEqual(ctx.profiles.for_scope("modality", "CT").calibration.gamma, 1.2)
            p2 = ctx.profiles.save(PrintProfile(id=p.id, name="Laser sala 1",
                                                calibration=CalibrationProfile(gamma=1.4)), actor="t")
            self.assertEqual(p2.calibration.gamma, 1.4)
            hist = ctx.changes.list(entity_type="print_profile")
            self.assertEqual(len(hist), 2)
        finally:
            ctx.close()


@unittest.skipUnless(HAS_IMG, "numpy/Pillow não instalados")
class CodecTest(TempDirTestCase):
    def test_lossless_codecs_roundtrip(self):
        import os

        from app.imaging import selftest
        results = selftest.run()
        self.assertEqual(results["RLE Lossless"], "ok")
        for name, state in results.items():
            self.assertIn(state, ("ok", "indisponível"), f"{name}: {state}")
        if os.environ.get("VYONIX_REQUIRE_CODECS") == "1":   # no pipeline Windows: todos obrigatórios
            self.assertEqual(set(results.values()), {"ok"}, results)

    def test_accepted_transfer_syntaxes_follow_decoders(self):
        from app.dicom import sop
        from app.imaging import codecs
        accepted = sop.accepted_transfer_syntaxes()
        self.assertEqual(accepted[:4], sop.UNCOMPRESSED)
        self.assertIn(sop.RLE_LOSSLESS, accepted)
        self.assertNotIn(sop.JPEG_LOSSLESS, accepted)         # sem decodificador por padrão
        self.assertNotIn(sop.JPEG_EXTENDED, accepted)
        for ts in accepted:
            self.assertTrue(ts in sop.UNCOMPRESSED or ts in codecs.decodable_compressed())
