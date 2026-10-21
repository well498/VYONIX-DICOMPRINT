"""Arquitetura DICOM simplificada e VYONIX Reception — testes obrigatórios 1 a 24 (prompt de
desenvolvimento, seção 20). Os nomes trazem o número do requisito (``r01_``…)."""

from __future__ import annotations

import http.cookiejar
import json
import os
import ssl
import time
import unittest
import urllib.request
import uuid

try:
    import pynetdicom  # noqa: F401
    HAS_NET = True
except ImportError:
    HAS_NET = False

from tests.helpers import TempDirTestCase

STUDY = "1.2.826.0.1.3680043.8.498.77"


class Base(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from app.bootstrap import bootstrap
        from tests.dicom_helpers import free_port
        self.port = free_port()
        self.print_port = free_port()
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        self.addCleanup(lambda: self.ctx.close())
        self.ctx.settings.update({"dicom.storage.bind_address": "127.0.0.1", "dicom.storage.port": self.port,
                                  "dicom.print.port": self.print_port, "jobs.collect_seconds": 2}, actor="t")
        self.svc = self.ctx.devices

    def rule(self, name, called, **kw):
        data = {"name": name, "called_ae": called, "modality": kw.pop("modality", "CT"), **kw}
        return self.svc.create(data, actor="t", authorized=True)

    def ev(self, called, calling="QUALQUER", address="192.168.10.25", port=None, service="store"):
        return self.ctx.storage_scp.policy.evaluate(
            calling_ae=calling, called_ae=called, address=address, local_ae="VYONIX",
            accept_unknown=False, port=port or self.port, default_port=self.port, service=service)

    def send(self, called, n=2, calling="CT_SALA1", study=STUDY, series="1.2.826.0.1.3680043.8.498.77.1",
             port=None, **attrs):
        from app.dicom import scu
        from tests.dicom_helpers import make_ct
        files = [make_ct(self.tmp / f"in-{uuid.uuid4().hex}.dcm", study_uid=study, series_uid=series, value=500 + i,
                         patient_name="SILVA^MARIA", AccessionNumber="ACC123", AdmissionID="AT-55",
                         **attrs) for i in range(n)]
        return scu.store_files("127.0.0.1", port or self.port, called, files, calling_ae=calling)

    def flush(self):
        return self.ctx.worker.collector.flush(force=True)


@unittest.skipUnless(HAS_NET, "pydicom/pynetdicom não instalados")
class RoutingTest(Base):
    def test_r01_rule_without_equipment_ip(self):
        r = self.rule("Tomografia 01", "VYONIX_CT01")
        self.assertIsNone(r.ip_address)
        self.assertEqual(r.ae_title, "*")
        self.assertEqual(r.called_ae, "VYONIX_CT01")
        self.assertTrue(self.ev("VYONIX_CT01", address="10.9.8.7").accepted)

    def test_r02_called_ae_selects_rule(self):
        r = self.rule("Tomografia 01", "VYONIX_CT01")
        d = self.ev("VYONIX_CT01")
        self.assertTrue(d.accepted)
        self.assertEqual(d.device_id, r.id)

    def test_r03_unknown_called_ae_rejected_and_logged(self):
        from app.dicom import scu
        from app.dicom.routing import DIAG_CALLED_AE
        self.rule("Tomografia 01", "VYONIX_CT01")
        self.assertEqual(self.ev("NAO_EXISTE").diagnostic, DIAG_CALLED_AE)
        self.ctx.storage_scp.start()
        self.assertFalse(scu.echo("127.0.0.1", self.port, "NAO_EXISTE", calling_ae="X")["ok"])
        self._wait_event("assoc.reject")
        # opção explícita: AE padrão do servidor aceito sem regra (configurações globais)
        self.assertTrue(self.ctx.storage_scp.policy.evaluate(
            calling_ae="X", called_ae="VYONIX", address="1.2.3.4", local_ae="VYONIX", accept_unknown=True,
            port=self.port, default_port=self.port).accepted)

    def _wait_event(self, action):
        from app.database.repositories.events_repo import EventFilter
        end = time.monotonic() + 5
        while time.monotonic() < end:
            if any(e.action == action for e in self.ctx.events.query(EventFilter(limit=100))):
                return
            time.sleep(0.05)
        self.fail(f"evento {action} ausente")

    def test_r04_two_rules_same_port_different_called(self):
        a = self.rule("CT 01", "VYONIX_CT01")
        b = self.rule("CT 02", "VYONIX_CT02", modality="CT")
        self.assertEqual(self.ev("VYONIX_CT01").device_id, a.id)
        self.assertEqual(self.ev("VYONIX_CT02").device_id, b.id)

    def test_r05_same_called_different_calling(self):
        a = self.rule("Sala 1", "VYONIX_CT", ae_title="CT_SALA1")
        b = self.rule("Sala 2", "VYONIX_CT", ae_title="CT_SALA2")
        self.assertEqual(self.ev("VYONIX_CT", calling="CT_SALA1").device_id, a.id)
        self.assertEqual(self.ev("VYONIX_CT", calling="CT_SALA2").device_id, b.id)
        self.assertFalse(self.ev("VYONIX_CT", calling="OUTRO").accepted)
        c = self.rule("Qualquer outro", "VYONIX_CT")                # genérica: vale para as demais origens
        self.assertEqual(self.ev("VYONIX_CT", calling="OUTRO").device_id, c.id)
        self.assertEqual(self.ev("VYONIX_CT", calling="CT_SALA1").device_id, a.id)   # específica prevalece

    def test_r06_ambiguous_rules_are_not_allowed(self):
        from app.core.errors import SettingsValidationError
        self.rule("CT 01", "VYONIX_CT01")
        with self.assertRaises(SettingsValidationError) as cm:
            self.rule("CT 01 cópia", "VYONIX_CT01")
        self.assertIn("Calling AE", str(cm.exception))
        # ambiguidade criada fora da validação (ex.: banco editado) é recusada, não resolvida em silêncio
        self.ctx.db.connection().execute(
            "INSERT INTO devices(name, ae_title, called_ae, service, authorized, active, created_at, updated_at) "
            "VALUES ('Duplicada', '*', 'VYONIX_CT01', 'store', 1, 1, 'x', 'x')")
        d = self.ev("VYONIX_CT01")
        self.assertFalse(d.accepted)
        self.assertIn("ambíguas", d.reason)

    def test_r07_equipment_ip_change_needs_no_edit(self):
        r = self.rule("CT 01", "VYONIX_CT01")
        self.assertEqual(self.ev("VYONIX_CT01", address="192.168.1.10").device_id, r.id)
        self.assertEqual(self.ev("VYONIX_CT01", address="10.20.30.40").device_id, r.id)

    def test_r08_optional_ip_restriction(self):
        r = self.rule("CT 01", "VYONIX_CT01", ip_address="192.168.1.0/24, 10.0.0.5")
        self.assertEqual(self.svc.get(r.id).ip_address, "192.168.1.0/24, 10.0.0.5")
        self.assertTrue(self.ev("VYONIX_CT01", address="192.168.1.77").accepted)
        self.assertTrue(self.ev("VYONIX_CT01", address="10.0.0.5").accepted)
        d = self.ev("VYONIX_CT01", address="192.168.2.1")
        self.assertFalse(d.accepted)
        self.assertIn("fora da restrição", d.reason)

    def test_r09_optional_calling_restriction(self):
        self.rule("CT 01", "VYONIX_CT01", ae_title="CT_SIEMENS")
        self.assertTrue(self.ev("VYONIX_CT01", calling="CT_SIEMENS").accepted)
        d = self.ev("VYONIX_CT01", calling="CT_OUTRO")
        self.assertFalse(d.accepted)
        self.assertIn("não autorizado", d.reason)

    def test_dedicated_listener_port_and_conflicts(self):
        from app.core.errors import SettingsValidationError
        from tests.dicom_helpers import free_port
        extra = free_port()
        r = self.rule("US 01", "VYONIX_US01", listen_port=extra, modality="US")
        self.assertFalse(self.ev("VYONIX_US01").accepted)                         # porta padrão: não
        self.assertEqual(self.ev("VYONIX_US01", port=extra).device_id, r.id)       # porta própria: sim
        with self.assertRaises(SettingsValidationError):
            self.rule("Conflito", "VYONIX_X", listen_port=self.print_port)          # porta do Print SCP
        self.ctx.storage_scp.start()
        self.assertEqual(self.ctx.storage_scp.ports, sorted({self.port, extra}))
        from app.dicom import scu
        self.assertTrue(scu.echo("127.0.0.1", extra, "VYONIX_US01", calling_ae="QUALQUER")["ok"])   # r12

    def test_r12_echo_and_technician_screen_data(self):
        from app.dicom import scu
        from app.utils.net import best_server_address
        self.rule("Tomografia 01", "VYONIX_CT01", ip_address="127.0.0.0/8")
        self.ctx.storage_scp.start()
        self.assertTrue(scu.echo("127.0.0.1", self.port, "VYONIX_CT01", calling_ae="CT")["ok"])
        self.assertTrue(scu.echo("127.0.0.1", self.port, "VYONIX_CT01", calling_ae="VYONIX_TEST")["ok"])
        ip, ips = best_server_address("0.0.0.0", "127.0.0.0/8")
        self.assertIsInstance(ips, list)
        ip2, _ = best_server_address("192.168.5.20", None)
        self.assertEqual(ip2, "192.168.5.20")


@unittest.skipUnless(HAS_NET, "pydicom/pynetdicom não instalados")
class FlowTest(Base):
    def setUp(self):
        super().setUp()
        self.ctx.storage_scp.start()

    def test_r10_r13_cstore_auto_print_and_exam_registered(self):
        from app.printing.backends.pdf import PDF_PRINTER
        r = self.rule("Tomografia 01", "VYONIX_CT01")
        self.ctx.device_settings.save(r.id, {"printer": PDF_PRINTER, "auto_print": True}, actor="t")
        self.assertEqual(self.send("VYONIX_CT01"), [0, 0])
        exams = self.ctx.exams.search()["exams"]
        self.assertEqual(len(exams), 1)
        e = exams[0]
        self.assertEqual((e["patient_name"], e["accession"], e["admission_id"], e["called_ae"]),
                         ("SILVA MARIA", "ACC123", "AT-55", "VYONIX_CT01"))
        self.assertEqual(e["device_id"], r.id)
        self.assertIn(e["print_state"], ("receiving", "awaiting"))      # fim da associação não conclui
        jobs = self.flush()
        self.assertEqual(len(jobs), 1)
        self.ctx.worker.process(self.ctx.jobs.get_job(jobs[0]))
        st = self.ctx.exams.search()["exams"][0]["print_state"]
        self.assertIn(st, ("spooled", "confirmed"))

    def test_r14_on_demand_waits_for_reception(self):
        r = self.rule("CR recepção", "VYONIX_CR", modality="CR")
        self.ctx.device_settings.save(r.id, {"auto_print": False}, actor="t")
        self.send("VYONIX_CR", n=1)
        self.flush()
        e = self.ctx.exams.search()["exams"][0]
        self.assertEqual(e["print_state"], "available")
        self.assertEqual(self.ctx.exams.saved_sheets()["exams"], 1)

    def test_r11_dicom_print_is_a_separate_service(self):
        """O filme DICOM Print vira exame "dicom_print" pela regra de impressão (não é um C-STORE)."""
        from tests.test_print_scp import PrintSCPTest  # noqa: F401 - mesmos utilitários de filme
        r = self.svc.create({"name": "Impressão CT", "called_ae": "VYONIX_PRT", "service": "print"}, actor="t",
                            authorized=True)
        d = self.ctx.print_scp.policy.evaluate(calling_ae="CT", called_ae="VYONIX_PRT", address="10.0.0.1",
                                               local_ae="VYONIX_PRINT", accept_unknown=False,
                                               port=self.print_port, default_port=self.print_port, service="print")
        self.assertTrue(d.accepted)
        self.assertEqual(d.device_id, r.id)
        # a mesma combinação no serviço C-STORE não existe
        self.assertFalse(self.ev("VYONIX_PRT").accepted)

    def test_r22_recovery_after_restart(self):
        from app.bootstrap import bootstrap
        r = self.rule("CT", "VYONIX_CT01")
        self.ctx.device_settings.save(r.id, {"auto_print": False}, actor="t")
        self.send("VYONIX_CT01", n=1)
        self.ctx.close()
        self.ctx = bootstrap(data_dir=self.tmp / "data")      # reinício antes da conclusão
        self.assertEqual(len(self.ctx.worker.collector.flush(force=True)), 1)
        e = self.ctx.exams.search()["exams"][0]
        self.assertEqual(e["print_state"], "available")
        self.assertEqual(e["patient_name"], "SILVA MARIA")


@unittest.skipUnless(HAS_NET, "pydicom/pynetdicom não instalados")
class ReceptionTest(Base):
    def setUp(self):
        super().setUp()
        from app.printing.backends.pdf import PDF_PRINTER
        from tests.dicom_helpers import free_port
        self.web_port = free_port()
        self.ctx.settings.update({"reception.port": self.web_port, "reception.bind_address": "127.0.0.1"}, actor="t")
        self.r = self.rule("Tomografia 01", "VYONIX_CT01")
        self.ctx.device_settings.save(self.r.id, {"printer": PDF_PRINTER, "auto_print": False}, actor="t")
        self.ctx.users.create("recep", "Recepção", "receptionist", "Recep1234", actor="t", must_change=False)
        self.ctx.users.create("super", "Supervisora", "supervisor", "Super1234", actor="t", must_change=False)
        self.ctx.storage_scp.start()
        self.ctx.reception.start()
        self.addCleanup(self.ctx.reception.stop)
        self.send("VYONIX_CT01", n=2)
        self.flush()
        self.exam = self.ctx.exams.search()["exams"][0]

    def client(self, user, pw):
        jar = http.cookiejar.CookieJar()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx),
                                             urllib.request.HTTPCookieProcessor(jar))
        base = f"https://127.0.0.1:{self.web_port}"
        state = {}

        def call(path, body=None, csrf=True):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET")
            if body is not None:
                req.add_header("Content-Type", "application/json")
                if csrf and state.get("csrf"):
                    req.add_header("X-CSRF-Token", state["csrf"])
            try:
                with opener.open(req, timeout=20) as r:
                    return r.status, json.loads(r.read() or b"{}"), dict(r.headers)
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"{}"), dict(e.headers)
        code, me, headers = call("/api/login", {"username": user, "password": pw})
        self.assertEqual(code, 200, me)
        self.assertIn("HttpOnly", headers.get("Set-Cookie", ""))
        state["csrf"] = me["csrf"]
        call.me = me
        return call

    def wait_job_done(self):
        for j in self.ctx.db.connection().execute("SELECT id FROM jobs WHERE state IN ('received','validating')"):
            self.ctx.worker.process(self.ctx.jobs.get_job(j["id"]))

    def test_r18_search_and_security(self):
        c = self.client("recep", "Recep1234")
        code, res, _ = c(f"/api/exams?q=silva")
        self.assertEqual(code, 200)
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["by_modality"], {"CT": 1})
        for q in ("q=ACC123", "q=AT-55", "q=SINT-0001", f"rule={self.r.id}", "modality=CT", "print_state=available",
                  "pickup_state=aguardando_preparacao"):
            self.assertEqual(c(f"/api/exams?{q}")[1]["total"], 1, q)
        self.assertEqual(c("/api/exams?modality=MR")[1]["total"], 0)
        self.assertEqual(c("/api/exams?q=OUTRO")[1]["total"], 0)
        code, d, headers = c(f"/api/exams/{self.exam['id']}")
        self.assertEqual(d["exam"]["patient_name"], "SILVA MARIA")
        self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""))
        self.assertEqual(c("/api/reports?group=modality")[0], 400)            # recepcionista: sem relatórios
        self.assertEqual(c(f"/api/exams/{self.exam['id']}/print", {}, csrf=False)[0], 403)   # sem token CSRF
        # sem sessão
        anon = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        with self.assertRaises(urllib.error.HTTPError) as cm:
            anon.open(f"https://127.0.0.1:{self.web_port}/api/exams")
        self.assertEqual(cm.exception.code, 401)
        # página estática
        with anon.open(f"https://127.0.0.1:{self.web_port}/") as r:
            self.assertIn(b"VYONIX", r.read())

    def test_r19_r20_print_duplicate_and_reprint(self):
        c = self.client("recep", "Recep1234")
        eid = self.exam["id"]
        key = str(uuid.uuid4())
        code, res, _ = c(f"/api/exams/{eid}/print", {"request_key": key})
        self.assertEqual(code, 200, res)
        code2, res2, _ = c(f"/api/exams/{eid}/print", {"request_key": key})     # clique repetido
        self.assertTrue(res2.get("replayed"))
        self.assertEqual(res2["jobs"], res["jobs"])
        code3, res3, _ = c(f"/api/exams/{eid}/print", {"request_key": str(uuid.uuid4())})   # enquanto na fila
        self.assertEqual(code3, 400)
        self.assertIn("já está na fila", res3["error"])
        self.wait_job_done()
        code, res, _ = c(f"/api/exams/{eid}/print", {"request_key": str(uuid.uuid4())})
        self.assertEqual(code, 409)
        self.assertTrue(res["duplicate"])
        self.assertIn("já foi impresso", res["error"])
        code, res, _ = c(f"/api/exams/{eid}/print", {"request_key": str(uuid.uuid4()), "confirm_duplicate": True,
                                                     "reason": "segunda via"})
        self.assertEqual(code, 400)                                          # recepcionista não reimprime
        s = self.client("super", "Super1234")
        code, res, _ = s(f"/api/exams/{eid}/print", {"request_key": str(uuid.uuid4()), "confirm_duplicate": True})
        self.assertIn("motivo", res["error"])
        code, res, _ = s(f"/api/exams/{eid}/print", {"request_key": str(uuid.uuid4()), "confirm_duplicate": True,
                                                     "reason": "paciente perdeu o filme"})
        self.assertEqual(code, 200, res)
        self.assertTrue(res["duplicate"])
        hist = s(f"/api/exams/{eid}")[1]["history"]
        rp = [h for h in hist if h["action"] == "reprint"][0]
        self.assertIn("paciente perdeu o filme", rp["detail"])
        self.assertEqual(rp["actor"], "usuario:super")
        rep = s("/api/reports?group=user")[1]
        self.assertTrue(any(r["chave"] == "usuario:super" for r in rep["rows"]))

    def test_r19_print_now_keeps_rule_settings(self):
        from app.printing.backends.pdf import PDF_PRINTER
        c = self.client("recep", "Recep1234")
        eid = self.exam["id"]
        before = self.ctx.device_settings.get(self.r.id)
        code, res, _ = c(f"/api/exams/{eid}/print-now", {"request_key": str(uuid.uuid4()), "printer": PDF_PRINTER,
                                                         "copies": 3})
        self.assertEqual(code, 200, res)
        job = self.ctx.jobs.get_job(res["jobs"][0])
        self.assertEqual(job.copies, 3)
        self.assertEqual(self.ctx.device_settings.get(self.r.id), before)
        code, prev, _ = c(f"/api/exams/{eid}/preview")
        self.assertEqual(code, 200)
        self.assertTrue(prev["pages"][0].startswith("data:image/png;base64,"))

    def test_r21_pickup_control(self):
        c = self.client("recep", "Recep1234")
        eid = self.exam["id"]
        self.assertEqual(c(f"/api/exams/{eid}/pickup", {"state": "pronto"})[0], 200)
        self.assertEqual(c(f"/api/exams/{eid}/pickup", {"state": "entregue"})[0], 400)      # exige quem retirou
        code, res, _ = c(f"/api/exams/{eid}/pickup", {"state": "entregue", "delivered_to": "Maria (RG 123)"})
        self.assertEqual(code, 200)
        e = self.ctx.exams.get(eid)
        self.assertEqual((e["pickup_state"], e["delivered_to"], e["pickup_by"]),
                         ("entregue", "Maria (RG 123)", "usuario:recep"))
        self.assertEqual(c(f"/api/exams/{eid}/pickup", {"state": "entrega_cancelada"})[0], 400)  # só supervisor
        s = self.client("super", "Super1234")
        self.assertEqual(s(f"/api/exams/{eid}/pickup", {"state": "entrega_cancelada", "note": "engano"})[0], 200)
        # impressão não marca entrega
        st = self.ctx.exams.search()["exams"][0]
        self.assertEqual(st["pickup_state"], "entrega_cancelada")

    def test_technical_settings_restricted_by_profile(self):
        self.ctx.access.set_password("Admin-Mestre-1", current=None, actor="t")
        self.ctx.users.create("tec", "Técnico", "technician", "Tecnico123", actor="t", must_change=False)
        self.ctx.access.lock()
        self.assertFalse(self.ctx.access.is_unlocked())
        self.assertTrue(self.ctx.access.unlock("tec:Tecnico123", actor="t"))
        self.ctx.access.lock()
        self.assertFalse(self.ctx.access.unlock("recep:Recep1234", actor="t"))
        c = self.client("recep", "Recep1234")
        self.assertNotIn("technical", c.me["perms"])
        self.assertIn("technical", self.ctx.users.authenticate("tec", "Tecnico123").public()["perms"])

    def test_alerts_and_login_lockout(self):
        alerts = self.ctx.exams.alerts()
        self.assertIsInstance(alerts, list)
        for _ in range(5):
            try:
                self.ctx.users.authenticate("recep", "errada")
            except Exception:  # noqa: BLE001
                pass
        from app.security.users import AuthError
        with self.assertRaisesRegex(AuthError, "bloqueado"):
            self.ctx.users.authenticate("recep", "Recep1234")


