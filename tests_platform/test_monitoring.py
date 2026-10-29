"""Saúde detalhada (monitoramento técnico): estado consolidado com motivo legível para cada problema.
Plataforma real, PostgreSQL real; motor DUBLÊ DE TESTE ``MemoryBackend``."""

from __future__ import annotations

import socket
import unittest
from datetime import timedelta

from tests_platform.pacs_support import make_dicom
from tests_platform.support import require_db
from tests_platform.test_pacs import ApiBase


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs
    test_pacs.db = db


class HealthDetail(ApiBase):
    URL = "/api/v1/health/detail"

    def setUp(self):
        super().setUp()
        self.c = self.login()
        from unittest import mock
        p = mock.patch("vyonix.monitoring._disk_paths", return_value={})   # o disco do CI varia; testado abaixo
        p.start()
        self.addCleanup(p.stop)

    def test_disk_space_levels_grouped_by_volume(self):
        from collections import namedtuple
        from vyonix import monitoring
        U = namedtuple("U", "total used free")
        gb = 1024 ** 3
        disks = {"/dados": U(500 * gb, 0, 200 * gb), "/imagens": U(1000 * gb, 0, 80 * gb),
                 "/backup": U(100 * gb, 0, 1 * gb)}
        out = monitoring.disk_check({"Dados da plataforma": "/dados", "Imagens do PACS": "/imagens",
                                     "Backup do PACS": "/backup/pasta-ainda-nao-criada"},
                                    usage=lambda p: disks[p], exists=lambda p: p in disks)
        levels = {v["labels"][0]: v["level"] for v in out["volumes"]}
        self.assertEqual(levels, {"Dados da plataforma": "ok", "Imagens do PACS": "warn", "Backup do PACS": "critical"})
        self.assertTrue(out["critical"])
        self.assertEqual(len(out["problems"]), 2)
        self.assertIn("Espaço crítico em disco para Backup do PACS", out["problems"][1])
        same = monitoring.disk_check({"A": "/dados", "B": "/dados"}, usage=lambda p: disks["/dados"],
                                     exists=lambda p: True)
        self.assertEqual(same["volumes"][0]["labels"], ["A", "B"])           # mesmo disco aparece uma vez
        # no painel: disco crítico deixa o estado em falha
        from unittest import mock
        with mock.patch("vyonix.monitoring._disk_paths", return_value={"Imagens do PACS": "/"}), \
                mock.patch("shutil.disk_usage", return_value=disks["/backup"]):
            h = self.c.get(self.URL).json()
        self.assertEqual(h["status"], "falha")
        self.assertTrue(any("Espaço crítico" in p for p in h["problems"]))

    def test_healthy_then_engine_down(self):
        self.license_and_enable()
        body, ctype = self.stow_body(make_dicom())
        self.c.post("/api/v1/pacs/dicomweb/studies", content=body, headers={"Content-Type": ctype})
        h = self.c.get(self.URL).json()
        self.assertEqual(h["status"], "ok", h["problems"])
        self.assertEqual(h["components"]["pacs"]["engine"]["reachable"], True)
        self.assertEqual(h["components"]["pacs"]["index"]["instances"], 1)
        self.assertTrue(h["components"]["license"]["modules"]["pacs"]["licensed"])
        self.assertNotIn("PAC-0001", str(h))                                  # sem dados de paciente
        self.b.down = True
        h = self.c.get(self.URL).json()
        self.assertEqual(h["status"], "falha")
        self.assertTrue(any("Motor DICOM sem resposta" in p for p in h["problems"]))

    def test_stalled_worker_is_flagged(self):
        from sqlalchemy import update
        from vyonix.db.base import utcnow
        from vyonix.events.bus import publish
        from vyonix.events.models import OutboxEvent
        self.license_and_enable()                         # isola a condição testada (sem licença já seria "falha")
        with db.session(self.t) as s:
            publish(s, "teste.evento.v1", {}, source="teste")
            s.execute(update(OutboxEvent).where(OutboxEvent.type == "teste.evento.v1")
                      .values(occurred_at=utcnow() - timedelta(minutes=12)))
        h = self.c.get(self.URL).json()
        ev = h["components"]["events"]
        self.assertGreaterEqual(ev["pending"], 1)
        self.assertGreater(ev["oldest_pending_seconds"], 600)
        self.assertEqual(h["status"], "atenção")
        self.assertTrue(any("VyonixWorker" in p for p in h["problems"]))

    def test_dicom_query_port_down_is_flagged(self):
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            port = sk.getsockname()[1]                                    # porta livre: ninguém escutando
        self.plat.cfg.extra["pacs_qr_port"] = port
        h = self.c.get(self.URL).json()
        self.assertFalse(h["components"]["dicom_qr"]["listening"])
        self.assertTrue(any(f"porta {port}" in p for p in h["problems"]))

    def test_without_license_is_failure(self):
        h = self.c.get(self.URL).json()
        self.assertEqual(h["status"], "falha")
        self.assertIn("Sem licença vigente do VYONIX Core.", h["problems"])

    def test_requires_permission(self):
        from fastapi.testclient import TestClient
        self.assertEqual(TestClient(self.client.app).get(self.URL).status_code, 401)
        r = self.c.post("/api/v1/users", json={"username": "recep", "display_name": "Recepção",
                                               "password": "Senha-Teste-1234", "roles": [{"role": "recepcionista"}]})
        self.assertEqual(r.status_code, 201)
        u = self.login("recep", "Senha-Teste-1234")
        u.post("/api/v1/auth/password", json={"current": "Senha-Teste-1234", "new": "Senha-Nova-9876!"})
        self.assertEqual(self.login("recep", "Senha-Nova-9876!").get(self.URL).status_code, 403)


if __name__ == "__main__":
    unittest.main()
