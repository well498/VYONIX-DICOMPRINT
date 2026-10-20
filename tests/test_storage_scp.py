"""Fase 2 — Storage SCP real em 127.0.0.1, com pynetdicom como equipamento simulado (SCU)."""

import time
import unittest

try:
    import pynetdicom  # noqa: F401
    HAS_NET = True
except ImportError:
    HAS_NET = False

from tests.helpers import TempDirTestCase


@unittest.skipUnless(HAS_NET, "pydicom/pynetdicom não instalados")
class StorageSCPTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from app.bootstrap import bootstrap
        from tests.dicom_helpers import free_port

        self.port = free_port()
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        self.ctx.settings.update({"dicom.storage.bind_address": "127.0.0.1",
                                  "dicom.storage.port": self.port}, actor="t")
        self.ctx.storage_scp.start()
        self.assertEqual(self.ctx.storage_scp.status().state.value, "running")
        self.device = self.ctx.devices.create(
            {"name": "CT teste", "ae_title": "CT_TESTE", "modality": "CT", "ip_address": "127.0.0.1"},
            actor="t")

    def tearDown(self):
        self.ctx.close()
        super().tearDown()

    def authorize(self):
        self.ctx.devices.set_authorized(self.device.id, True, actor="t")

    def wait_events(self, action, n=1, timeout=5.0):
        from app.database.repositories.events_repo import EventFilter
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            found = [e for e in self.ctx.events.query(EventFilter(limit=200)) if e.action == action]
            if len(found) >= n:
                return found
            time.sleep(0.05)
        self.fail(f"evento {action} não registrado")

    def test_echo_from_registered_device(self):
        from app.dicom import scu
        self.authorize()
        r = scu.echo("127.0.0.1", self.port, "VYONIX", calling_ae="CT_TESTE")
        self.assertTrue(r["ok"], r)

    def test_rejections(self):
        from app.dicom import scu
        # Não autorizado
        self.assertIn("recusada", scu.echo("127.0.0.1", self.port, "VYONIX", calling_ae="CT_TESTE")["detail"])
        # Desconhecido
        self.assertFalse(scu.echo("127.0.0.1", self.port, "VYONIX", calling_ae="DESCONHECIDO")["ok"])
        # Called AE errado
        self.authorize()
        self.assertFalse(scu.echo("127.0.0.1", self.port, "OUTRO_AE", calling_ae="CT_TESTE")["ok"])
        rejects = self.wait_events("assoc.reject", 3)
        self.assertTrue(all(e.level == "WARNING" for e in rejects))
        # IP diferente do cadastrado
        self.ctx.devices.update(self.device.id, {"ip_address": "10.9.9.9"}, actor="t")
        self.assertFalse(scu.echo("127.0.0.1", self.port, "VYONIX", calling_ae="CT_TESTE")["ok"])

    def test_store_persists_dedupes_and_audits(self):
        from app.dicom import scu
        from tests.dicom_helpers import make_ct
        self.authorize()
        files = [make_ct(self.tmp / f"in/{i}.dcm") for i in range(3)]
        self.assertEqual(scu.store_files("127.0.0.1", self.port, "VYONIX", files, calling_ae="CT_TESTE"),
                         [0, 0, 0])
        rows = self.ctx.db.connection().execute(
            "SELECT * FROM instances ORDER BY id").fetchall()
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["source_ae"], "CT_TESTE")
            self.assertEqual(row["device_id"], self.device.id)
            self.assertEqual(row["modality"], "CT")
            self.assertTrue(row["file_path"].startswith(str(self.ctx.paths.storage_dir)))
            self.assertIsNotNone(row["purge_after"])
        # Reenvio: duplicatas idênticas confirmadas sem novo armazenamento
        self.assertEqual(scu.store_files("127.0.0.1", self.port, "VYONIX", files[:2],
                                         calling_ae="CT_TESTE"), [0, 0])
        count = self.ctx.db.connection().execute("SELECT COUNT(*) FROM instances").fetchone()[0]
        self.assertEqual(count, 3)
        complete = self.wait_events("assoc.complete", 2)
        self.assertIn("2 duplicada(s)", complete[0].message)
        # Nenhum dado de paciente no evento
        self.assertNotIn("SINTETICO", " ".join(e.message for e in complete))
        dev = self.ctx.devices.get(self.device.id)
        self.assertIsNotNone(dev.last_seen_at)
        self.assertEqual(dev.comm_status, "ok")
        # Nenhum arquivo temporário sobrando
        self.assertEqual(list(self.ctx.paths.temp_dir.glob("rx-*")), [])

    def test_size_limit_and_invalid_dataset(self):
        from app.core.contracts import AssociationPeer
        from app.dicom.storage import STATUS_CANNOT_UNDERSTAND, STATUS_OUT_OF_RESOURCES
        peer = AssociationPeer("CT_TESTE", "VYONIX", "127.0.0.1", 1)
        out = self.ctx.store.store(b"x" * 2048, peer, None, max_bytes=1024)
        self.assertEqual(out.status, STATUS_OUT_OF_RESOURCES)
        out = self.ctx.store.store(b"lixo" * 100, peer, None, max_bytes=1 << 20)
        self.assertEqual(out.status, STATUS_CANNOT_UNDERSTAND)
        self.assertEqual(list(self.ctx.paths.temp_dir.glob("rx-*")), [])

    def test_path_traversal_uid_is_rejected(self):
        from app.core.contracts import AssociationPeer
        from app.dicom.storage import STATUS_DATASET_MISMATCH
        from tests.dicom_helpers import make_ct
        bad = make_ct(self.tmp / "bad.dcm", study_uid="..\\..\\evil")
        peer = AssociationPeer("CT_TESTE", "VYONIX", "127.0.0.1", 1)
        out = self.ctx.store.store(bad.read_bytes(), peer, None, max_bytes=1 << 20)
        self.assertEqual(out.status, STATUS_DATASET_MISMATCH)

    def test_concurrent_associations_and_connection_cleanup(self):
        import threading

        from app.dicom import scu
        from tests.dicom_helpers import make_ct
        self.authorize()
        results = []

        def send(n):
            files = [make_ct(self.tmp / f"c{n}/{i}.dcm") for i in range(4)]
            results.append(scu.store_files("127.0.0.1", self.port, "VYONIX", files, calling_ae="CT_TESTE"))

        threads = [threading.Thread(target=send, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(sorted(sum(results, [])), [0] * 16)
        self.wait_events("assoc.complete", 4)
        time.sleep(0.3)
        # Conexões de banco das threads de associação foram fechadas
        self.assertLessEqual(self.ctx.db.open_connections(), 2)

    def test_restart_on_port_change_and_bind_error(self):
        import socket
        from tests.dicom_helpers import free_port
        busy = socket.socket()
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        try:
            self.ctx.storage_scp.stop()
            self.ctx.settings.update({"dicom.storage.port": busy.getsockname()[1]}, actor="t")
            self.ctx.storage_scp.start()
            st = self.ctx.storage_scp.status()
            self.assertEqual(st.state.value, "error")
            self.assertIn("em uso", st.detail)
        finally:
            busy.close()
        self.ctx.settings.update({"dicom.storage.port": free_port()}, actor="t")
        self.ctx.storage_scp.start()
        self.assertEqual(self.ctx.storage_scp.status().state.value, "running")


class RetentionTest(TempDirTestCase):
    def test_purge_old_instances_keeps_active_jobs(self):
        from datetime import timedelta

        from app.bootstrap import bootstrap
        from app.utils.timeutil import to_iso, utc_now
        ctx = bootstrap(data_dir=self.tmp / "d")
        try:
            conn = ctx.db.connection()
            old = to_iso(utc_now() - timedelta(days=60))
            files = []
            for i in range(3):
                f = ctx.paths.storage_dir / "1.2" / "3" / f"{i}.dcm"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"x" * 100)
                files.append(f)
                conn.execute("INSERT INTO instances(sop_instance_uid, sop_class_uid, study_uid, series_uid,"
                             " transfer_syntax, file_path, file_sha256, file_size, source_ae, received_at)"
                             " VALUES (?, '1.2', '1.2', '3', '1.2', ?, 'h', 100, 'X', ?)",
                             (f"9.{i}", str(f), old))
            conn.execute("INSERT INTO jobs(id, uuid, idempotency_key, source_type, state, created_at, updated_at)"
                         " VALUES (1, 'u1', 'k1', 'storage', 'waiting_print', 't', 't')")
            conn.execute("INSERT INTO job_items(job_id, instance_id, position) VALUES (1, 1, 0)")
            result = ctx.retention.purge()
            self.assertEqual(result["instances"], 2)
            self.assertTrue(files[0].exists())            # ligada a trabalho em andamento
            self.assertFalse(files[1].exists())
            self.assertFalse(files[2].exists())
            conn.execute("UPDATE jobs SET state = 'completed' WHERE id = 1")
            self.assertEqual(ctx.retention.purge()["instances"], 1)
            self.assertFalse(files[0].exists())
            self.assertFalse((ctx.paths.storage_dir / "1.2").exists())   # pastas vazias removidas
        finally:
            ctx.close()


class AdminAccessTest(TempDirTestCase):
    def test_password_flow(self):
        from app.bootstrap import bootstrap
        from app.security.access import AccessDenied
        ctx = bootstrap(data_dir=self.tmp / "d")
        try:
            acc = ctx.access
            self.assertTrue(acc.is_unlocked())            # sem senha: livre
            acc.require("teste")
            with self.assertRaises(Exception):
                acc.set_password("curta", current=None, actor="t")
            acc.set_password("senha-forte-1", current=None, actor="t")
            raw = ctx.db.connection().execute("SELECT value_json FROM settings WHERE key='security.admin'").fetchone()[0]
            self.assertNotIn("senha-forte-1", raw)
            acc.lock()
            with self.assertRaises(AccessDenied):
                acc.require("alterar configurações")
            self.assertFalse(acc.unlock("errada", actor="t"))
            self.assertTrue(acc.unlock("senha-forte-1", actor="t"))
            acc.require("alterar configurações")
            with self.assertRaises(AccessDenied):
                acc.set_password("nova-senha-2", current="errada", actor="t")
            acc.lock()
            for _ in range(5):
                acc.unlock("errada", actor="t")
            with self.assertRaises(AccessDenied):         # bloqueio temporário após 5 erros
                acc.unlock("senha-forte-1", actor="t")
        finally:
            ctx.close()
