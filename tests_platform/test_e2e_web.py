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
        import uvicorn  # noqa: F401
        from vyonix.api.https_server import make_server
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

    def test_0_http_on_https_port_redirects(self):
        """Quem digita http:// na porta do VYONIX vai para https:// (relato da homologação de 28/10/2026)."""
        import http.client
        from playwright.sync_api import expect
        h = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h.request("GET", "/api/v1/health?x=1", headers={"Host": f"192.168.0.10:{self.port}"})
        r = h.getresponse()
        self.assertEqual((r.status, r.getheader("Location")), (301, f"https://192.168.0.10:{self.port}/api/v1/health?x=1"))
        pg = self.page()
        pg.goto(f"http://127.0.0.1:{self.port}/")
        self.assertTrue(pg.url.startswith(f"https://127.0.0.1:{self.port}/"), pg.url)
        expect(pg.get_by_label("Usuário")).to_be_visible()

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
        prof = pg.get_by_role("region", name="Perfis da instituição")            # perfis opcionais
        prof.get_by_role("button", name="Modelos de perfil").click()
        prof.get_by_role("listitem").filter(has_text="Coordenador do CDI").get_by_role("button", name="Ativar").click()
        expect(prof.get_by_text("Perfil Coordenador do CDI ativado.")).to_be_visible()
        pg.get_by_role("button", name="Novo usuário").click()
        form = pg.get_by_role("form", name="Novo usuário")
        form.get_by_label("Usuário (login)").fill("tecnico1")
        form.get_by_label("Nome completo").click()                             # sai do campo: confere o login
        expect(form.get_by_text("Este login já está em uso na plataforma")).to_be_visible()
        expect(form.get_by_label("Papel").locator("option", has_text="Coordenador do CDI")).to_have_count(1)
        form.get_by_role("button", name="Cancelar").click()

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
        type(self).license_id = amended["license_id"]
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
        with pg.expect_popup() as pop:                              # lançador: o servidor decide protocolo e escopo
            row.get_by_role("button", name="Abrir no Viewer").click()
        popup = pop.value
        popup.wait_for_url(f"**/viewer/viewer?StudyInstanceUIDs={uid(1)}")
        self.assertIsNone(popup.evaluate("window.opener"))                          # sem acesso à janela de origem
        popup.close()
        expect(row.get_by_role("status")).to_contain_text("Padrão (1 quadro)")
        row.get_by_role("button", name="Comparar…").click()
        expect(row.get_by_text("Nenhum exame anterior com imagens disponível para você.")).to_be_visible()
        pg.get_by_role("button", name="Protocolos do Viewer").click()
        vp = pg.get_by_role("form", name="Novo protocolo do Viewer")
        vp.get_by_label("Protocolo da instituição").check()
        vp.get_by_label("Modalidade do protocolo").fill("CT")
        vp.get_by_label("Layout ao abrir").select_option(label="Grade de séries")
        vp.get_by_role("button", name="Salvar protocolo").click()
        expect(pg.get_by_role("region", name="Protocolos do Viewer").get_by_role("listitem").filter(has_text="Grade de séries")).to_contain_text("CT")
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
        ret = pg.get_by_role("region", name="Retenção de estudos")             # relatório; nada é excluído
        ret.get_by_role("button", name="Ver relatório").click()
        expect(ret.get_by_text("Prazo: 20 anos")).to_be_visible()
        expect(ret.get_by_text("Nada é excluído pelo VYONIX")).to_be_visible()

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
        expect(form.get_by_text("A estação CR_SALA1 não está cadastrada no PACS")).to_be_visible()
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
        nav.get_by_role("link", name="Central de exames").click()              # ciclo do pedido ao laudo
        expect(pg.get_by_role("heading", name="Central de exames")).to_be_visible()
        expect(pg.get_by_role("row", name="Carlos Agenda Sintetico").first).to_be_visible()
        expect(pg.get_by_role("group", name="Resumo do período")).to_contain_text("Pedidos")
        self.shot(pg, "10b-central-exames")
        nav.get_by_role("link", name="Painel do técnico").click()             # painel próprio do técnico
        expect(pg.get_by_role("heading", name="Painel do técnico")).to_be_visible()
        expect(pg.get_by_role("group", name="Resumo do dia")).to_contain_text("Recusas na recepção DICOM")
        self.shot(pg, "10c-painel-tecnico")
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

    def test_6_dicom_stations(self):
        """Nós DICOM (PACS): cadastro completo, detalhes do equipamento, aparece para a recepção no
        agendamento, política de recepção, remoção auditada."""
        from playwright.sync_api import expect
        pg = self.page()
        self.login(pg, "admin", ADMIN_PW)
        nav = pg.get_by_role("navigation", name="Navegação principal")
        nav.get_by_role("link", name="Nós DICOM").click()
        expect(pg.get_by_text("Nenhum equipamento cadastrado.")).to_be_visible()
        pg.get_by_role("button", name="Cadastrar equipamento").click()
        form = pg.get_by_role("form", name="Cadastrar equipamento")
        form.get_by_label("Identificação").fill("Ultrassom sala 4 (simulador)")
        form.get_by_label("AE Title").fill("us_sala4")
        form.get_by_label("Fabricante").fill("Fabricante Fictício")
        form.get_by_label("Modelo").fill("US-100")
        form.get_by_label("Modalidade").fill("us")
        form.get_by_label("Endereço (IP ou nome)").fill("192.168.10.44")
        form.get_by_label("Porta DICOM").fill("104")
        form.get_by_label("Recebe estudos do PACS (C-MOVE, C-GET)").check()
        form.get_by_role("button", name="Salvar equipamento").click()
        expect(pg.get_by_text("Equipamento cadastrado.")).to_be_visible()
        row = pg.get_by_role("row", name="Ultrassom sala 4 (simulador)")
        expect(row.get_by_role("cell", name="192.168.10.44:104")).to_be_visible()
        expect(row.get_by_text("Sem contato ainda")).to_be_visible()
        self.shot(pg, "11-nos-dicom")
        r = self.plat_client_get("recep1", "Recepcao-2026", "/api/v1/ris/stations")
        self.assertEqual([x["ae_title"] for x in r["items"]], ["US_SALA4"])
        # detalhes: teste de conexão (endereço fictício, sem resposta) registra a falha no histórico
        row.get_by_role("button", name="Detalhes US_SALA4").click()
        sheet = pg.get_by_role("dialog", name="Equipamento US_SALA4")
        expect(sheet.get_by_text("Fabricante Fictício · US-100")).to_be_visible()
        sheet.get_by_role("button", name="Fechar").click()
        # regra de encaminhamento para o nó que recebe estudos
        fw = pg.get_by_role("region", name="Encaminhamento de estudos")
        fw.get_by_role("button", name="Nova regra").click()
        rf = pg.get_by_role("form", name="Nova regra de encaminhamento")
        rf.get_by_label("Nome da regra").fill("US para o ultrassom da sala 4")
        rf.get_by_label("Modalidade do estudo").fill("us")
        rf.get_by_role("button", name="Salvar regra").click()
        expect(fw.get_by_text("Regra de encaminhamento criada.")).to_be_visible()
        expect(fw.get_by_role("row", name="US para o ultrassom da sala 4")).to_contain_text("Ativa")
        fw.get_by_role("row", name="US para o ultrassom da sala 4").get_by_role("button", name="Remover").click()
        expect(fw.get_by_text("Nenhuma regra de encaminhamento.")).to_be_visible()
        # política de recepção: só equipamentos cadastrados
        pg.get_by_label("Só de equipamentos cadastrados (os demais ficam retidos para sua decisão; nada é apagado)").click()
        expect(pg.get_by_text("Agora só equipamentos cadastrados com “Envia imagens” são aceitos.")).to_be_visible()
        row.get_by_role("button", name="Detalhes US_SALA4").click()
        sheet.get_by_role("button", name="Remover").click()
        sheet.get_by_role("button", name="Confirmar remoção de US_SALA4").click()
        expect(pg.get_by_text("Nenhum equipamento cadastrado.")).to_be_visible()
        from vyonix.audit import service as audit
        with db.session(self.tenant) as s:
            self.assertEqual(len(audit.query(s, action="pacs.node.remove")), 1)
            from vyonix.settings import service as settings
            self.assertEqual(settings.get(s, "pacs", "reception")["store_policy"], "registered")
            settings.put(s, "pacs", "reception", {"store_policy": "any"}, actor="teste")
        # salas do RIS: cadastro e preenchimento automático no agendamento
        nav.get_by_role("link", name="Agenda").click()
        pg.get_by_role("button", name="Salas").click()
        rooms = pg.get_by_role("form", name="Nova sala")
        rooms.get_by_label("Nome da sala").fill("Sala RX 2")
        rooms.get_by_label("Modalidade da sala").fill("cr")
        rooms.get_by_label("Estação (AE Title)").fill("cr_sala2")
        rooms.get_by_label("Duração padrão (min)").fill("10")
        rooms.get_by_role("button", name="Salvar sala").click()
        expect(pg.get_by_text("Sala RX 2 — CR · CR_SALA2 · 10 min")).to_be_visible()
        pg.get_by_role("button", name="Agendar exame").click()
        form = pg.get_by_role("form", name="Agendar exame")
        form.get_by_label("Sala cadastrada preenche").fill("sala rx 2")
        expect(form.get_by_label("Modalidade")).to_have_value("CR")
        expect(form.get_by_label("AE Title da estação")).to_have_value("CR_SALA2")
        expect(form.get_by_label("Duração (min)")).to_have_value("10")

    def test_7_report_flow(self):
        """Laudos (REPORT): médico cria rascunho a partir de modelo, senha errada não libera, libera com a senha,
        registra adendo; o texto liberado não é editável."""
        import uuid
        from datetime import date
        from playwright.sync_api import expect
        from vyonix.clinical import service as clinical
        from vyonix.modules import registry
        from vyonix.report import service as rep
        amended = self.lm.amend_modules(self.lm_admin, self.license_id,
                                        {"core": {"kind": "demo", "days": 15}, "ris": {"kind": "demo", "days": 15},
                                         "pacs": {"kind": "demo", "days": 15}, "report": {"kind": "demo", "days": 15}},
                                        reason="teste do REPORT")
        with db.session(self.tenant) as s:
            self.plat.licensing.install(s, amended["document"], actor="admin")
            registry.enable(s, "report", actor="admin", license_check=self.plat.licensing.module_ok)
            p = clinical.create_patient(s, name="Helena Laudo Sintetica", birth_date=date(1980, 1, 1), sex="F",
                                        identifiers=[("DICOM", "LD-777")], actor="t")
            o = clinical.create_order(s, patient_id=p.id, actor="t")
            st = clinical.register_study(s, study_instance_uid=f"2.25.{uuid.uuid4().int}", accession=o.accession,
                                         modality="MR", study_date=date(2026, 10, 27), description="RM de joelho",
                                         actor="t")
            clinical.reconcile(s, st.id, o.id, actor="t")
            from vyonix.report import templates as tpl
            t, _ = tpl.save(s, name="RM normal", modality="MR", technique="Sequências padrão em {{paciente.nome}}.",
                            findings="", actor="t")
            tpl.publish(s, t.id, reviewed=True, actor="t")
        pg = self.page()
        self.login(pg, "admin", ADMIN_PW)
        nav = pg.get_by_role("navigation", name="Navegação principal")
        nav.get_by_role("link", name="Usuários e papéis").click()
        pg.get_by_role("button", name="Novo usuário").click()
        form = pg.get_by_role("form", name="Novo usuário")
        form.get_by_label("Nome completo").fill("Marta Médica")
        form.get_by_label("Usuário").fill("medica1")
        form.get_by_label("Senha provisória").fill("Provisoria-123")
        form.get_by_label("Papel").select_option(label="Médico")
        form.get_by_role("button", name="Criar usuário").click()
        expect(pg.get_by_role("cell", name="medica1")).to_be_visible()
        # cadastro do médico e vínculo (administrador)
        nav.get_by_role("link", name="Laudos").click()
        pg.get_by_role("button", name="Médicos").click()
        cad = pg.get_by_role("form", name="Cadastrar médico")
        cad.get_by_label("Usuário do médico").select_option(label="Marta Médica (medica1)")
        cad.get_by_label("CRM", exact=True).fill("12345")
        cad.get_by_label("UF do CRM").select_option("CE")
        cad.get_by_label("RQE").fill("6789")
        cad.get_by_label("Especialidades").fill("Radiologia e Diagnóstico por Imagem")
        cad.get_by_role("button", name="Cadastrar médico").click()
        panel = pg.get_by_role("region", name="Médicos")
        expect(panel.get_by_text("Marta Médica — CRM 12345/CE — RQE 6789")).to_be_visible()
        expect(panel.get_by_text("Sem vínculo: não pode liberar laudos.")).to_be_visible()
        panel.get_by_role("button", name="Incluir vínculo").click()
        panel.get_by_role("form", name="Vínculo de Marta Médica").get_by_role("button", name="Incluir vínculo").click()
        expect(panel.get_by_text("toda a organização: desde")).to_be_visible()
        self.shot(pg, "13-medicos")
        # fila: coordenação atribui o exame à médica
        arow = pg.get_by_role("row", name="Helena Laudo Sintetica")
        arow.get_by_role("button", name="Atribuir").click()
        af = arow.get_by_role("form", name="Atribuir exame")
        af.get_by_label("Médico").select_option(label="Marta Médica — CRM 12345/CE — RQE 6789")
        af.get_by_label("Prioridade").select_option("urgent")
        af.get_by_role("button", name="Atribuir").click()
        expect(pg.get_by_text("Exame atribuído.")).to_be_visible()
        expect(pg.get_by_role("row", name="Helena Laudo Sintetica").get_by_text("urgente")).to_be_visible()
        # identidade visual (administrador): logomarca, rodapé, nova versão e pré-visualização A4
        import io as _io
        from PIL import Image
        logo = self.tmp / "logo.png"
        buf = _io.BytesIO()
        Image.new("RGB", (240, 80), (10, 110, 120)).save(buf, "PNG")
        logo.write_bytes(buf.getvalue())
        pg.get_by_role("button", name="Identidade visual").click()
        ed = pg.get_by_role("form", name="Editar identidade visual")
        ed.get_by_label("Logomarca", exact=True).set_input_files(str(logo))
        ed.get_by_label("Texto do rodapé").fill("Clínica Imagem Teste · Rua Sintética, 1")
        ed.get_by_role("button", name="Salvar nova versão").click()
        expect(pg.get_by_text("Identidade salva como nova versão.")).to_be_visible()
        expect(ed.get_by_text("Versão 1 por admin")).to_be_visible()
        expect(ed.get_by_text("com logomarca")).to_be_visible()
        r = pg.request.get(self.base + "/api/v1/report/branding/preview")
        self.assertEqual((r.status, r.headers["content-type"]), (200, "application/pdf"))
        from pypdf import PdfReader
        self.assertIn("Clínica Imagem Teste · Rua Sintética, 1",
                      " ".join(p_.extract_text() for p_ in PdfReader(_io.BytesIO(r.body())).pages))
        self.shot(pg, "14-identidade")
        # modelo de laudo: campo desconhecido recusado, rascunho, conferência obrigatória e publicação
        pg.get_by_role("button", name="Modelos de laudo").click()
        mf = pg.get_by_role("form", name="Editar modelo")
        mf.get_by_label("Nome do modelo").fill("TC padrão")
        mf.get_by_label("Modalidade").fill("CT")
        mf.get_by_role("textbox", name="Achados", exact=True).fill("Exame de {{paciente.cpf}}.")
        mf.get_by_role("button", name="Salvar rascunho").click()
        expect(pg.get_by_text("Campos desconhecidos no modelo: paciente.cpf.")).to_be_visible()
        achados = mf.get_by_role("textbox", name="Achados", exact=True)
        achados.fill("Exame de ")
        achados.press("Control+b")                                        # formatação pela barra/atalho
        achados.press_sequentially("{{paciente.nome}}")
        achados.press("Control+b")
        achados.press_sequentially(" em {{exame.data}}.")
        expect(achados.locator("b, strong")).to_have_text("{{paciente.nome}}")
        mf.get_by_role("button", name="Salvar rascunho").click()
        expect(pg.get_by_text("Rascunho do modelo salvo.")).to_be_visible()
        pub = pg.get_by_role("group", name="Publicar modelo")
        expect(pub.get_by_role("button", name="Publicar versão 1")).to_be_disabled()
        r = pg.request.get(self.base + pub.get_by_role("link", name="Pré-visualizar A4").get_attribute("href"))
        self.assertIn("PACIENTE DE EXEMPLO",
                      " ".join(p_.extract_text() for p_ in PdfReader(_io.BytesIO(r.body())).pages))
        pub.get_by_label("Conferi o texto e a pré-visualização").check()
        pub.get_by_role("button", name="Publicar versão 1").click()
        expect(pg.get_by_text("Modelo publicado.")).to_be_visible()
        expect(pg.get_by_text("v1 publicada por admin")).to_be_visible()
        # importação DOCX: vira rascunho com o relatório de incompatibilidades
        from tests_platform.test_report_docx import make_docx
        docx_file = self.tmp / "modelo.docx"
        docx_file.write_bytes(make_docx())
        pg.get_by_role("group", name="Importar DOCX").get_by_label("Arquivo DOCX").set_input_files(str(docx_file))
        expect(pg.get_by_text("DOCX importado como rascunho.")).to_be_visible()
        expect(mf.get_by_label("Nome do modelo")).to_have_value("TC de abdome (importado)")
        imported = mf.get_by_role("textbox", name="Achados", exact=True)
        expect(imported.locator("table td").filter(has_text="Baço")).to_be_visible()   # tabela do Word preservada
        expect(imported).to_contain_text("[paciente.cpf]")
        expect(pg.get_by_role("group", name="Publicar modelo").get_by_role("button", name="Publicar versão 1")).to_be_disabled()
        pg = self.page()
        self.login(pg, "medica1", "Provisoria-123")
        pg.get_by_label("Senha atual").fill("Provisoria-123")
        pg.get_by_label("Nova senha", exact=True).fill("Medica-2026xy")
        pg.get_by_label("Repita a nova senha").fill("Medica-2026xy")
        pg.get_by_role("button", name="Salvar senha").click()
        nav = pg.get_by_role("navigation", name="Navegação principal")
        nav.get_by_role("link", name="Laudos").click()
        # imagem da assinatura: só a própria médica envia e autoriza
        sigf = self.tmp / "assinatura.jpg"
        im_ = Image.new("RGB", (420, 150), (250, 250, 248))                 # traço sintético em "papel"
        from PIL import ImageDraw as _Draw
        _Draw.Draw(im_).line([(30, 110), (140, 30), (250, 100), (390, 40)], fill=(20, 30, 100), width=6)
        buf = _io.BytesIO()
        im_.save(buf, "JPEG")
        sigf.write_bytes(buf.getvalue())
        pg.get_by_role("button", name="Minha assinatura").click()
        sp = pg.get_by_role("region", name="Minha assinatura")
        expect(sp.get_by_text("Assinatura digital ICP-Brasil (PAdES)")).to_be_visible()
        sp.get_by_label("Arquivo da assinatura").set_input_files(str(sigf))
        expect(sp.get_by_role("img", name="Pré-visualização da assinatura tratada")).to_be_visible()
        sp.get_by_label("Recorte à esquerda").fill("5")
        sp.get_by_role("button", name="Enviar para confirmação").click()
        expect(sp.get_by_text("aguarda a confirmação do médico")).to_be_visible()
        expect(sp.get_by_role("img", name="Assinatura pendente de confirmação")).to_be_visible()
        self.assertGreater(sp.get_by_role("img", name="Assinatura pendente de confirmação")
                           .evaluate("e => e.decode().then(() => e.naturalWidth)"), 100)      # imagem carregada (CSP)
        expect(sp.get_by_label("Autorizo aplicar a imagem nos laudos que eu liberar")).to_have_count(0)  # ainda pendente
        self.shot(pg, "11b-assinatura-pendente")
        cf = sp.get_by_role("form", name="Confirmar assinatura")
        cf.get_by_label("Sua senha").fill("Medica-2026xy")
        cf.get_by_role("button", name="Confirmar que é a minha assinatura").click()
        expect(sp.get_by_text("Imagem confirmada e ativa.")).to_be_visible()
        expect(sp.get_by_role("img", name="Sua assinatura ativa")).to_be_visible()
        vp = pg.viewport_size
        pg.set_viewport_size({"width": 390, "height": 844})                  # celular: painel sem rolagem lateral
        self.assertLessEqual(sp.evaluate("e => e.scrollWidth - e.clientWidth"), 0)
        self.assertLessEqual(sp.bounding_box()["width"], 390)
        self.shot(pg, "11c-assinatura-celular")
        pg.set_viewport_size(vp)
        sp.get_by_label("Autorizo aplicar a imagem nos laudos que eu liberar").click()
        expect(sp.get_by_text("Uso autorizado nos próximos laudos que você liberar.")).to_be_visible()
        expect(sp.get_by_label("Autorizo aplicar a imagem nos laudos que eu liberar")).to_be_checked()
        pg.get_by_label("Atribuídos a mim").check()
        pg.get_by_role("button", name="Filtrar").click()
        row = pg.get_by_role("row", name="Helena Laudo Sintetica")
        expect(row.get_by_role("cell", name="Sem laudo")).to_be_visible()
        expect(pg.get_by_role("row", name="Carlos Agenda Sintetico")).to_have_count(0)        # não atribuído a ela
        # frase rápida pessoal com campo editável [[...]]
        pg.get_by_role("button", name="Frases rápidas").click()
        fp = pg.get_by_role("form", name="Editar frase")
        fp.get_by_label("Título da frase").fill("Menisco")
        fp.get_by_label("Atalho").fill("menisco")
        fp.get_by_label("Categoria").fill("Joelho")
        fp.get_by_role("textbox", name="Texto da frase", exact=True).fill("Menisco medial com [[medida]] mm.")
        fp.get_by_role("button", name="Salvar frase").click()
        expect(pg.get_by_text("Frase salva.")).to_be_visible()
        expect(pg.get_by_role("list", name="Lista de frases").get_by_text("Menisco", exact=True)).to_be_visible()
        pg.get_by_role("button", name="Fechar frases").click()
        row.get_by_role("button", name="Laudar").click()
        editor = pg.get_by_role("region", name="Laudo")
        expect(editor.get_by_text("Modelo selecionado: RM normal (regra: organização + modalidade).")).to_be_visible()
        editor.get_by_label("Modelo").select_option(label="RM normal")
        editor.get_by_role("button", name="Iniciar laudo").click()
        text = editor.get_by_role("textbox", name="Texto do laudo", exact=True)
        expect(text).to_contain_text("Sequências padrão em Helena Laudo Sintetica.")
        text.fill("Técnica: sequências padrão. Achados: sem alterações significativas.")
        text.press("Enter")
        editor.get_by_role("button", name="Lista com marcadores").click()
        text.press_sequentially("Conclusão: exame normal.")
        expect(text.locator("li")).to_have_text("Conclusão: exame normal.")
        text.press("Enter")
        text.press("Enter")                                                      # sai da lista
        text.press_sequentially("/menisco")
        text.press("Space")                                                      # atalho → pede o campo
        campos = editor.get_by_role("group", name="Campos da frase")
        campos.get_by_label("medida").fill("4")
        campos.get_by_role("button", name="Inserir frase").click()
        expect(text).to_contain_text("Menisco medial com 4 mm.")
        self.shot(pg, "12a-editor-texto-rico")
        editor.get_by_role("button", name="Salvar rascunho").click()
        expect(editor.get_by_text("Rascunho salvo.")).to_be_visible()
        draft_url = editor.get_by_role("link", name="Prévia do rascunho (sem assinatura)").get_attribute("href")
        draft_pdf = PdfReader(_io.BytesIO(pg.request.get(self.base + draft_url).body()))
        self.assertIn("RASCUNHO", " ".join(p_.extract_text() for p_ in draft_pdf.pages))
        n_draft = sum(len(p_.images) for p_ in draft_pdf.pages)                        # identidade visual, sem assinatura
        expect(editor.get_by_text("A imagem da sua assinatura manuscrita será inserida")).to_be_visible()
        editor.get_by_label("Achado crítico").check()
        editor.get_by_label("Descrição do achado crítico").fill("Lesão nova — avisar solicitante")
        sign = editor.get_by_role("form", name="Liberar laudo")
        sign.get_by_label("Sua senha para liberar").fill("senha-errada")
        sign.get_by_role("button", name="Liberar laudo").click()
        expect(editor.get_by_text("Senha incorreta: o laudo não foi liberado.")).to_be_visible()
        sign.get_by_label("Sua senha para liberar").fill("Medica-2026xy")
        sign.get_by_role("button", name="Liberar laudo").click()
        expect(editor.get_by_text("Laudo liberado.")).to_be_visible()
        v1 = editor.get_by_role("article", name="Versão 1")
        expect(v1.get_by_text("Conclusão: exame normal.")).to_be_visible()
        expect(v1.get_by_text("Marta Médica — CRM 12345/CE — RQE 6789").first).to_be_visible()
        expect(v1.get_by_text("Redigido e liberado por Marta Médica")).to_be_visible()
        expect(editor.get_by_role("textbox", name="Texto do laudo", exact=True)).to_have_count(0)   # não editável
        expect(v1.locator("li")).to_have_text("Conclusão: exame normal.")                # lista preservada
        add = editor.get_by_role("form", name="Registrar adendo")
        add.get_by_label("Adendo", exact=True).fill("Adendo: correlacionar com a clínica.")
        add.get_by_label("Sua senha para o adendo").fill("Medica-2026xy")
        add.get_by_role("button", name="Registrar adendo").click()
        expect(editor.get_by_role("article", name="Versão 2")).to_be_visible()
        pdf_url = editor.get_by_role("link", name="Baixar PDF do laudo").get_attribute("href")
        laudo_pdf = PdfReader(_io.BytesIO(pg.request.get(self.base + pdf_url).body()))
        self.assertGreaterEqual(sum(len(p_.images) for p_ in laudo_pdf.pages), 2)     # logomarca + assinatura
        self.assertGreater(sum(len(p_.images) for p_ in laudo_pdf.pages), n_draft)    # assinatura só no liberado
        self.shot(pg, "12-laudo-liberado")
        editor.get_by_role("button", name="Fechar").click()
        crit = pg.get_by_role("region", name="Achados críticos a comunicar")
        expect(crit.get_by_text("Lesão nova — avisar solicitante")).to_be_visible()
        crit.get_by_role("button", name="Registrar comunicação").click()
        cf = crit.get_by_role("form", name="Registrar comunicação do achado crítico")
        cf.get_by_label("Comunicado a").fill("Dr. Plantonista")
        cf.get_by_role("button", name="Confirmar").click()
        expect(pg.get_by_text("Comunicação do achado crítico registrada.")).to_be_visible()
        nav.get_by_role("link", name="Início").click()
        pend = pg.get_by_role("group", name="Pendências")
        expect(pend.get_by_role("link", name="Achados críticos a comunicar 0")).to_be_visible()
        expect(pend.get_by_role("link", name="Estudos sem laudo")).to_be_visible()
        nav.get_by_role("link", name="Pacientes").click()
        pg.get_by_label("Buscar paciente").fill("Helena")
        pg.get_by_role("button", name="Buscar").click()
        pg.get_by_role("button", name="Helena Laudo Sintetica").click()
        ficha = pg.get_by_role("article", name="Paciente Helena Laudo Sintetica")
        expect(ficha.get_by_text("laudo liberado")).to_be_visible()
        href = ficha.get_by_role("link", name="PDF do laudo").get_attribute("href")
        self.assertRegex(href, r"^/api/v1/report/reports/[0-9a-f-]{36}/pdf$")
        with db.session(self.tenant) as s:
            from vyonix.report.models import Report
            r = s.query(Report).filter(Report.study_id == st.id).one()
            self.assertEqual((r.status, r.version), ("final", 2))
            self.assertTrue(rep.verify(s, r.id)["valid"])

    def test_8_reconcile_flow(self):
        """Conciliação: estudo sem pedido conciliado pelo número de acesso, conferindo o paciente."""
        import uuid
        from datetime import date
        from playwright.sync_api import expect
        from vyonix.clinical import service as clinical
        from vyonix.clinical.models import Study
        with db.session(self.tenant) as s:
            p = clinical.create_patient(s, name="Otavio Conciliacao Sintetico", birth_date=date(1990, 2, 3), sex="M",
                                        identifiers=[("DICOM", "CC-321")], actor="t")
            o = clinical.create_order(s, patient_id=p.id, actor="t")
            st = clinical.register_study(s, study_instance_uid=f"2.25.{uuid.uuid4().int}", modality="US",
                                         study_date=date(2026, 10, 28), description="US abdome sem pedido", actor="t")
            sid, acc = st.id, o.accession
        pg = self.page()
        self.login(pg, "admin", ADMIN_PW)
        pg.get_by_role("navigation", name="Navegação principal").get_by_role("link", name="Conciliação").click()
        row = pg.get_by_role("row", name="US abdome sem pedido")
        row.get_by_role("button", name="Conciliar").click()
        form = pg.get_by_role("form", name="Buscar pedido")
        form.get_by_label("Número de acesso do pedido").fill(acc)
        form.get_by_role("button", name="Buscar pedido").click()
        expect(pg.get_by_text("Otavio Conciliacao Sintetico")).to_be_visible()
        pg.get_by_role("button", name="Confirmar conciliação").click()
        expect(pg.get_by_text("Estudo conciliado com o pedido.")).to_be_visible()
        expect(pg.get_by_role("row", name="US abdome sem pedido")).to_have_count(0)
        with db.session(self.tenant) as s:
            x = s.get(Study, sid)
            self.assertEqual((x.order_id, x.patient_id), (o.id, p.id))

    def plat_client_get(self, user, pw, path):
        import httpx
        with httpx.Client(base_url=self.base, verify=False) as c:
            r = c.post("/api/v1/auth/login", json={"username": user, "password": pw})
            r.raise_for_status()
            out = c.get(path)
            out.raise_for_status()
            return out.json()


if __name__ == "__main__":
    unittest.main()