@unittest.skipUnless(HAS_NET, "pydicom/pynetdicom não instalados")
class CalibrationAndPersistenceTest(Base):
    def test_r15_r16_r17_rule_calibration_sheet_and_identity(self):
        from app.imaging import tone
        from app.printing import calibration_sheet as cs
        a = self.rule("CT A", "VYONIX_A")
        b = self.rule("CT B", "VYONIX_B")
        self.ctx.device_settings.save_tone(a.id, tone.ToneControls(brightness=1.5, contrast=-0.5, gamma=0.5),
                                           actor="t", reason="teste")
        self.ctx.device_settings.save(b.id, {"header_enabled": False, "footer_enabled": True}, actor="t")
        va, vb = self.ctx.device_settings.get(a.id), self.ctx.device_settings.get(b.id)
        self.assertEqual((va["brightness"], va["contrast"], va["gamma"]), (1.5, -0.5, 0.5))
        self.assertNotIn("brightness", vb)
        self.assertFalse(vb["header_enabled"])
        m = cs.build_matrix(tone.ToneControls(gamma=0.5), "gamma_contrast", 0.5)
        self.assertEqual(len(m.cells), 9)
        self.assertTrue(self.ctx.templates.info("header").is_standard)

    def test_r23_update_keeps_configuration(self):
        from app.bootstrap import bootstrap
        r = self.rule("CT A", "VYONIX_A", ae_title="CT_X", ip_address="10.0.0.0/8", listen_port=None)
        self.ctx.users.create("tec", "Técnico", "technician", "Tecnico123", actor="t")
        self.ctx.close()
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        d = self.ctx.devices.get(r.id)
        self.assertEqual((d.called_ae, d.ae_title, d.ip_address), ("VYONIX_A", "CT_X", "10.0.0.0/8"))
        self.assertEqual([u["username"] for u in self.ctx.users.list()], ["tec"])

    def test_r23_migration_converts_100_equipment(self):
        """Banco da 1.0.0: equipamento (AE + IP) vira regra com destino = AE local e as mesmas restrições."""
        from app.database.connection import Database
        from app.database.migrations import MIGRATIONS
        from app.database.migrator import migrate
        db = Database(self.tmp / "old.db")
        self.addCleanup(db.close)
        migrate(db, MIGRATIONS[:5], backup_dir=self.tmp / "bk")
        db.connection().execute("""INSERT INTO devices(name, ae_title, ip_address, authorized, active, created_at,
                                   updated_at) VALUES ('CT antigo', 'CT_OLD', '10.1.1.1', 1, 1, 'x', 'x')""")
        db.connection().execute("""INSERT INTO settings(key, value_json, updated_at, updated_by)
                                   VALUES ('dicom.storage.ae_title', '"CLINICA"', 'x', 't')""")
        migrate(db, MIGRATIONS, backup_dir=self.tmp / "bk")
        r = db.connection().execute("SELECT called_ae, ae_title, ip_address, service FROM devices").fetchone()
        self.assertEqual(tuple(r), ("CLINICA", "CT_OLD", "10.1.1.1", "store"))

    def test_r24_license_validation_still_applies(self):
        os.environ["VYONIX_LICENSE_ENFORCE"] = "1"
        try:
            from app.bootstrap import bootstrap
            ctx = bootstrap(data_dir=self.tmp / "lic")
        finally:
            os.environ["VYONIX_LICENSE_ENFORCE"] = "0"
        try:
            self.assertFalse(ctx.license.allows("printing"))
            ctx.license.start_demo(actor="t")
            self.assertTrue(ctx.license.allows("printing"))
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
