"""Ponta a ponta no navegador, servidor em nuvem (várias instituições): a tela de acesso tem só usuário e senha; o
administrador geral VYONIX cadastra a Clínica Alfa pelo assistente; a gestora da Alfa entra só com usuário e senha,
troca a senha provisória e não vê a Administração VYONIX; a VYONIX desativa e o acesso da Alfa é bloqueado.
Chromium (Playwright), API real em HTTPS, PostgreSQL real; dados fictícios."""

from __future__ import annotations

import secrets
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tests_platform.support import ADMIN_PW, require_db
from tests_platform.test_e2e_web import DIST, SHOTS, free_port


def setUpModule():
    global db
    from tests_platform import test_e2e_web
    test_e2e_web.setUpModule()
    db = require_db()


class CloudE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uvicorn  # noqa: F401
        from vyonix.api.https_server import make_server
        from tests.licensing_support import Computer
        from tests_platform.test_licensing import Base
        from vyonix.api.app import create_app
        from vyonix.cli import ensure_tls
        from vyonix.config import Config
        from vyonix.context import build
        from vyonix.tenancy import platform_admin
        cls.tmp = Path(tempfile.mkdtemp(prefix="vyx-e2e-cloud-"))
        cls.sfx = secrets.token_hex(3)
        cls.op_login = f"geral.{cls.sfx}"
        platform_admin.create_operator(db, code=f"vyonix-{cls.sfx}", name="VYONIX", admin_username=cls.op_login,
                                       admin_password=ADMIN_PW)
        h = Base.__new__(Base)
        h.keys = {}
        cfg = Config(data_dir=cls.tmp / "data", mode="cloud")
        cfg.data_dir.mkdir(parents=True)
        plat = build(cfg, licensing=h.licensing(Computer()), db=db)
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
        from playwright.sync_api import expect
        pg.goto(self.base + "/")
        expect(pg.get_by_label("Usuário")).to_be_visible()
        self.assertEqual(pg.locator("form input").count(), 2)              # só usuário e senha
        pg.get_by_label("Usuário").fill(user)
        pg.get_by_label("Senha").fill(pw)
        pg.get_by_role("button", name="Entrar").click()

    def test_operator_registers_institution_and_institution_logs_in(self):
        from playwright.sync_api import expect
        pg = self.page()
        self.login(pg, self.op_login, ADMIN_PW)
        nav = pg.get_by_role("navigation", name="Navegação principal")
        nav.get_by_role("link", name="Administração VYONIX").click()
        expect(pg.get_by_role("heading", name="Administração VYONIX")).to_be_visible()
        pg.get_by_role("button", name="Nova instituição").click()
        f = pg.get_by_role("form", name="Nova instituição")
        f.get_by_label("Nome", exact=True).fill("Clínica Alfa")
        f.get_by_label("CNPJ").fill("11.222.333/0001-81")
        f.get_by_label("Código interno").fill(f"alfa-{self.sfx}")
        f.get_by_label("Unidades").fill("Unidade Centro\nUnidade Norte")
        f.get_by_label("PACS e Viewer").check()
        f.get_by_label("Telelaudos").check()
        f.get_by_label("Modelo").select_option(label="Centro de diagnóstico (CDI)")
        f.get_by_label("Nome do gestor").fill("Gestora Alfa")
        f.get_by_label("Login do gestor").fill(f"gestora.alfa.{self.sfx}")
        f.get_by_label("Senha provisória").fill("Provisoria-2026x")
        self.shot(pg, "c1-assistente-instituicao")
        f.get_by_role("button", name="Cadastrar instituição").click()
        expect(pg.get_by_text("Instituição cadastrada.")).to_be_visible()
        row = pg.get_by_role("row").filter(has_text=f"alfa-{self.sfx}")      # o banco de teste tem outras "Alfa"
        expect(row).to_contain_text("pacs, report")
        expect(row).to_contain_text("1 / 2")
        self.shot(pg, "c2-instituicoes")
        # gestora da Alfa: só usuário e senha, troca da provisória, sem Administração VYONIX
        g = self.page()
        self.login(g, f"gestora.alfa.{self.sfx}", "Provisoria-2026x")
        g.get_by_label("Senha atual").fill("Provisoria-2026x")
        g.get_by_label("Nova senha", exact=True).fill("Gestora-Alfa-2026!")
        g.get_by_label("Repita a nova senha").fill("Gestora-Alfa-2026!")
        g.get_by_role("button", name="Salvar senha").click()
        gnav = g.get_by_role("navigation", name="Navegação principal")
        expect(gnav.get_by_role("link", name="Usuários e papéis")).to_be_visible()
        expect(gnav.get_by_role("link", name="Administração VYONIX")).to_have_count(0)
        # a VYONIX desativa a Alfa: a gestora perde o acesso
        row.get_by_role("button", name="Desativar").click()
        off = row.get_by_role("form", name="Desativar Clínica Alfa")
        off.get_by_label("Motivo").fill("Teste de desativação")
        off.get_by_role("button", name="Confirmar").click()
        expect(pg.get_by_text("acessos bloqueados e sessões encerradas")).to_be_visible()
        self.login(g, f"gestora.alfa.{self.sfx}", "Gestora-Alfa-2026!")
        expect(g.get_by_text("Usuário ou senha inválidos.")).to_be_visible()


if __name__ == "__main__":
    unittest.main()
