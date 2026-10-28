"""TELELAUDO T2 — identidade visual: versões imutáveis, herança unidade ← organização campo a campo, imagens
validadas pelo conteúdo, isolamento entre organizações, identidade registrada na liberação e reemissão idêntica.
PostgreSQL real; imagens sintéticas geradas no teste."""

from __future__ import annotations

import io
import unittest

from tests_platform.support import new_org, require_db
from tests_platform.test_report import make_physician, make_study


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs, test_report
    test_pacs.db = test_report.db = db


def png(w=120, h=40, color=(18, 49, 63)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    return " ".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


class Branding(unittest.TestCase):
    def setUp(self):
        from vyonix.report import branding
        self.br = branding
        self.t = new_org(db)

    def test_versions_inheritance_and_validation(self):
        from vyonix.errors import NotFound, ValidationFailed
        from vyonix.tenancy.models import Site
        with db.session(self.t) as s:
            site = Site(name="Unidade Centro")
            s.add(site)
            s.flush()
            sid = site.id
            logo = self.br.store_asset(s, "logo", png(), actor="adm")
            self.assertEqual((logo.media_type, logo.width, logo.height), ("image/png", 120, 40))
            for bad in (b"%PDF-1.7 ...", b"<svg onload=alert(1)>", b"\\x89PNG\\r\\n\\x1a\\n" + b"x" * 20, b""):
                with self.assertRaises(ValidationFailed):
                    self.br.store_asset(s, "logo", bad, actor="adm")
            with self.assertRaises(ValidationFailed):
                self.br.save(s, site_id=None, settings={"accent_color": "red"}, actor="adm")
            with self.assertRaises(ValidationFailed):
                self.br.save(s, site_id=None, settings={"margin_top_mm": 200}, actor="adm")
            with self.assertRaises(ValidationFailed):
                self.br.save(s, site_id=None, settings={"script": "x"}, actor="adm")
            v1 = self.br.save(s, site_id=None, settings={"accent_color": "#aa0000", "footer_text": "Rodapé da org"},
                              logo_asset_id=logo.id, actor="adm")
            v2 = self.br.save(s, site_id=None, settings={"accent_color": "#00aa00", "footer_text": "Rodapé da org"},
                              actor="adm")
            self.assertEqual((v1.version, v2.version, v2.logo_asset_id), (1, 2, logo.id))   # imagem mantida
            self.br.save(s, site_id=sid, settings={"footer_text": "Rodapé da unidade"}, actor="adm")
            e = self.br.effective(s, sid)
            self.assertEqual((e["settings"]["accent_color"], e["settings"]["footer_text"]), ("#00AA00",
                                                                                              "Rodapé da unidade"))
            self.assertEqual((e["origin"]["accent_color"], e["origin"]["footer_text"], e["origin"]["logo"]),
                             ("organização", "unidade", "organização"))
            self.assertEqual(self.br.effective(s, sid, org_version=1)["settings"]["accent_color"], "#AA0000")
            self.assertEqual(self.br.effective(s, None)["settings"]["footer_text"], "Rodapé da org")
        other = new_org(db)
        with db.session(other) as s:                                       # outra organização: nada visível
            e = self.br.effective(s, None)
            self.assertEqual((e["logo"], e["org_version"], e["settings"]["accent_color"]), (None, None, "#12313F"))
            with self.assertRaises(NotFound):
                self.br.save(s, site_id=None, settings={}, logo_asset_id=logo.id, actor="x")
            with self.assertRaises(NotFound):
                self.br.save(s, site_id=sid, settings={}, actor="x")

    def test_versions_and_assets_immutable_for_application(self):
        from sqlalchemy import text
        from sqlalchemy.exc import ProgrammingError
        with db.session(self.t) as s:
            self.br.save(s, site_id=None, settings={"header_text": "A"}, actor="adm")
        for sql in ("UPDATE report.branding_versions SET settings = '{}'", "DELETE FROM report.assets"):
            with self.assertRaises(ProgrammingError):
                with db.session(self.t) as s:
                    s.execute(text(sql))

    def test_released_report_keeps_branding_version(self):
        from vyonix.report import service as rep
        uid, _ = make_physician(self.t)
        study_id, _ = make_study(self.t)
        with db.session(self.t) as s:
            logo = self.br.store_asset(s, "logo", png(), actor="adm")
            lh = self.br.store_asset(s, "letterhead", png(595, 842, (250, 250, 245)), actor="adm")
            self.br.save(s, site_id=None, settings={"footer_text": "Clinica Versao Um", "font": "Serif"},
                         logo_asset_id=logo.id, letterhead_asset_id=lh.id, actor="adm")
            r = rep.open_report(s, study_id, actor="med")
            rep.update_draft(s, r.id, body="Texto do laudo de teste.", actor="med")
            rep.finalize(s, r.id, actor="med", actor_id=uid)
            self.assertEqual((r.branding_org_version, r.branding_site_version), (1, None))
            first, _ = rep.pdf(s, r.id, actor="med")
            self.br.save(s, site_id=None, settings={"footer_text": "Clinica Versao Dois"}, actor="adm")
            again, _ = rep.pdf(s, r.id, actor="med")
        t1, t2 = pdf_text(first), pdf_text(again)
        self.assertIn("Clinica Versao Um", t1)
        self.assertIn("Página 1 de 1", t1)
        self.assertNotIn("Versao Dois", t2)                                # reemissão usa a versão da liberação
        self.assertEqual(t1, t2)


if __name__ == "__main__":
    unittest.main()
