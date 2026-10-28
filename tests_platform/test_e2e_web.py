"""Ponta a ponta: interface web real (web/dist) no navegador Chromium (Playwright), servidor HTTPS real
(uvicorn), banco PostgreSQL real e License Manager real emitindo a licença de demonstração.

Papéis exercitados: administrador, técnico e recepcionista. Pulado (com motivo) se faltar o banco de
teste, a interface compilada (``web/dist``), o uvicorn ou o Playwright.
"""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tests_platform.support import ADMIN_PW, new_org, require_db

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"
SHOTS = Path(os.environ.get("VYONIX_E2E_SHOTS", "")) if os.environ.get("VYONIX_E2E_SHOTS") else None


def setUpModule():
    global db
    db = require_db()
    if not (DIST / "index.html").exists():
        raise unittest.SkipTest("web/dist não compilado (execute 'npm run build' em web/).")
    try:
        import playwright.sync_api  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as exc:
        raise unittest.SkipTest(f"Dependência ausente para o teste de interface: {exc.name}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WebE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uvicorn
        from tests.licensing_support import Computer, make_manager
        from tests_platform.test_licensing import Base
        from vyonix.api.app import create_app
        from vyonix.cli import ensure_tls
        from vyonix.config import Config
        from vyonix.context import build
        cls.tmp = Path(tempfile.mkdtemp(prefix="vyx-e2e-"))
        cls.pc = Computer()
        cls.lm, cls.lm_admin, cls.keys, cls.cid = make_manager(cls.tmp / "lm", clock=lambda: cls.pc.clock.wall)
        helper = Base.__new__(Base)
        helper.keys = cls.keys
        cls.code = f"e2e-{int(time.time())}"
        cls.tenant = new_org(db, cls.code)
        cfg = Config(data_dir=cls.tmp / "data", default_organization=cls.code)
        cfg.data_dir.mkdir(parents=True)
        plat = build(cfg, licensing=helper.licensing(cls.pc), db=db)
        from tests_platform.pacs_support import MemoryBackend
        plat.options["pacs_backend"] = cls.pacs_backend = MemoryBackend()     # dublê de motor (rotulado)
        cls.plat = plat
        cert, key = ensure_tls(cfg)
        cls.port = free_port()
        cls.server = uvicorn.Server(uvicorn.Config(create_app(plat, web_dist=DIST), host="127.0.0.1", port=cls.port,
                                                   ssl_certfile=cert, ssl_keyfile=key, log_level="warning"))
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

    def page(self):
        ctx = self.browser.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo")
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

    def login(self, pg, user, pw):
        pg.goto(self.base + "/")
        pg.get_by_label("Usuário").fill(user)
        pg.get_by_label("Senha").fill(pw)
        pg.get_by_role("button", name="Entrar").click()

    def test_1_admin_flow(self):
        from playwright.sync_api import expect
        pg = self.page()
        self.login(pg, "admin", ADMIN_PW)
        expect(pg.get_by_role("heading", name="Olá, Administrador")).to_be_visible()
        expect(pg.get_by_text("Nenhuma licença instalada")).to_be_visible()
        cookie = [c for c in pg.context.cookies() if c["name"] == "vyx_session"][0]
        self.assertTrue(cookie["httpOnly"] and cookie["secure"])
        self.assertEqual(cookie["sameSite"], "Strict")
        self.shot(pg, "01-inicio-sem-licenca")

        # usuários: técnico e recepcionista
        nav = pg.get_by_role("navigation", name="Navegação principal")
        nav.get_by_role("link", name="Usuários e papéis").click()
        for user, name, role in (("tecnico1", "Teresa Técnica", "Técnico"), ("recep1", "Rita Recepção", "Recepcionista")):
            pg.get_by_role("button", name="Novo usuário").click()
            form = pg.get_by_role("form", name="Novo usuário")
            form.get_by_label("Nome completo").fill(name)
            form.get_by_label("Usuário").fill(user)
            form.get_by_label("Senha provisória").fill("Provisoria-123")
            form.get_by_label("Papel").select_option(label=role)
            form.get_by_role("button", name="Criar usuário").click()
            expect(pg.get_by_role("cell", name=user)).to_be_visible()
        self.shot(pg, "02-usuarios")

        # pedido de demonstração (painel comercial)
        nav.get_by_role("link", name="Contratar e demonstrar").click()
        form = pg.get_by_role("form", name="Solicitar demonstração")
        form.get_by_label("15 dias").check()
        form.get_by_label("E-mail para resposta").fill("ti@clinica.example")
        form.get_by_role("button", name="Gerar pedido").click()
        code = pg.get_by_label("Código do pedido").input_value()
        self.assertTrue(code.startswith("VYXR2-"))
        self.shot(pg, "03-pedido-demonstracao")

        # o fornecedor emite a demonstração no License Manager (real) a partir do pedido
        info = self.lm.import_request(self.lm_admin, code)
        self.assertEqual(info.data["platform"]["demo_days"], 15)
        lic = self.lm.issue(self.lm_admin, info.request_id, self.cid, ltype="annual", edition="Profissional",
                            features=[], modules={"core": {"kind": "demo", "days": 15},
                                                  "ris": {"kind": "demo", "days": 15}})
        type(self).license_id = lic["license_id"]
        nav.get_by_role("link", name="Licença e módulos").click()
        pg.get_by_label("Conteúdo do documento").fill(lic["document"])
        pg.get_by_role("button", name="Aplicar licença").click()
        expect(pg.get_by_text("Licença aplicada.")).to_be_visible()
        expect(pg.get_by_role("row", name="VYONIX Core").get_by_text("restantes")).to_be_visible()
        self.shot(pg, "04-licenca-demo")

        # configurações com histórico
        nav.get_by_role("link", name="Configurações").click()
        form = pg.get_by_role("form", name="Dados da instituição")
        form.get_by_label("Nome exibido").fill("Clínica Imagem Teste")
        form.get_by_label("Motivo da alteração").fill("cadastro inicial")
        form.get_by_role("button", name="Salvar").click()
        expect(form.get_by_text("Configuração salva.")).to_be_visible()

        # auditoria encadeada
        nav.get_by_role("link", name="Auditoria").click()
        pg.get_by_role("button", name="Verificar integridade").click()
        expect(pg.get_by_text("Cadeia íntegra")).to_be_visible()
        expect(pg.get_by_role("cell", name="license.apply")).to_be_visible()
        self.shot(pg, "05-auditoria")

    def test_2_reception_flow(self):
        from playwright.sync_api import expect
        pg = self.page()
        self.login(pg, "recep1", "Provisoria-123")
        expect(pg.get_by_role("heading", name="Defina sua senha")).to_be_visible()
        pg.get_by_label("Senha atual").fill("Provisoria-123")
        pg.get_by_label("Nova senha", exact=True).fill("Recepcao-2026")
        pg.get_by_label("Repita a nova senha").fill("Recepcao-2026")
        pg.get_by_role("button", name="Salvar senha").click()
        nav = pg.get_by_role("navigation", name="Navegação principal")
        expect(nav.get_by_role("link", name="Pacientes")).to_be_visible()
        expect(nav.get_by_role("link", name="Usuários e papéis")).to_have_count(0)
        expect(nav.get_by_role("link", name="Auditoria")).to_have_count(0)
        nav.get_by_role("link", name="Pacientes").click()
        pg.get_by_role("button", name="Novo paciente").click()
        form = pg.get_by_role("form", name="Novo paciente")
        form.get_by_label("Nome completo").fill("Joana Pereira Teste")
        form.get_by_label("Número").fill("PR-555")
        form.get_by_role("button", name="Cadastrar paciente").click()
        expect(pg.get_by_role("article", name="Paciente Joana Pereira Teste")).to_be_visible()
        pg.get_by_role("button", name="Novo pedido").click()
        expect(pg.get_by_text("Pedido criado.")).to_be_visible()
        self.shot(pg, "06-recepcao-paciente")

    def test_3_technician_flow(self):
        from playwright.sync_api import expect
        pg = self.page()
        self.login(pg, "tecnico1", "Provisoria-123")
        pg.get_by_label("Senha atual").fill("Provisoria-123")
        pg.get_by_label("Nova senha", exact=True).fill("Tecnico-2026x")
        pg.get_by_label("Repita a nova senha").fill("Tecnico-2026x")
        pg.get_by_role("button", name="Salvar senha").click()
        nav = pg.get_by_role("navigation", name="Navegação principal")
        nav.get_by_role("link", name="Pacientes").click()
        pg.get_by_label("Buscar paciente").fill("joana")
        pg.get_by_role("button", name="Buscar").click()
        pg.get_by_role("button", name="Joana Pereira Teste").click()
        expect(pg.get_by_role("heading", name="Pedidos")).to_be_visible()
        expect(pg.get_by_role("button", name="Novo paciente")).to_have_count(0)
        expect(pg.get_by_role("button", name="Novo pedido")).to_have_count(0)
        expect(nav.get_by_role("link", name="Licença e módulos")).to_be_visible()
        expect(nav.get_by_role("link", name="Configurações")).to_have_count(0)
        self.shot(pg, "07-tecnico")
        pg.get_by_role("button", name="Sair").click()
        expect(pg.get_by_role("heading", name="Entrar")).to_be_visible()

    def test_4_images_flow(self):
        """Imagens (PACS): pesquisa, pendências de qualidade e link para o Viewer. Motor: dublê de teste."""
        from playwright.sync_api import expect
        from tests_platform.pacs_support import make_dicom, uid
        from vyonix.modules import registry
        from vyonix.pacs import service as pacs
        amended = self.lm.amend_modules(self.lm_admin, self.license_id,
                                        {"core": {"kind": "demo", "days": 15}, "ris": {"kind": "demo", "days": 15},
                                         "pacs": {"kind": "demo", "days": 15}}, reason="teste do PACS")
        with db.session(self.tenant) as s:
            self.plat.licensing.install(s, amended["document"], actor="admin")
            registry.enable(s, "pacs", actor="admin", license_check=self.plat.licensing.module_ok)
            for i in (1, 2, 4):                                    # falta a imagem 3
                pacs.ingest(s, self.pacs_backend, make_dicom(sop=uid(1, 1, i), instance_number=i,
                                                             patient_name="SILVA^MARIA SINTETICA", accession="AC-77"),
                            actor="teste")
        pg = self.page()
        self.login(pg, "admin", ADMIN_PW)
        nav = pg.get_by_role("navigation", name="Navegação principal")
        nav.get_by_role("link", name="Imagens").click()
        expect(pg.get_by_role("heading", name="Imagens")).to_be_visible()
        row = pg.get_by_role("row", name="MARIA SINTETICA SILVA")
        expect(row).to_be_visible()
        expect(row.get_by_role("cell", name="CT", exact=True)).to_be_visible()
        link = row.get_by_role("link", name="Abrir no Viewer")
        self.assertEqual(link.get_attribute("href"), f"/viewer/viewer?StudyInstanceUIDs={uid(1)}")
        self.assertEqual(link.get_attribute("rel"), "noopener")
        status = pg.get_by_role("group", name="Estado do armazenamento")
        expect(status.get_by_text("Habilitado")).to_be_visible()
        expect(status.get_by_text("memoria-teste 0")).to_be_visible()              # nome e versão vindos do motor
        expect(status.get_by_text(" KB")).to_be_visible()
        row.get_by_role("button", name="Qualidade").click()
        expect(pg.get_by_text("faltam as instâncias 3")).to_be_visible()
        expect(pg.get_by_text("Estudo sem pedido conciliado.")).to_be_visible()
        self.shot(pg, "08-imagens-qualidade")
        pg.get_by_label("Só com pendência de qualidade").check()
        expect(pg.get_by_role("row", name="MARIA SINTETICA SILVA")).to_be_visible()
        expect(pg.get_by_text("Lacuna na numeração")).to_be_visible()
        pg.get_by_label("Só com pendência de qualidade").uncheck()
        pg.get_by_label("ID do paciente").fill("NINGUEM")
        pg.get_by_role("button", name="Pesquisar").click()
        expect(pg.get_by_text("Nenhum estudo com esses filtros.")).to_be_visible()
        self.shot(pg, "09-imagens-sem-resultado")

    def test_5_ris_schedule_flow(self):
        """Agenda (RIS): a recepção agenda um pedido, inicia e cancela com motivo; o técnico só consulta."""
        from datetime import date, datetime, timedelta, timezone
        today = datetime.now(timezone(timedelta(hours=-3))).date()     # dia da clínica (navegador em São Paulo)
        from playwright.sync_api import expect
        from vyonix.clinical import service as clinical
        from vyonix.modules import registry
        with db.session(self.tenant) as s:
            registry.enable(s, "ris", actor="admin", license_check=self.plat.licensing.module_ok)
            p = clinical.create_patient(s, name="Carlos Agenda Sintetico", birth_date=date(1975, 5, 6), sex="M",
                                        identifiers=[("DICOM", "AG-901")], actor="t")
            proc = clinical.save_procedure(s, code="RX-TORAX", name="RX de tórax", modality="CR", actor="t")
            acc = clinical.create_order(s, patient_id=p.id, procedure_id=proc.id, actor="t").accession
            acc2 = clinical.create_order(s, patient_id=p.id, procedure_id=proc.id, actor="t").accession
        pg = self.page()
        self.login(pg, "recep1", "Recepcao-2026")
        nav = pg.get_by_role("navigation", name="Navegação principal")
        nav.get_by_role("link", name="Agenda").click()
        expect(pg.get_by_role("heading", name="Agenda")).to_be_visible()
        expect(pg.get_by_text("Nenhum exame agendado nesse período.")).to_be_visible()
        pg.get_by_role("button", name="Agendar exame").click()
        form = pg.get_by_role("form", name="Agendar exame")
        form.get_by_label("Pedido").select_option(label=f"Carlos Agenda Sintetico — {acc} — RX de tórax")
        expect(form.get_by_label("Modalidade")).to_have_value("CR")             # vem do procedimento
        form.get_by_label("Data e hora").fill(f"{today.isoformat()}T23:30")
        form.get_by_label("AE Title da estação").fill("cr_sala1")
        form.get_by_role("button", name="Confirmar agendamento").click()
        expect(pg.get_by_text("Exame agendado.")).to_be_visible()
        row = pg.get_by_role("row", name="Carlos Agenda Sintetico")
        expect(row.get_by_role("cell", name="AG-901")).to_be_visible()
        expect(row.get_by_role("cell", name="CR_SALA1")).to_be_visible()
        expect(row.get_by_role("cell", name="23:30")).to_be_visible()
        self.shot(pg, "10-agenda")
        pg.get_by_role("button", name="Agendar exame").click()          # mesmo horário e estação: recusado
        form = pg.get_by_role("form", name="Agendar exame")
        form.get_by_label("Pedido").select_option(label=f"Carlos Agenda Sintetico — {acc2} — RX de tórax")
        form.get_by_label("Data e hora").fill(f"{today.isoformat()}T23:40")
        form.get_by_label("AE Title da estação").fill("CR_SALA1")
        form.get_by_role("button", name="Confirmar agendamento").click()
        expect(pg.get_by_text("Horário ocupado na estação CR_SALA1")).to_be_visible()
        form.get_by_role("button", name="Cancelar").click()
        row.get_by_role("button", name="Check-in").click()
        expect(row.get_by_role("cell", name="Paciente chegou")).to_be_visible()
        row.get_by_role("button", name="Iniciar").click()
        expect(row.get_by_role("cell", name="Em realização")).to_be_visible()
        row.get_by_role("button", name="Cancelar").click()
        cf = pg.get_by_role("form", name="Cancelar exame de Carlos Agenda Sintetico")
        cf.get_by_label("Motivo do cancelamento").fill("paciente não compareceu")
        cf.get_by_role("button", name="Confirmar cancelamento").click()
        expect(pg.get_by_text("Nenhum exame agendado nesse período.")).to_be_visible()
        pg.get_by_label("Incluir recebidos, concluídos e cancelados").check()
        pg.get_by_role("button", name="Filtrar").click()
        expect(pg.get_by_role("row", name="Carlos Agenda Sintetico").get_by_role("cell", name="Cancelado")).to_be_visible()
        pg = self.page()
        self.login(pg, "tecnico1", "Tecnico-2026x")
        nav = pg.get_by_role("navigation", name="Navegação principal")
        nav.get_by_role("link", name="Agenda").click()
        expect(pg.get_by_role("heading", name="Agenda")).to_be_visible()
        expect(pg.get_by_role("button", name="Agendar exame")).to_have_count(0)
        from vyonix.audit import service as audit
        with db.session(self.tenant) as s:
            self.assertEqual(len(audit.query(s, action="ris.schedule.status")), 3)

        # estudo agendado chega ao PACS (dublê de motor) → "Imagens recebidas" com link para o Viewer
        from tests_platform.pacs_support import make_dicom
        from vyonix.events.worker import process_batch
        from vyonix.pacs import service as pacs
        from vyonix.ris import service as ris
        brt = timezone(timedelta(hours=-3))
        with db.session(self.tenant) as s:
            st = ris.schedule(s, clinical.create_order(s, patient_id=p.id, procedure_id=proc.id, actor="t").id,
                              scheduled_at=datetime.now(brt).replace(hour=22, minute=0, second=0, microsecond=0),
                              station_aet="CR_SALA2", actor="t")
            study_uid = st.study_instance_uid
            pacs.ingest(s, self.pacs_backend, make_dicom(study=study_uid, series=study_uid + ".1",
                                                         sop=study_uid + ".1.1", patient_id="AG-901",
                                                         patient_name="SINTETICO^CARLOS AGENDA"), actor="teste")
        while process_batch(db, self.plat.bus):
            pass
        with db.session(self.tenant) as s:
            from vyonix.ris.models import Schedule
            self.assertEqual(s.get(Schedule, st.id).status, "received")
        pg = self.page()
        self.login(pg, "admin", ADMIN_PW)
        pg.get_by_role("navigation", name="Navegação principal").get_by_role("link", name="Agenda").click()
        expect(pg.get_by_role("row", name="CR_SALA2")).to_have_count(0)          # fora da lista de pendentes
        pg.get_by_label("Incluir recebidos, concluídos e cancelados").check()
        pg.get_by_role("button", name="Filtrar").click()
        row = pg.get_by_role("row", name="CR_SALA2")
        expect(row.get_by_text("Imagens recebidas")).to_be_visible()
        self.assertEqual(row.get_by_role("link", name="Abrir no Viewer").get_attribute("href"),
                         f"/viewer/viewer?StudyInstanceUIDs={study_uid}")


if __name__ == "__main__":
    unittest.main()
