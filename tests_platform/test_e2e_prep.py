"""Ponta a ponta no navegador — Central de Exames / Painel do Técnico: o técnico vê o estudo recebido na fila de
preparação, abre o painel de ações (no celular, painel inferior), comenta, anexa foto de documento, marca o
checklist, encaminha para laudo; barra lateral recolhida/oculta e menu temporário no celular.
Chromium, API real em HTTPS (instalação local), PostgreSQL real, motor dublê; dados sintéticos."""

from __future__ import annotations

import io
import shutil
import tempfile
import threading
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

from tests_platform.pacs_support import MemoryBackend, make_dicom, uid
from tests_platform.support import ADMIN_PW, new_org, require_db
from tests_platform.test_e2e_web import DIST, SHOTS, free_port


def setUpModule():
    global db
    from tests_platform import test_e2e_web
    test_e2e_web.setUpModule()
    db = require_db()


class PrepE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uvicorn  # noqa: F401
        from vyonix.api.https_server import make_server
        from sqlalchemy import update
        from tests.licensing_support import Computer, make_manager
        from tests_platform.test_licensing import Base
        from vyonix.api.app import create_app
        from vyonix.auth import service as auth
        from vyonix.cli import ensure_tls
        from vyonix.clinical import service as clinical
        from vyonix.config import Config
        from vyonix.context import build
        from vyonix.db.base import utcnow
        from vyonix.modules import registry
        from vyonix.pacs import service as pacs
        from vyonix.pacs.models import PacsStudy
        cls.tmp = Path(tempfile.mkdtemp(prefix="vyx-e2e-prep-"))
        pc = Computer()
        cls.lm, admin, keys, cid = make_manager(cls.tmp / "lm", clock=lambda: pc.clock.wall)
        h = Base.__new__(Base)
        h.keys, h.lm, h.admin, h.cid = keys, cls.lm, admin, cid
        lic = h.licensing(pc)
        h.lic = lic
        cls.code = f"e2e-prep-{int(time.time())}"
        cls.t = new_org(db, cls.code)
        doc = h.issue("annual", modules={"core": {"kind": "contract"}, "pacs": {"kind": "contract"},
                                         "ris": {"kind": "contract"}, "report": {"kind": "contract"}})
        b = MemoryBackend()
        with db.session(cls.t) as s:
            lic.install(s, doc["document"], actor="admin")
            for m in ("pacs", "ris", "report"):
                registry.enable(s, m, actor="admin", license_check=lic.module_ok)
            auth.create_user(s, username="tecprep", display_name="Tânia Técnica", password="Tecnica-2026xy",
                             roles=[("tecnico", None)], must_change=False, actor="t")
            for i in (1, 2):
                pacs.ingest(s, b, make_dicom(study=uid(55), series=uid(55, 1), sop=uid(55, 1, i), instance_number=i,
                                             patient_id="E2EPREP", station="TC_SALA_9"), actor="pacs-sync", via="dimse")
            p = clinical.create_patient(s, name="Paciente Navegador Sintetico", identifiers=[("DICOM", "E2EPREP")],
                                        actor="t")
            st = clinical.register_study(s, study_instance_uid=uid(55), modality="CT", description="TC de crânio",
                                         study_date=date(2026, 10, 28), actor="t")
            st.patient_id = p.id
            s.execute(update(PacsStudy).values(last_received_at=utcnow() - timedelta(minutes=10)))
        cfg = Config(data_dir=cls.tmp / "data", default_organization=cls.code)
        cfg.data_dir.mkdir(parents=True)
        plat = build(cfg, licensing=lic, db=db)
        plat.options["pacs_backend"] = b
        cert, key = ensure_tls(cfg)
        cls.port = free_port()
        cls.server = make_server(create_app(plat, web_dist=DIST), host="127.0.0.1", port=cls.port,
                                 certfile=cert, keyfile=key, log_level="warning")
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.1)
        cls.base = f"https://127.0.0.1:{cls.port}"
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.should_exit = True
        cls.thread.join(10)
        cls.lm.close()
        shutil.rmtree(cls.tmp, True)

    def page(self, **kw):
        ctx = self.browser.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo", **kw)
        self.addCleanup(ctx.close)
        pg = ctx.new_page()
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, [], "erros de JavaScript na página"))
        return pg

    def shot(self, pg, name):
        if SHOTS:
            SHOTS.mkdir(parents=True, exist_ok=True)
            pg.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)

    def login(self, pg):
        from playwright.sync_api import expect
        pg.goto(self.base + "/")
        expect(pg.get_by_label("Usuário")).to_be_visible()
        pg.get_by_label("Usuário").fill("tecprep")
        pg.get_by_label("Senha").fill("Tecnica-2026xy")
        pg.get_by_role("button", name="Entrar").click()

    def test_1_technician_prepares_on_phone(self):
        from playwright.sync_api import expect
        from PIL import Image
        pg = self.page(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
        self.login(pg)
        pg.get_by_role("button", name="Menu").click()                     # menu temporário no celular
        nav = pg.get_by_role("navigation", name="Navegação principal")
        nav.get_by_role("link", name="Painel do técnico").click()
        expect(nav).not_to_be_in_viewport()                                  # fecha ao escolher
        cards = pg.get_by_role("group", name="Situação dos estudos")
        expect(cards.get_by_role("button", name="Aguardando preparação")).to_contain_text("1")
        pg.get_by_role("button", name="Preparar Paciente Navegador Sintetico").click()
        sheet = pg.get_by_role("dialog", name="Preparação do estudo")
        expect(sheet.get_by_role("heading", name="Paciente Navegador Sintetico")).to_be_visible()
        expect(sheet.get_by_text("CT · TC de crânio")).to_be_visible()
        wide = pg.evaluate("""() => [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > 392)
            .slice(0, 8).map(e => e.tagName + '.' + e.className + ' ' + Math.round(e.getBoundingClientRect().right))""")
        self.assertEqual(pg.evaluate("document.documentElement.scrollWidth"), 390, wide)   # sem rolagem lateral
        self.assertLessEqual(sheet.bounding_box()["width"], 390)
        self.shot(pg, "p1-painel-acoes-celular")
        # comentário
        sheet.get_by_role("button", name="Comentários").click()
        sheet.get_by_role("textbox", name="Comentário").fill("Paciente com marcapasso (sintético).")
        sheet.get_by_role("button", name="Enviar comentário").click()
        expect(sheet.get_by_text("Paciente com marcapasso (sintético).")).to_be_visible()
        sheet.get_by_role("button", name="‹ Voltar às ações").click()
        # foto do documento (no celular, o campo abre a câmera)
        photo = self.tmp_photo()
        sheet.get_by_role("button", name="Fotografar documento").click()
        inp = sheet.get_by_label("Foto do documento")
        self.assertEqual(inp.get_attribute("capture"), "environment")
        inp.set_input_files(str(photo))
        expect(sheet.get_by_text("Foto anexada.")).to_be_visible()
        expect(sheet.get_by_role("button", name="Anexos")).to_contain_text("1")
        # checklist e encaminhamento
        sheet.get_by_role("button", name="Preparação do estudo").click()
        enc = sheet.get_by_role("button", name="Encaminhar para laudo")
        expect(enc).to_be_disabled()
        for label in ("Identificação do paciente conferida", "Procedimento correto", "Qualidade técnica conferida"):
            sheet.get_by_label(label).click()                              # caixa controlada: confirmação do servidor
            expect(sheet.get_by_label(label)).to_be_checked()
        expect(enc).to_be_enabled()
        self.shot(pg, "p2-checklist-celular")
        enc.click()
        expect(sheet.get_by_text("Estudo encaminhado à fila de laudos.")).to_be_visible()
        expect(sheet.get_by_text("Pronto para laudo")).to_be_visible()
        sheet.get_by_role("button", name="Fechar").click()
        expect(cards.get_by_role("button", name="Prontos para laudo")).to_contain_text("1")

    def tmp_photo(self):
        from PIL import Image
        p = Path(self.tmp) / "doc.jpg"
        buf = io.BytesIO()
        Image.new("RGB", (120, 160), (240, 240, 235)).save(buf, "JPEG")
        p.write_bytes(buf.getvalue())
        return p

    def test_2_sidebar_states_on_desktop(self):
        from playwright.sync_api import expect
        pg = self.page(viewport={"width": 1366, "height": 800})
        self.login(pg)
        nav = pg.get_by_role("navigation", name="Navegação principal")
        expect(nav.get_by_text("Painel do técnico")).to_be_visible()
        modes = nav.get_by_role("group", name="Barra lateral")
        modes.get_by_role("button", name="Recolher").click()
        expect(nav.get_by_text("Painel do técnico")).to_be_hidden()
        self.assertLess(nav.bounding_box()["width"], 90)
        modes.get_by_role("button", name="Ocultar").click()
        expect(nav).to_be_hidden()
        pg.reload()                                                           # preferência lembrada
        expect(pg.get_by_role("button", name="Mostrar menu")).to_be_visible()
        pg.get_by_role("button", name="Mostrar menu").click()
        expect(nav.get_by_text("Painel do técnico")).to_be_visible()
        # o técnico não vê menus de outros perfis
        for other in ("Usuários e papéis", "Laudos", "Administração VYONIX", "Configurações"):
            expect(nav.get_by_role("link", name=other)).to_have_count(0)


if __name__ == "__main__":
    unittest.main()
