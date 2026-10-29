"""Roteiro de homologação do proprietário, pela interface, no navegador (variante de homologação interna):
gestor entra → cadastra técnico e médica → cadastra a médica no módulo de laudos com vínculo → cadastra paciente
fictícia (prontuário HML-001) → o simulador envia o estudo sintético por C-STORE real → o estudo entra no PACS e
aparece sozinho na Central de Exames → técnico abre o painel de ações, comenta, anexa, marca o checklist e encaminha →
médica vê o exame na fila de laudos. Capturas de tela reais em VYONIX_E2E_SHOTS (prefixo r*).

Diferença para o Windows: aqui o motor DICOM é o dublê de teste (o C-STORE do simulador é recebido por um SCP local e
indexado pela mesma função ``pacs.ingest`` que a sincronização usa); o instalador real com o Orthanc é coberto por
``tools/ci_homolog_acceptance.py`` no pipeline deploy-windows (flavor=homologacao). Dados fictícios.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests_platform.pacs_support import MemoryBackend
from tests_platform.support import ADMIN_PW, new_org, require_db
from tests_platform.test_e2e_web import DIST, SHOTS, free_port


def setUpModule():
    global db
    from tests_platform import test_e2e_web
    test_e2e_web.setUpModule()
    db = require_db()


class Roteiro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uvicorn  # noqa: F401
        from vyonix.api.https_server import make_server
        from pynetdicom import AE, AllStoragePresentationContexts, evt
        from tests.licensing_support import Computer
        from tests_platform.test_licensing import Base
        from vyonix import build_flavor
        from vyonix.api.app import create_app
        from vyonix.cli import ensure_tls
        from vyonix.config import Config
        from vyonix.context import build
        from vyonix.modules import registry
        from vyonix.pacs import service as pacs
        cls.patch = mock.patch.object(build_flavor, "HOMOLOG", True)
        cls.patch2 = mock.patch.object(build_flavor, "FLAVOR", "homologacao")
        cls.patch.start()
        cls.patch2.start()
        cls.tmp = Path(tempfile.mkdtemp(prefix="vyx-roteiro-"))
        cls.code = f"clinica-alfa-{int(time.time())}"
        cls.t = new_org(db, cls.code)
        h = Base.__new__(Base)
        h.keys = {}
        lic = h.licensing(Computer())
        with db.session(cls.t) as s:
            for m in ("pacs", "ris", "report"):
                registry.enable(s, m, actor="Preparar_Homologacao", license_check=lic.module_ok)
        cfg = Config(data_dir=cls.tmp / "data", default_organization=cls.code)
        cfg.data_dir.mkdir(parents=True)
        plat = build(cfg, licensing=lic, db=db)
        cls.backend = MemoryBackend()
        plat.options["pacs_backend"] = cls.backend
        # "motor DICOM" de teste: recebe o C-STORE do simulador e indexa como a sincronização faria
        cls.dicom_port = free_port()

        def store(event):
            ds = event.dataset
            ds.file_meta = event.file_meta
            buf = io.BytesIO()
            ds.save_as(buf, enforce_file_format=True)
            with db.session(cls.t) as s:
                pacs.ingest(s, cls.backend, buf.getvalue(), actor="pacs-sync", via="dimse")
            return 0x0000
        ae = AE(ae_title="VYONIX_PACS")
        ae.supported_contexts = AllStoragePresentationContexts
        cls.scp = ae.start_server(("127.0.0.1", cls.dicom_port), block=False, evt_handlers=[(evt.EVT_C_STORE, store)])
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
        cls.scp.shutdown()
        cls.patch.stop()
        cls.patch2.stop()
        shutil.rmtree(cls.tmp, True)

    def page(self, **kw):
        ctx = self.browser.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
                                       viewport={"width": 1366, "height": 860}, **kw)
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

    def login(self, pg, user, pw, new=None):
        from playwright.sync_api import expect
        pg.goto(self.base + "/")
        expect(pg.get_by_label("Usuário")).to_be_visible()
        pg.get_by_label("Usuário").fill(user)
        pg.get_by_label("Senha").fill(pw)
        pg.get_by_role("button", name="Entrar").click()
        if new:
            pg.get_by_label("Senha atual").fill(pw)
            pg.get_by_label("Nova senha", exact=True).fill(new)
            pg.get_by_label("Repita a nova senha").fill(new)
            pg.get_by_role("button", name="Salvar senha").click()
        return pg.get_by_role("navigation", name="Navegação principal")

    def test_roteiro_completo(self):
        from playwright.sync_api import expect
        from vyonix import homolog
        # 1. Gestor da clínica fictícia
        pg = self.page()
        nav = self.login(pg, "admin", ADMIN_PW)
        expect(pg.get_by_role("note")).to_contain_text("HOMOLOGAÇÃO INTERNA")
        self.shot(pg, "r01-inicio-gestor")
        # 2. Usuários: técnico e médica
        nav.get_by_role("link", name="Usuários e papéis").click()
        for login, name, role in (("tecnico.alfa", "Tiago Técnico Fictício", "Técnico"),
                                  ("dra.ficticia", "Dra. Fictícia Teste", "Médico")):
            pg.get_by_role("button", name="Novo usuário").click()
            f = pg.get_by_role("form", name="Novo usuário")
            f.get_by_label("Nome completo").fill(name)
            f.get_by_label("Usuário (login)").fill(login)
            f.get_by_label("Senha provisória").fill("Provisoria-2026x")
            f.get_by_label("Papel").select_option(label=role)
            f.get_by_role("button", name="Criar usuário").click()
            expect(pg.get_by_role("cell", name=login)).to_be_visible()
        self.shot(pg, "r02-usuarios")
        # 3. Cadastro médico com vínculo
        nav.get_by_role("link", name="Laudos").click()
        pg.get_by_role("button", name="Médicos").click()
        cad = pg.get_by_role("form", name="Cadastrar médico")
        cad.get_by_label("Usuário do médico").select_option(label="Dra. Fictícia Teste (dra.ficticia)")
        cad.get_by_label("CRM", exact=True).fill("000001")
        cad.get_by_label("UF do CRM").select_option("PB")
        cad.get_by_role("button", name="Cadastrar médico").click()
        panel = pg.get_by_role("region", name="Médicos")
        panel.get_by_role("button", name="Incluir vínculo").click()
        panel.get_by_role("form", name="Vínculo de Dra. Fictícia Teste").get_by_role("button", name="Incluir vínculo").click()
        expect(panel.get_by_text("toda a organização: desde")).to_be_visible()
        self.shot(pg, "r03-medica-cadastrada")
        # 4. Paciente fictícia
        nav.get_by_role("link", name="Pacientes").click()
        pg.get_by_role("button", name="Novo paciente").click()
        f = pg.get_by_role("form", name="Novo paciente")
        f.get_by_label("Nome completo").fill("Maria Ficticia")
        f.get_by_label("Número").fill("HML-001")
        f.get_by_role("button", name="Cadastrar paciente").click()
        expect(pg.get_by_text("PRONTUARIO HML-001").first).to_be_visible()
        self.shot(pg, "r04-paciente")
        # 5. Exame simulado (C-STORE real do simulador)
        r = homolog.send(homolog.synthetic_study(patient_id="HML-001", patient_name="Maria Ficticia", size=64),
                         port=self.dicom_port)
        self.assertEqual((r["sent"], r["failed"]), (8, 0))
        from sqlalchemy import update
        from vyonix.db.base import utcnow
        from vyonix.pacs.models import PacsStudy
        from datetime import timedelta
        with db.session(self.t) as s:                       # recepção encerrada (no Windows: aguardar 1 minuto)
            s.execute(update(PacsStudy).values(last_received_at=utcnow() - timedelta(minutes=5)))
        # 6. Técnico: Central de Exames, painel de ações, comentário, anexo, checklist, encaminhar
        tp = self.page()
        tnav = self.login(tp, "tecnico.alfa", "Provisoria-2026x", new="Tecnico-Alfa-2026!")
        tnav.get_by_role("link", name="Painel do técnico").click()
        cards = tp.get_by_role("group", name="Situação dos estudos")
        expect(cards.get_by_role("button", name="Aguardando preparação")).to_contain_text("1")
        self.shot(tp, "r05-central-exames-tecnico")
        tp.get_by_role("button", name="Preparar Maria Ficticia").click()
        sheet = tp.get_by_role("dialog", name="Preparação do estudo")
        sheet.get_by_role("button", name="Abrir imagens ▾").click()          # mesmo menu em todas as telas
        with tp.expect_popup() as pop:
            sheet.get_by_role("menuitem", name="VYONIX Viewer").click()
        pop.value.wait_for_url(f"**/viewer/viewer?StudyInstanceUIDs={r['study_instance_uid']}")
        pop.value.close()
        expect(sheet.get_by_role("menuitem", name="Abrir com Weasis")).to_have_count(0)  # menu fecha após abrir
        self.shot(tp, "r06-painel-acoes")
        sheet.get_by_role("button", name="Comentários").click()
        sheet.get_by_role("textbox", name="Comentário").fill("Paciente orientada (comentário fictício).")
        sheet.get_by_role("button", name="Enviar comentário").click()
        expect(sheet.get_by_text("Paciente orientada (comentário fictício).")).to_be_visible()
        sheet.get_by_role("button", name="‹ Voltar às ações").click()
        pdf = self.tmp / "pedido-ficticio.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%ficticio\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
        sheet.get_by_role("button", name="Anexos").click()
        sheet.get_by_label("Arquivo do anexo").set_input_files(str(pdf))
        expect(sheet.get_by_text("pedido-ficticio.pdf")).to_be_visible()
        sheet.get_by_role("button", name="‹ Voltar às ações").click()
        sheet.get_by_role("button", name="Preparação do estudo").click()
        for label in ("Identificação do paciente conferida", "Procedimento correto", "Qualidade técnica conferida"):
            sheet.get_by_label(label).click()
            expect(sheet.get_by_label(label)).to_be_checked()
        self.shot(tp, "r07-checklist")
        sheet.get_by_role("button", name="Encaminhar para laudo").click()
        expect(sheet.get_by_text("Estudo encaminhado à fila de laudos.")).to_be_visible()
        sheet.get_by_role("button", name="Fechar").click()
        expect(cards.get_by_role("button", name="Prontos para laudo")).to_contain_text("1")
        self.shot(tp, "r08-encaminhado")
        # 7. Médica: exame na fila de laudos
        mp = self.page()
        mnav = self.login(mp, "dra.ficticia", "Provisoria-2026x", new="Medica-Ficticia-2026!")
        mnav.get_by_role("link", name="Laudos").click()
        expect(mp.get_by_role("row", name="Maria Ficticia")).to_be_visible()
        self.shot(mp, "r09-fila-de-laudos-medica")
        # 8. Laudo liberado (pelo serviço, como a API faz após conferir a senha) e Minha produção da médica
        from sqlalchemy import select
        from vyonix.auth.models import User
        from vyonix.clinical.models import Study
        from vyonix.report import service as rep
        with db.session(self.t) as s:
            uid_med = s.execute(select(User.id).where(User.username == "dra.ficticia")).scalar()
            sid = s.execute(select(Study.id).where(Study.study_instance_uid == r["study_instance_uid"])).scalar()
            rp = rep.open_report(s, sid, actor="dra.ficticia", actor_id=uid_med)
            rp.body = "Achados: estudo sintético de homologação.\nConclusão: teste, sem valor diagnóstico."
            s.flush()
            rep.finalize(s, rp.id, actor="dra.ficticia", actor_id=uid_med)
        mnav.get_by_role("link", name="Minha produção").click()
        resumo = mp.get_by_role("group", name="Resumo da produção")
        expect(resumo.get_by_text("Laudos liberados")).to_be_visible()
        expect(mp.get_by_role("region", name="Por modalidade")).to_contain_text("CT")
        self.shot(mp, "r10-minha-producao")


if __name__ == "__main__":
    unittest.main()
