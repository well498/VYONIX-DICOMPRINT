"""Assinatura manuscrita digitalizada no cadastro do médico: tratamento da imagem, ciclo pendente → confirmada →
substituída/excluída, delegação expressa a administrador, isolamento entre médicos e entre clínicas, inserção só no
documento do próprio médico liberado, bloqueio em rascunho, bloco configurável no modelo, liberação em lote,
auditoria e o ponto de integração PAdES (não disponível). Imagens **sintéticas** (traços gerados), nenhum dado real."""

from __future__ import annotations

import io
import os
import unittest
import uuid

from tests_platform.support import new_org, require_db
from tests_platform.test_pacs import ApiBase
from tests_platform.test_report import make_physician, make_study
from tests_platform.test_report_branding import pdf_text

KEY = os.urandom(32)
PW = "Senha-Teste-1234"


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs, test_report
    test_pacs.db = test_report.db = db


def scribble(fmt="PNG", size=(400, 160), bg=(255, 255, 255)) -> bytes:
    """Traço sintético sobre fundo branco (simula a foto de uma assinatura no papel)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, bg)
    w, h = size
    ImageDraw.Draw(im).line([(w * .1, h * .7), (w * .35, h * .2), (w * .55, h * .65), (w * .9, h * .3)],
                            fill=(15, 20, 90), width=5)
    buf = io.BytesIO()
    im.save(buf, fmt)
    return buf.getvalue()


def images_in_pdf(data: bytes) -> int:
    from pypdf import PdfReader
    return sum(len(p.images) for p in PdfReader(io.BytesIO(data)).pages)


def open_draft(t, uid, body="Achados: texto sintético.\nConclusão: sem alterações."):
    from vyonix.report import service as rep
    study_id, _ = make_study(t)
    with db.session(t) as s:
        r = rep.open_report(s, study_id, actor="med", actor_id=uid)
        rep.update_draft(s, r.id, body=body, actor="med")
        return r.id


class Processing(unittest.TestCase):
    def test_formats_and_rejections(self):
        from PIL import Image
        from vyonix.errors import ValidationFailed
        from vyonix.report import signature as sig
        for fmt, mt in (("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")):
            data = scribble(fmt)
            self.assertEqual(sig.sniff(data), mt)
            png, w, h = sig.process(data)
            self.assertEqual(Image.open(io.BytesIO(png)).format, "PNG")
            self.assertEqual((w, h), (400, 160))
        bad = [b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"GIF89a" + b"\0" * 50, b"", scribble()[:60],
               b"%PDF-1.4 ...", b"\x89PNG\r\n\x1a\n" + b"lixo" * 20, b"\xff\xd8\xff" + os.urandom(6 * 1024 * 1024)]
        for data in bad:
            with self.assertRaises(ValidationFailed):
                sig.process(data)
        for kw in ({"crop": (0.5, 0, 0.4, 1)}, {"crop": (0, 0, 1.2, 1)}, {"brightness": 9}, {"contrast": 0},
                   {"crop": (0, 0, 0.01, 0.01)}):
            with self.assertRaises(ValidationFailed):
                sig.process(scribble(), **kw)

    def test_crop_brightness_contrast_background(self):
        from PIL import Image
        from vyonix.report import signature as sig
        png, w, h = sig.process(scribble(), crop=(0.1, 0.1, 0.9, 0.9))
        self.assertEqual((w, h), (320, 128))
        dark, _, _ = sig.process(scribble(), brightness=0.5)
        self.assertLess(Image.open(io.BytesIO(dark)).convert("L").getpixel((2, 2)), 200)   # fundo escurecido
        plain = Image.open(io.BytesIO(sig.process(scribble())[0]))
        clear = Image.open(io.BytesIO(sig.process(scribble(), remove_background=True, contrast=1.4)[0]))
        self.assertEqual(plain.getpixel((2, 2))[3], 255)
        self.assertEqual(clear.getpixel((2, 2))[3], 0)                          # fundo branco transparente
        self.assertGreater(sum(1 for px in clear.getdata() if px[3] == 255), 500)  # traço preservado
        big = sig.process(scribble(size=(3000, 1000)))
        self.assertEqual(big[1], sig.MAX_OUT_W)                                  # reduzida proporcionalmente


class Lifecycle(unittest.TestCase):
    def setUp(self):
        from vyonix.auth import service as auth
        self.t = new_org(db)
        self.uid, self.pid = make_physician(self.t)
        self.uid2, self.pid2 = make_physician(self.t, name="Dr. Bruno Sintetico Outro", crm="654321")
        with db.session(self.t) as s:
            auth.ensure_default_roles(s)
            self.adm = auth.create_user(s, username="admcad", display_name="Adm Cadastro", password=PW,
                                        roles=[("administrador", None)], actor="t").id

    def test_pending_confirm_replace_delete_history(self):
        from sqlalchemy import select
        from vyonix.audit import service as audit
        from vyonix.errors import Conflict, ValidationFailed
        from vyonix.report import signature as sig
        from vyonix.report.models import Physician, SignatureImage
        with db.session(self.t) as s:
            img1 = sig.upload(s, self.uid, scribble("JPEG"), key=KEY, actor="med", remove_background=True)
            self.assertEqual((img1.status, img1.media_type), ("pending", "image/jpeg"))
            with self.assertRaises(ValidationFailed):                            # pendente não pode ser autorizada
                sig.set_consent(s, self.uid, True, actor="med")
            p = s.get(Physician, self.pid)
            p.use_signature_image = True                                         # nem forçando: pendente não é usada
            self.assertIsNone(sig.for_release(s, p))
            p.use_signature_image = False
            sig.confirm(s, self.uid, actor="med")
            sig.set_consent(s, self.uid, True, actor="med")
            self.assertEqual(sig.for_release(s, p), img1.id)
            with self.assertRaises(Conflict):
                sig.confirm(s, self.uid, actor="med")                           # nada pendente
            # substituição: a nova só vale depois de confirmada (sem troca silenciosa)
            img2 = sig.upload(s, self.uid, scribble("WEBP"), key=KEY, actor="med")
            self.assertEqual(sig.for_release(s, p), img1.id)
            sig.confirm(s, self.uid, actor="med")
            self.assertEqual(sig.for_release(s, p), img2.id)
            s.refresh(img1)
            self.assertEqual(img1.status, "replaced")
            self.assertIsNotNone(img1.ended_at)
            self.assertTrue(img1.ciphertext)                                     # bytes preservados (histórico)
            st = sig.status(s, self.uid)
            self.assertEqual([h["status"] for h in st["history"]], ["active", "replaced"])
            self.assertEqual(st["history"][0]["uploaded_by"], "med")
            # exclusão: desautoriza e apaga os bytes não usados em laudo
            sig.delete(s, self.uid, actor="med")
            self.assertFalse(s.get(Physician, self.pid).use_signature_image)
            self.assertIsNone(sig.for_release(s, p))
            s.refresh(img2)
            self.assertEqual((img2.status, img2.ciphertext), ("deleted", b""))
            acts = [e.action for e in audit.query(s, action="report.signature.*")]
            for a in ("report.signature.upload", "report.signature.confirm", "report.signature.consent",
                      "report.signature.delete"):
                self.assertIn(a, acts)
            self.assertEqual(len(list(s.execute(select(SignatureImage)).scalars())), 2)

    def test_only_owner_or_expressly_delegated_admin(self):
        from vyonix.audit import service as audit
        from vyonix.errors import Forbidden
        from vyonix.report import signature as sig
        with db.session(self.t) as s:
            with self.assertRaises(Forbidden):                                   # outro médico não envia pelo colega
                sig.upload(s, self.uid2, scribble(), key=KEY, actor="b", physician_id=self.pid)
            with self.assertRaises(Forbidden):                                   # administrador sem designação
                sig.upload(s, self.adm, scribble(), key=KEY, actor="adm", physician_id=self.pid)
            with self.assertRaises(Forbidden):                                   # administrador não é médico
                sig.confirm(s, self.adm, actor="adm")
            sig.set_delegate(s, self.uid, self.adm, actor="med")
            img = sig.upload(s, self.adm, scribble(), key=KEY, actor="adm", physician_id=self.pid)
            self.assertEqual((img.status, img.uploaded_by_id), ("pending", self.adm))
            self.assertTrue(sig.image_for(s, self.adm, physician_id=self.pid, key=KEY, actor="adm")
                            .startswith(b"\x89PNG"))
            self.assertEqual(len(audit.query(s, action="report.signature.admin_view")), 1)
            with self.assertRaises(Forbidden):                                   # outro médico não vê
                sig.image_for(s, self.uid2, physician_id=self.pid, key=KEY, actor="b")
            sig.confirm(s, self.uid, actor="med")                                # só o médico ativa
            with self.assertRaises(Exception):                                   # ativa não é visível ao admin
                sig.image_for(s, self.adm, physician_id=self.pid, key=KEY, actor="adm")
            sig.set_delegate(s, self.uid, None, actor="med")                     # revoga a designação
            with self.assertRaises(Forbidden):
                sig.upload(s, self.adm, scribble(), key=KEY, actor="adm", physician_id=self.pid)
            from vyonix.errors import ValidationFailed
            with self.assertRaises(ValidationFailed):                            # só administrador do cadastro
                sig.set_delegate(s, self.uid, self.uid2, actor="med")

    def test_document_of_own_physician_only_and_drafts_never_signed(self):
        from sqlalchemy import select
        from vyonix.audit import service as audit
        from vyonix.report import service as rep
        from vyonix.report import signature as sig
        from vyonix.report.models import ReportVersion
        with db.session(self.t) as s:
            sig.upload(s, self.uid, scribble(), key=KEY, actor="a")
            sig.confirm(s, self.uid, actor="a")
            sig.set_consent(s, self.uid, True, actor="a")
        rid = open_draft(self.t, self.uid)
        with db.session(self.t) as s:
            draft, name = rep.pdf(s, rid, draft=True, actor="a", signature_key=KEY)
            txt = pdf_text(draft)
            self.assertTrue(name.startswith("rascunho-"))
            self.assertIn("RASCUNHO", txt)
            self.assertIn("NÃO FINALIZADO", txt)
            self.assertNotIn("Liberado", txt)
            self.assertNotIn("CRM 123456", txt)
            self.assertEqual(images_in_pdf(draft), 0)                            # imagem nunca no rascunho
            with self.assertRaises(Exception):
                rep.pdf(s, rid, actor="a", signature_key=KEY)                    # sem PDF "final" de rascunho
        # o médico B libera o laudo dele: sem a imagem do médico A
        rid_b = open_draft(self.t, self.uid2)
        with db.session(self.t) as s:
            rep.finalize(s, rid_b, actor="B", actor_id=self.uid2)
            self.assertEqual(images_in_pdf(rep.pdf(s, rid_b, actor="B", signature_key=KEY)[0]), 0)
        with db.session(self.t) as s:
            rep.finalize(s, rid, actor="A", actor_id=self.uid)
            final = rep.pdf(s, rid, actor="A", signature_key=KEY)[0]
            self.assertEqual(images_in_pdf(final), 1)
            txt = pdf_text(final)
            self.assertIn("imagem da assinatura manuscrita", txt)
            self.assertIn("Não é assinatura digital", txt.replace("\n", " "))                                          # nunca alega ICP-Brasil
            self.assertNotIn("assinado digitalmente", txt.lower())
            applied = audit.query(s, action="report.signature.applied")
            self.assertEqual([(e.target_id, e.details["physician_id"]) for e in applied], [(str(rid), str(self.pid))])
            self.assertEqual(rep.get(s, rid)["versions"][0]["signature_mode"], "handwritten_image")
            self.assertEqual(rep.get(s, rid_b)["versions"][0]["signature_mode"], "password")
            # adulteração: versão de B apontando para a imagem de A não é desenhada
            img_a = s.execute(select(ReportVersion.signature_image_id).where(ReportVersion.report_id == rid)).scalar()
        from sqlalchemy import create_engine, text
        from tests_platform.support import urls
        eng = create_engine(urls().owner.replace("postgresql://", "postgresql+psycopg://", 1))
        with eng.begin() as cx:
            cx.execute(text("ALTER TABLE report.report_versions DISABLE TRIGGER USER"))
            cx.execute(text("UPDATE report.report_versions SET signature_image_id=:i WHERE report_id=:r"),
                       {"i": img_a, "r": rid_b})
            cx.execute(text("ALTER TABLE report.report_versions ENABLE TRIGGER USER"))
        eng.dispose()
        with db.session(self.t) as s:
            self.assertEqual(images_in_pdf(rep.pdf(s, rid_b, actor="B", signature_key=KEY)[0]), 0)
        # imagem excluída depois do uso: o laudo emitido continua reproduzível; novos laudos ficam sem imagem
        with db.session(self.t) as s:
            sig.delete(s, self.uid, actor="a")
        with db.session(self.t) as s:
            self.assertEqual(images_in_pdf(rep.pdf(s, rid, actor="A", signature_key=KEY)[0]), 1)
        rid2 = open_draft(self.t, self.uid)
        with db.session(self.t) as s:
            rep.finalize(s, rid2, actor="A", actor_id=self.uid)
            self.assertEqual(images_in_pdf(rep.pdf(s, rid2, actor="A", signature_key=KEY)[0]), 0)

    def test_isolation_between_clinics(self):
        from cryptography.exceptions import InvalidTag
        from sqlalchemy import select
        from vyonix.report import signature as sig
        from vyonix.report.models import SignatureImage
        with db.session(self.t) as s:
            img = sig.upload(s, self.uid, scribble(), key=KEY, actor="a")
            sig.confirm(s, self.uid, actor="a")
            iid, nonce, ct = img.id, img.nonce, img.ciphertext
        other = new_org(db)
        ouid, opid = make_physician(other, crm="111111")
        with db.session(other) as s:
            self.assertEqual(list(s.execute(select(SignatureImage)).scalars()), [])     # RLS: nada visível
            self.assertIsNone(s.get(SignatureImage, iid))
            # bytes copiados para outra organização/médico não decifram (dado associado = organização + médico)
            fake = SignatureImage(physician_id=opid, nonce=nonce, ciphertext=ct, sha256=img.sha256, width=1,
                                  height=1, active=True, status="active")
            s.add(fake)
            s.flush()
            with self.assertRaises(InvalidTag):
                sig.decrypt(s, fake.id, key=KEY)
            s.rollback()


class TemplateBlock(unittest.TestCase):
    def test_settings_and_rendering(self):
        from vyonix.errors import ValidationFailed
        from vyonix.report import pdf as render
        from vyonix.report import templates as tpl
        self.assertEqual(tpl.block_settings(None)["position"], "block")
        for bad in ({"position": "topo"}, {"align": "x"}, {"height_mm": 99}, {"cor": "azul"}):
            with self.assertRaises(ValidationFailed):
                tpl.block_settings(bad)
        brand = {"settings": {}}
        inst = {"display_name": "Clínica Exemplo"}
        full = render.preview(brand, inst, body="Texto.", block={"show_specialty": True})
        t = pdf_text(full)
        self.assertEqual(images_in_pdf(full), 1)
        for line in ("Dr(a). Exemplo", "CRM 000000/UF", "RQE 00000", "Especialidade de exemplo"):
            self.assertIn(line, t)
        bare = render.preview(brand, inst, body="Texto.", block={"show_image": False, "show_rqe": False,
                                                                 "show_crm": False})
        t = pdf_text(bare)
        self.assertEqual(images_in_pdf(bare), 0)
        self.assertNotIn("RQE 00000", t)
        self.assertNotIn("CRM 000000/UF", t.replace("Dr(a). Exemplo — CRM 000000/UF", ""))
        foot = render.preview(brand, inst, body="Texto curto.", block={"position": "footer", "align": "right",
                                                                       "height_mm": 20})
        self.assertEqual(images_in_pdf(foot), 1)
        from pypdf import PdfReader
        self.assertEqual(len(PdfReader(io.BytesIO(foot)).pages), 1)              # cabe no rodapé da mesma página
        long_ = render.preview(brand, inst, pages=2, block={"position": "footer"})
        self.assertEqual(images_in_pdf(long_), 1)                                # só uma vez, na última página
        last = PdfReader(io.BytesIO(long_)).pages[-1]
        self.assertEqual(len(last.images), 1)

    def test_template_version_block_used_in_report(self):
        from vyonix.report import service as rep
        from vyonix.report import signature as sig
        from vyonix.report import templates as tpl
        t = new_org(db)
        uid, _pid = make_physician(t)
        with db.session(t) as s:
            sig.upload(s, uid, scribble(), key=KEY, actor="a")
            sig.confirm(s, uid, actor="a")
            sig.set_consent(s, uid, True, actor="a")
            m, v = tpl.save(s, name="Sem imagem", findings="Achados: normal.", actor="a",
                            signature_block={"show_image": False, "show_rqe": False})
            tpl.publish(s, m.id, reviewed=True, actor="a")
            m2, _ = tpl.save(s, template_id=m.id, name="Sem imagem", findings="Achados: normal 2.", actor="a")
            self.assertFalse(tpl.listing(s)[0]["draft"]["signature_block"]["show_image"])   # herdado
        study_id, _ = make_study(t)
        with db.session(t) as s:
            r = rep.open_report(s, study_id, template_id=m.id, actor="a", actor_id=uid)
            rep.finalize(s, r.id, actor="a", actor_id=uid)
            data = rep.pdf(s, r.id, actor="a", signature_key=KEY)[0]
            self.assertEqual(images_in_pdf(data), 0)                             # modelo oculta a imagem
            self.assertNotIn("RQE 7788", pdf_text(data).split("Laudo")[-1].split("liberado com")[0])


class Pades(unittest.TestCase):
    def test_not_available_and_never_pretends(self):
        from vyonix.errors import Conflict
        from vyonix.report import pades
        self.assertFalse(pades.status().available)
        with self.assertRaises(Conflict) as cm:
            pades.sign(b"%PDF-1.7", physician_id=uuid.uuid4())
        self.assertEqual(cm.exception.code, "pades_not_available")
        self.assertEqual(pades.mode_of({"kind": "draft"}), "draft")
        self.assertEqual(pades.mode_of({"kind": "final", "has_signature_image": True}), "handwritten_image")
        self.assertEqual(pades.mode_of({"kind": "final"}), "password")
        self.assertEqual(len(set(pades.MODES.values())), 4)                     # rótulos distintos


class Api(ApiBase):
    def setUp(self):
        super().setUp()
        from vyonix.modules import registry
        doc = self.helper.issue("annual", modules={"core": {"kind": "contract"}, "report": {"kind": "contract"}})
        with db.session(self.t) as s:
            self.lic.install(s, doc["document"], actor="admin")
            registry.enable(s, "report", actor="admin", license_check=self.lic.module_ok)
        self.admin = self.login()
        self.meds = []
        for i, (u, crm) in enumerate((("drlote", "4040"), ("droutro", "5050"))):
            r = self.admin.post("/api/v1/users", json={"username": u, "display_name": u, "password": PW,
                                                       "roles": [{"role": "medico"}]})
            uid = r.json()["id"]
            m = self.login(u, PW)
            m.post("/api/v1/auth/password", json={"current": PW, "new": "Senha-Nova-9876!"})
            pid = self.admin.post("/api/v1/report/physicians", json={"user_id": uid, "full_name": f"Dr. {u} Sint",
                                                                     "crm": crm, "crm_uf": "PB"}).json()["id"]
            self.admin.post(f"/api/v1/report/physicians/{pid}/links", json={"valid_from": "2026-01-01"})
            self.meds.append((self.login(u, "Senha-Nova-9876!"), pid, uid))

    def test_upload_preview_confirm_and_private_access(self):
        med, pid, _ = self.meds[0]
        other, pid2, _ = self.meds[1]
        u = "/api/v1/report/physicians/me/signature"
        r = med.post(u + "/preview?crop=0.05,0.05,0.95,0.95&remove_background=true&contrast=1.3",
                     content=scribble("JPEG"))
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "image/png"))
        self.assertIn("no-store", r.headers["cache-control"])
        self.assertEqual(med.get(u).json()["history"], [])                       # pré-visualizar não grava
        self.assertEqual(med.post(u, content=b"<svg/>").status_code, 422)
        self.assertEqual(med.post(u + "?crop=a,b", content=scribble()).status_code, 422)
        r = med.post(u + "?remove_background=true", content=scribble("WEBP"))
        self.assertEqual((r.status_code, r.json()["pending"]["uploaded_by"]), (201, "drlote"))
        self.assertEqual(med.get(u + "/image?which=pending").status_code, 200)
        self.assertEqual(med.get(u + "/image").status_code, 404)                 # nada ativo ainda
        r = med.post(u + "/confirm", json={"password": "errada"})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "password_mismatch"))
        r = med.post(u + "/confirm", json={"password": "Senha-Nova-9876!"})
        self.assertEqual((r.status_code, r.json()["has_image"]), (200, True))
        self.assertEqual(med.get(u + "/image").status_code, 200)
        self.assertEqual(other.get(u + "/image").status_code, 404)               # outro médico: só a dele (nenhuma)
        self.assertEqual(self.admin.get(f"/api/v1/report/physicians/{pid}/signature/pending").status_code, 403)
        r = self.admin.post(f"/api/v1/report/physicians/{pid}/signature", content=scribble())
        self.assertEqual((r.status_code, r.json()["error"]), (403, "signature_not_delegated"))
        self.assertEqual(other.post(f"/api/v1/report/physicians/{pid}/signature", content=scribble()).status_code,
                         403)                                                    # médico não tem cadastro de médicos
        # delegação expressa
        cands = med.get(u + "/delegates").json()["items"]
        adm = next(c for c in cands if c["username"] == "admin")
        self.assertEqual(med.put(u + "/delegate", json={"user_id": adm["id"]}).status_code, 200)
        r = self.admin.post(f"/api/v1/report/physicians/{pid}/signature", content=scribble("JPEG"))
        self.assertEqual((r.status_code, r.json()["status"]), (201, "pending"))
        self.assertEqual(self.admin.get(f"/api/v1/report/physicians/{pid}/signature/pending").status_code, 200)
        self.assertEqual(self.admin.post(u + "/confirm", json={"password": "x"}).status_code, 403)
        st = med.get(u).json()
        self.assertEqual(st["pending"]["uploaded_by"], "admin")
        self.assertTrue(st["has_image"])                                         # a ativa segue até confirmar
        self.assertEqual(med.delete(u).status_code, 200)
        self.assertFalse(med.get(u).json()["has_image"])

    def test_batch_finalize(self):
        med, _pid, uid = self.meds[0]
        other, _pid2, _ = self.meds[1]
        rids = []
        for _ in range(3):
            study_id, _ = make_study(self.t)
            rid = med.post("/api/v1/report/reports", json={"study_id": str(study_id)}).json()["id"]
            med.put(f"/api/v1/report/reports/{rid}", json={"body": "Achados: sintético."})
            rids.append(rid)
        empty_sid, _ = make_study(self.t)
        empty = med.post("/api/v1/report/reports", json={"study_id": str(empty_sid)}).json()["id"]
        u = "/api/v1/report/reports/finalize-batch"
        self.assertEqual(med.post(u, json={"report_ids": rids, "password": "Senha-Nova-9876!"}).status_code, 422)
        r = med.post(u, json={"report_ids": rids, "password": "errada", "confirm": True})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(med.get(f"/api/v1/report/reports/{rids[0]}").json()["status"], "draft")
        self.assertEqual(med.post(u, json={"report_ids": [str(uuid.uuid4())] * 51, "password": "x",
                                           "confirm": True}).status_code, 422)
        r = med.post(u, json={"report_ids": rids + [empty], "password": "Senha-Nova-9876!", "confirm": True})
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual(out["released"], 3)
        self.assertEqual([x["ok"] for x in out["results"]], [True, True, True, False])
        from vyonix.audit import service as audit
        with db.session(self.t) as s:
            fin = [e for e in audit.query(s, action="report.finalize") if e.details.get("batch") == out["batch"]]
            self.assertEqual(sorted(e.target_id for e in fin), sorted(rids))     # trilha individual por laudo
            self.assertTrue(all(str(e.actor_id) == uid for e in fin))
        r = other.post(u, json={"report_ids": [empty], "password": "Senha-Nova-9876!", "confirm": True})
        self.assertEqual(r.json()["released"], 0)                                # vazio continua recusado


if __name__ == "__main__":
    unittest.main()
