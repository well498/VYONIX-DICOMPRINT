"""Motor DICOM supervisionado (``vyonix.pacs.engine_host``) com o binário REAL do Orthanc: partida com a
configuração no formato gerado pelo DEPLOY, autenticação, armazenamento, parada limpa por
``/tools/shutdown`` (código 0), dados preservados após reiniciar, e detecção de queda do processo.

Exige ``VYONIX_TEST_ORTHANC_BIN`` (no CI da plataforma: /usr/sbin/Orthanc). Sem ela é pulado com motivo.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import time
import unittest
from pathlib import Path

from tests_platform.pacs_support import make_dicom, uid

BIN = os.environ.get("VYONIX_TEST_ORTHANC_BIN", "")


def setUpModule():
    if not BIN or not Path(BIN).exists():
        raise unittest.SkipTest("VYONIX_TEST_ORTHANC_BIN não definida (binário do Orthanc).")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class EngineHost(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-engine-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.http, self.dicom = free_port(), free_port()
        st = str(self.tmp / "storage")
        self.cfg = self.tmp / "orthanc.json"
        self.cfg.write_text(json.dumps({
            "Name": "VYONIX teste", "StorageDirectory": st, "IndexDirectory": st, "HttpPort": self.http,
            "RemoteAccessAllowed": False, "AuthenticationEnabled": True, "RegisteredUsers": {"vyonix": "s3nha-teste"},
            "DicomAet": "VYONIX_PACS", "DicomPort": self.dicom, "DicomCheckCalledAet": True, "Plugins": [],
            "OverwriteInstances": False}), encoding="utf-8")

    def engine(self):
        from vyonix.pacs.engine_host import EngineProcess
        e = EngineProcess(Path(BIN), self.cfg, log_file=self.tmp / "logs" / "orthanc.log")
        self.addCleanup(e.stop)
        return e

    def backend(self, pw="s3nha-teste"):
        from vyonix.pacs.orthanc import OrthancBackend
        b = OrthancBackend(f"http://127.0.0.1:{self.http}", username="vyonix", password=pw)
        self.addCleanup(b.close)
        return b

    def test_start_store_clean_stop_restart_keeps_data(self):
        e = self.engine()
        e.start()
        self.assertTrue(e.alive())
        info = self.backend().ping()
        self.assertEqual((info["dicom_aet"], info["dicom_port"]), ("VYONIX_PACS", self.dicom))
        import httpx
        with self.assertRaises(httpx.HTTPStatusError):
            self.backend("errada").ping()
        data = make_dicom(study=uid(77), series=uid(77, 1), sop=uid(77, 1, 1))
        ref = self.backend().store(data)
        self.assertEqual(e.stop(), 0)                                     # parada limpa
        self.assertFalse(e.alive())
        self.assertTrue((self.tmp / "logs" / "orthanc.log").stat().st_size > 0)
        e2 = self.engine()
        e2.start()
        self.assertEqual(self.backend().fetch(ref.backend_id), data)       # índice e arquivo preservados
        e2.stop()

    def test_crash_is_detected(self):
        e = self.engine()
        e.start()
        e.proc.kill()
        e.thread.join(10)
        self.assertFalse(e.alive())
        self.assertFalse(e.thread.is_alive())                              # o serviço termina com erro

    def test_bad_config_fails_fast(self):
        from vyonix.pacs.engine_host import EngineProcess
        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps({"HttpPort": self.http, "StorageDirectory": "/proc/nao-gravavel/x",
                                   "IndexDirectory": "/proc/nao-gravavel/x", "Plugins": []}), encoding="utf-8")
        t = time.monotonic()
        with self.assertRaises(RuntimeError):
            EngineProcess(Path(BIN), bad).start(wait_s=30)
        self.assertLess(time.monotonic() - t, 30)


if __name__ == "__main__":
    unittest.main()
