"""TELELAUDO T5 — imagem da assinatura manuscrita: só o próprio médico envia e autoriza; cifrada no banco; nunca
devolvida pela API; aplicada no PDF só se autorizada na liberação; revogação vale para as próximas versões;
administrador não usa. Plataforma real, PostgreSQL real; imagens sintéticas."""

from __future__ import annotations

import io
import unittest

from tests_platform.support import require_db
from tests_platform.test_pacs import ApiBase
from tests_platform.test_report import make_study


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs, test_report
    test_pacs.db = test_report.db = db


def png() -> bytes:
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (300, 100), (255, 255, 255, 0))
    ImageDraw.Draw(im).line([(10, 80), (120, 20), (200, 70), (290, 30)], fill=(10, 10, 80, 255), width=4)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def images_in_pdf(data: bytes) -> int:
    from pypdf import PdfReader
    return sum(len(p.images) for p in PdfReader(io.BytesIO(data)).pages)


class Signature(ApiBase):
    def setUp(self):
        super().setUp()
        from vyonix.modules import registry
        doc = self.helper.issue("annual", modules={"core": {"kind": "contract"}, "report": {"kind": "contract"}})
        with db.session(self.t) as s:
            self.lic.install(s, doc["document"], actor="admin")
            registry.enable(s, "report", actor="admin", license_check=self.lic.module_ok)
        self.admin = self.login()
        r = self.admin.post("/api/v1/users", json={"username": "drsig", "display_name": "Dr. Sig",
                                                   "password": "Senha-Teste-1234", "roles": [{"role": "medico"}]})
        uid = r.json()["id"]
        m = self.login("drsig", "Senha-Teste-1234")
        m.post("/api/v1/auth/password", json={"current": "Senha-Teste-1234", "new": "Senha-Nova-9876!"})
        self.med = self.login("drsig", "Senha-Nova-9876!")
        pid = self.admin.post("/api/v1/report/physicians", json={"user_id": uid, "full_name": "Dr. Sig Sintetico",
                                                                 "crm": "777", "crm_uf": "RN"}).json()["id"]
        self.admin.post(f"/api/v1/report/physicians/{pid}/links", json={"valid_from": "2026-01-01"})

    def release(self, text="Laudo de teste."):
        study_id, _ = make_study(self.t)
        rid = self.med.post("/api/v1/report/reports", json={"study_id": str(study_id)}).json()["id"]
        rv = self.med.put(f"/api/v1/report/reports/{rid}", json={"body": text}).json()["row_version"]
        r = self.med.post(f"/api/v1/report/reports/{rid}/finalize", json={"password": "Senha-Nova-9876!",
                                                                          "row_version": rv})
        self.assertEqual(r.status_code, 200, r.text)
        return rid

    def test_only_physician_consent_and_encryption(self):
        from sqlalchemy import select
        from vyonix.report.models import ReportVersion, SignatureImage
        # administrador (não é médico) não envia, não consulta, não autoriza
        self.assertEqual(self.admin.post("/api/v1/report/physicians/me/signature", content=png(),
                                         headers={"Content-Type": "image/png"}).json()["error"], "physician_required")
        self.assertEqual(self.admin.get("/api/v1/report/physicians/me/signature").status_code, 403)
        # sem autorização: imagem não aparece
        r = self.med.post("/api/v1/report/physicians/me/signature/consent", json={"allow": True})
        self.assertEqual(r.status_code, 422)                                     # precisa enviar antes
        r = self.med.post("/api/v1/report/physicians/me/signature", content=png(), headers={"Content-Type": "image/png"})
        self.assertEqual((r.status_code, r.json()["has_image"], r.json()["use_signature_image"]), (201, True, False))
        rid0 = self.release()
        self.assertEqual(images_in_pdf(self.med.get(f"/api/v1/report/reports/{rid0}/pdf").content), 0)
        # com autorização: aparece no PDF e fica registrada na versão
        self.med.post("/api/v1/report/physicians/me/signature/consent", json={"allow": True})
        rid1 = self.release()
        pdf1 = self.admin.get(f"/api/v1/report/reports/{rid1}/pdf").content          # quem lê o laudo vê
        self.assertEqual(images_in_pdf(pdf1), 1)
        # revogação: vale para as próximas versões; a liberada continua como foi
        self.med.post("/api/v1/report/physicians/me/signature/consent", json={"allow": False})
        r = self.med.post(f"/api/v1/report/reports/{rid1}/addenda", json={"text": "Adendo.",
                                                                          "password": "Senha-Nova-9876!"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(images_in_pdf(self.med.get(f"/api/v1/report/reports/{rid1}/pdf").content), 1)
        with db.session(self.t) as s:
            vs = list(s.execute(select(ReportVersion).where(ReportVersion.report_id == rid1)
                                .order_by(ReportVersion.version)).scalars())
            self.assertIsNotNone(vs[0].signature_image_id)
            self.assertIsNone(vs[1].signature_image_id)
            img = s.execute(select(SignatureImage)).scalar_one()
            self.assertNotIn(b"PNG", img.ciphertext)                             # cifrada em repouso
            self.assertNotIn(b"IHDR", img.ciphertext)
        # a API nunca devolve a imagem
        st = self.med.get("/api/v1/report/physicians/me/signature").json()
        self.assertEqual(set(st), {"has_image", "use_signature_image", "uploaded_at"})
        # imagem inválida
        r = self.med.post("/api/v1/report/physicians/me/signature", content=b"<svg/>", headers={"Content-Type": "image/svg+xml"})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
