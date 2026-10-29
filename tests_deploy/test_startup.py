"""Inicialização e acesso web (correção do relato da homologação de 28/10/2026): diagnóstico de inicialização por
componente com sondas simuladas (não configurado, serviço parado, logo após ligar o Windows, banco fora do ar, porta
ocupada, API sem banco, interface ausente, acesso pelo IP, rede Pública sem regra), relatório HTML sem segredos,
comando ``abrir`` (abre o navegador só com o sistema funcionando), regra de firewall do perfil Público só para a
sub-rede local, atalho VYONIX que verifica antes de abrir. O cenário real no Windows fica no CI (deploy-windows)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vyonix_deploy import startup
from vyonix_deploy.config import DeployConfig
from vyonix_deploy.db import DeployDB
from vyonix_deploy.engine import Context
from vyonix_deploy.paths import default_paths

HEALTH = json.dumps({"status": "ok", "database": True, "version": "0.2.0", "flavor": "commercial"}).encode()


def probes(**over):
    svc = {"VyonixPostgreSQL": {"state": "Running", "delayed": False},
           "VyonixCore": {"state": "Running", "delayed": True},
           "VyonixWorker": {"state": "Running", "delayed": True}, "VyonixPacsEngine": None}
    svc.update(over.pop("services", {}))
    web = {("127.0.0.1", "/api/v1/health"): (200, HEALTH), ("127.0.0.1", "/"): (200, b"<!doctype html><html><body>"),
           ("192.168.0.50", "/api/v1/health"): (200, HEALTH)}
    web.update(over.pop("web", {}))
    base = dict(service=lambda n: svc.get(n), tcp=lambda h, p: True,
                https=lambda h, p, path: web.get((h, path)), lan_ips=lambda: ["192.168.0.50"],
                profiles=lambda: [{"alias": "Ethernet", "category": "Private"}],
                rules=lambda: [{"id": "VYONIX-core-https-8444", "enabled": "True", "profile": "Domain, Private",
                                "port": "8444"},
                               {"id": "VYONIX-core-lan-8444", "enabled": "True", "profile": "Public", "port": "8444"}],
                port_owner=lambda p: {"process": "VyonixPlatform", "pid": 10}, uptime_s=lambda: 3600.0)
    base.update(over)
    return startup.Probes(**base)


def by_id(res):
    return {c.id: c for c in res.checks}


class Checks(unittest.TestCase):
    def test_everything_ok_lists_localhost_and_lan_addresses(self):
        r = startup.run_checks(8444, probes=probes())
        self.assertEqual(r.status, "ok", startup.to_text(r))
        self.assertTrue(r.web_ok)
        self.assertEqual(r.urls, ["https://localhost:8444/", "https://192.168.0.50:8444/"])

    def test_not_configured_says_wizard_not_finished(self):
        r = startup.run_checks(8444, probes=probes(services={"VyonixPostgreSQL": None, "VyonixCore": None,
                                                             "VyonixWorker": None}, web={
            ("127.0.0.1", "/api/v1/health"): None}))
        c = by_id(r)["install"]
        self.assertEqual(c.status, "fail")
        self.assertIn("assistente", c.detail)
        self.assertIn("Assistente de instalacao", c.fix)
        self.assertFalse(r.web_ok)

    def test_stopped_service_and_shortly_after_boot(self):
        stopped = {"VyonixCore": {"state": "Stopped", "delayed": True}}
        r = startup.run_checks(8444, probes=probes(services=stopped, port_owner=lambda p: None,
                                                   web={("127.0.0.1", "/api/v1/health"): None}))
        self.assertEqual(by_id(r)["service.VyonixCore"].status, "fail")
        self.assertIn("parado", by_id(r)["service.VyonixCore"].detail)
        r = startup.run_checks(8444, probes=probes(services=stopped, port_owner=lambda p: None, uptime_s=lambda: 90.0,
                                                   web={("127.0.0.1", "/api/v1/health"): None}))
        self.assertEqual(by_id(r)["service.VyonixCore"].status, "warn")
        self.assertIn("início automático atrasado", by_id(r)["service.VyonixCore"].detail)
        self.assertTrue(startup._starting(r))                           # vale esperar

    def test_database_down_and_api_without_database(self):
        bad = json.dumps({"status": "ok", "database": False}).encode()
        r = startup.run_checks(8444, probes=probes(tcp=lambda h, p: False,
                                                   web={("127.0.0.1", "/api/v1/health"): (503, bad)}))
        self.assertEqual(by_id(r)["database"].status, "fail")
        self.assertEqual(by_id(r)["web.localhost"].status, "fail")
        self.assertIn("VyonixPostgreSQL", by_id(r)["web.localhost"].fix)
        self.assertFalse(startup._starting(r))

    def test_port_taken_by_other_program(self):
        r = startup.run_checks(8444, probes=probes(port_owner=lambda p: {"process": "httpd", "pid": 77},
                                                   web={("127.0.0.1", "/api/v1/health"): None}))
        c = by_id(r)["port"]
        self.assertEqual(c.status, "fail")
        self.assertIn("httpd", c.detail)
        self.assertIn("porta livre", c.fix)
        self.assertFalse(startup._starting(r))                          # não adianta esperar

    def test_frontend_missing_and_lan_not_answering(self):
        r = startup.run_checks(8444, probes=probes(web={("127.0.0.1", "/"): (404, b"{}"),
                                                        ("192.168.0.50", "/api/v1/health"): None}))
        self.assertEqual(by_id(r)["web.frontend"].status, "fail")
        self.assertEqual(by_id(r)["web.lan.192.168.0.50"].status, "warn")
        self.assertEqual(r.urls, ["https://localhost:8444/"])

    def test_public_network_without_lan_rule_is_flagged(self):
        r = startup.run_checks(8444, probes=probes(
            profiles=lambda: [{"alias": "Ethernet 2", "category": "Public"}],
            rules=lambda: [{"id": "VYONIX-core-https-8444", "enabled": "True", "profile": "Domain, Private",
                            "port": "8444"}]))
        c = by_id(r)["firewall"]
        self.assertEqual(c.status, "warn")
        self.assertIn("Pública", c.detail)
        self.assertEqual(by_id(startup.run_checks(8444, probes=probes(
            profiles=lambda: [{"alias": "Ethernet 2", "category": "Public"}])))["firewall"].status, "ok")

    def test_html_report_escapes_and_has_no_secrets(self):
        r = startup.run_checks(8444, probes=probes(port_owner=lambda p: {"process": "<script>x</script>", "pid": 1},
                                                   web={("127.0.0.1", "/api/v1/health"): None}))
        h = startup.render_html(r)
        self.assertIn("&lt;script&gt;", h)
        self.assertNotIn("<script>x", h)
        self.assertIn("não está funcionando", h)
        for word in ("password", "senha=", "postgresql://"):
            self.assertNotIn(word, h)


class OpenCommand(unittest.TestCase):
    def run_cli(self, res, *args):
        from vyonix_deploy import cli
        tmp = Path(tempfile.mkdtemp(prefix="vyx-abrir-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        opened = []
        with mock.patch("vyonix_deploy.startup.wait_until_ready", return_value=res), \
                mock.patch("vyonix_deploy.wizard.open_browser_url", side_effect=opened.append), \
                mock.patch("webbrowser.open", side_effect=opened.append), \
                mock.patch("tempfile.gettempdir", return_value=str(tmp)):
            code = cli.main(["abrir", "--porta", "8444", *args])
        return code, opened, tmp

    def test_opens_browser_only_when_working_otherwise_report(self):
        ok = startup.run_checks(8444, probes=probes())
        code, opened, _ = self.run_cli(ok)
        self.assertEqual((code, opened), (0, ["https://localhost:8444/"]))
        bad = startup.run_checks(8444, probes=probes(services={"VyonixCore": None, "VyonixWorker": None,
                                                               "VyonixPostgreSQL": None},
                                                     web={("127.0.0.1", "/api/v1/health"): None}))
        code, opened, tmp = self.run_cli(bad)
        self.assertEqual(code, 1)
        self.assertTrue(opened[0].startswith("file:///") and opened[0].endswith("VYONIX-diagnostico-inicializacao.html"))
        self.assertIn("Instalação configurada", (tmp / "VYONIX-diagnostico-inicializacao.html").read_text("utf-8"))


class Plan(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-plan-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = default_paths(self.tmp)
        self.db = DeployDB(self.paths.db_file)
        self.addCleanup(self.db.close)

    def steps(self, **cfg):
        from vyonix_deploy.plans import install_steps
        return {s.id: s for s in install_steps(Context(cfg=DeployConfig(**cfg), paths=self.paths, db=self.db))}

    def test_public_profile_rule_only_for_local_subnet(self):
        st = self.steps()
        lan = st["firewall.core-lan"]
        d = lan.desired(None)
        self.assertEqual((d["profile"], d["remote"], d["port"]), ("Public", ["LocalSubnet"], "8444"))
        self.assertEqual(st["firewall.core-https"].desired(None)["profile"], "Domain, Private")
        self.assertNotEqual(lan.rule_id.rsplit("-", 1)[0], st["firewall.core-https"].rule_id.rsplit("-", 1)[0])
        # origens explícitas ou opção desligada: a regra do perfil Público é removida, não criada
        self.assertEqual(self.steps(firewall_sources=["10.0.0.0/24"])["remove.firewall.core-lan"].desired(None),
                         {"id": "VYONIX-core-lan-8444", "exists": False})
        self.assertIn("remove.firewall.core-lan", self.steps(firewall_public_lan=False))

    def test_main_shortcut_checks_before_opening(self):
        st = self.steps()
        items = st["shortcuts"].items
        self.assertEqual(items["VYONIX.lnk"]["args"], "abrir --porta 8444")
        self.assertNotIn("VYONIX.url", items)
        self.assertTrue(items["VYONIX Diagnóstico.lnk"]["admin"])        # o DEPLOY exige administrador
        st = self.steps(https_port=8450)
        self.assertEqual(st["shortcuts"].items["VYONIX.lnk"]["args"], "abrir --porta 8450")


if __name__ == "__main__":
    unittest.main()


class HistoryChecks(unittest.TestCase):
    """“VYONIX - Verificar funcionamento” também mostra falhas de inicialização recentes e a situação dos backups."""

    def test_recent_failures_and_backups(self):
        from vyonix_deploy import startup
        r = startup.run_checks(8444, probes=probes(
            events=lambda: [{"at": "29/10 14:02", "service": "", "text": "O serviço VYONIX Core foi encerrado inesperadamente."}],
            backups=lambda: {"count": 0}))
        c = {x.id: x for x in r.checks}
        self.assertEqual(c["events"].status, "warn")
        self.assertIn("encerrado inesperadamente", c["events"].detail)
        self.assertEqual(c["backups"].status, "warn")
        r = startup.run_checks(8444, probes=probes(
            backups=lambda: {"count": 2, "latest": "antes-da-atualizacao-20261029", "size_mb": 3.2, "valid": False}))
        c = {x.id: x for x in r.checks}
        self.assertEqual((c["events"].status, c["backups"].status), ("ok", "warn"))
        self.assertIn("NÃO confere", c["backups"].detail)
        r = startup.run_checks(8444, probes=probes())                          # sem acesso: só o que dá para ler
        self.assertNotIn("backups", {x.id for x in r.checks})
