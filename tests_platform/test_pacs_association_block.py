"""BLK-15 (fase simulada) — recusa de equipamentos não autorizados na associação DICOM.

* Sem motor: cálculo da lista (só nós habilitados com envio), plano que só mexe nas entradas ``vyx-``.
* Com o binário REAL do Orthanc (``VYONIX_TEST_ORTHANC_BIN``, no CI da plataforma): um Orthanc **próprio do teste**
  com ``DicomAlwaysAllowStore=false`` e ``DicomCheckModalityHost=true``; a lista é aplicada pela API REST; o
  equipamento autorizado grava, o não autorizado (AE desconhecido ou IP diferente) é recusado e nada é gravado; ao
  desabilitar o nó, ele passa a ser recusado. A instalação do DEPLOY e o Orthanc do CI não são alterados.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N

from tests_platform.pacs_support import make_dicom, uid
from tests_platform.test_pacs_engine import BIN, free_port


def node(ae, host="127.0.0.1", port=11112, *, store=True, receive=False, enabled=True):
    return N(ae_title=ae, host=host, port=port, can_store=store, can_receive=receive, enabled=enabled)


class FakeOrthanc:
    def __init__(self, mods):
        self.mods, self.calls = dict(mods), []

    def _req(self, method, path, **kw):
        self.calls.append((method, path))
        name = path.split("/")[2] if path.count("/") >= 2 else None
        if method == "PUT":
            self.mods[name] = kw["json"]
        elif method == "DELETE":
            self.mods.pop(name)
        return N(json=lambda: self.mods, raise_for_status=lambda: None)


class Plan(unittest.TestCase):
    def test_only_enabled_store_nodes_and_only_vyx_entries_change(self):
        from vyonix.pacs import association as a
        nodes = [node("CT_SALA1"), node("MR 2", host=None, port=None), node("WS_QUERY", store=False),
                 node("OFF", enabled=False), node("DEST", store=False, receive=True)]
        want = a.desired(nodes)
        self.assertEqual(sorted(v["AET"] for v in want.values()), ["CT_SALA1", "DEST", "MR 2"])
        self.assertEqual(want["vyx-mr_2"]["Port"], 104)
        self.assertFalse(want["vyx-dest"]["AllowStore"])                     # destino de C-MOVE não envia ao PACS
        self.assertFalse(any(v["AllowFind"] or v["AllowMove"] or v["AllowGet"] for v in want.values()))
        fake = FakeOrthanc({"manual": {"AET": "MANUAL", "Host": "10.0.0.9", "Port": 104},
                            "vyx-old": {"AET": "OLD", "Host": "10.0.0.8", "Port": 104},
                            "vyx-ct_sala1": dict(want["vyx-ct_sala1"])})
        r = a.sync(fake, nodes, dry_run=True)
        self.assertEqual((r["put"], r["delete"], r["untouched"]), (["vyx-dest", "vyx-mr_2"], ["vyx-old"], ["manual"]))
        self.assertEqual([c for c in fake.calls if c[0] != "GET"], [])          # simulação não altera nada
        a.sync(fake, nodes)
        self.assertEqual(sorted(fake.mods), ["manual", "vyx-ct_sala1", "vyx-dest", "vyx-mr_2"])
        self.assertEqual(fake.mods["manual"]["AET"], "MANUAL")                   # entrada manual intacta


def c_store(port: int, calling: str, data: bytes) -> tuple[bool, int | None]:
    """(associação aceita?, status do C-STORE)."""
    from pydicom import dcmread
    from pynetdicom import AE
    ds = dcmread(io.BytesIO(data))
    ae = AE(ae_title=calling)
    ae.acse_timeout = ae.network_timeout = 10
    ae.add_requested_context(ds.SOPClassUID, ds.file_meta.TransferSyntaxUID)
    assoc = ae.associate("127.0.0.1", port, ae_title="VYONIX_PACS")
    if not assoc.is_established:
        return False, None
    try:
        st = assoc.send_c_store(ds)
        return True, (st.Status if st else None)
    finally:
        assoc.release()


@unittest.skipUnless(BIN and Path(BIN).exists(), "VYONIX_TEST_ORTHANC_BIN não definida (binário do Orthanc).")
class RealEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-assoc-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.http, self.dicom = free_port(), free_port()
        st = str(self.tmp / "storage")
        self.cfg = self.tmp / "orthanc.json"
        self.cfg.write_text(json.dumps({
            "Name": "VYONIX teste BLK-15", "StorageDirectory": st, "IndexDirectory": st, "HttpPort": self.http,
            "RemoteAccessAllowed": False, "AuthenticationEnabled": True, "RegisteredUsers": {"vyonix": "s3nha-teste"},
            "DicomAet": "VYONIX_PACS", "DicomPort": self.dicom, "DicomCheckCalledAet": True, "Plugins": [],
            "DicomAlwaysAllowStore": False, "DicomAlwaysAllowEcho": False, "DicomCheckModalityHost": True,
            "DicomAlwaysAllowFind": False, "DicomAlwaysAllowGet": False, "DicomAlwaysAllowMove": False,
            "DicomModalities": {}, "DicomModalitiesInDatabase": False}), encoding="utf-8")
        from vyonix.pacs.engine_host import EngineProcess
        from vyonix.pacs.orthanc import OrthancBackend
        self.engine = EngineProcess(Path(BIN), self.cfg, log_file=self.tmp / "orthanc.log")
        self.addCleanup(self.engine.stop)
        self.engine.start()
        self.b = OrthancBackend(f"http://127.0.0.1:{self.http}", username="vyonix", password="s3nha-teste")
        self.addCleanup(self.b.close)

    def count(self) -> int:
        return len(self.b._req("GET", "/instances").json())

    def refused(self, calling: str, data: bytes) -> bool:
        ok, status = c_store(self.dicom, calling, data)
        return (not ok) or status != 0x0000

    def test_authorized_stores_unauthorized_refused(self):
        from vyonix.pacs import association as a
        nodes = [node("MOD_OK"), node("MOD_OUTRO_IP", host="10.255.255.1"), node("WS_QUERY", store=False)]
        r = a.sync(self.b, nodes)
        self.assertEqual(r["authorized"], ["MOD_OK", "MOD_OUTRO_IP"])
        ok, status = c_store(self.dicom, "MOD_OK", make_dicom(study=uid(91), series=uid(91, 1), sop=uid(91, 1, 1)))
        self.assertTrue(ok)
        self.assertEqual(status, 0x0000)
        self.assertEqual(self.count(), 1)
        for calling in ("MOD_DESCONHECIDO", "MOD_OUTRO_IP", "WS_QUERY"):          # AE fora da lista; IP diferente; sem envio
            self.assertTrue(self.refused(calling, make_dicom(study=uid(92), series=uid(92, 1), sop=uid(92, 1, 1))),
                            calling)
        self.assertEqual(self.count(), 1)                                         # nada gravado dos recusados
        nodes[0].enabled = False                                                  # desabilitar o nó → passa a ser recusado
        r = a.sync(self.b, nodes)
        self.assertIn("vyx-mod_ok", r["delete"])
        self.assertTrue(self.refused("MOD_OK", make_dicom(study=uid(93), series=uid(93, 1), sop=uid(93, 1, 1))))
        self.assertEqual(self.count(), 1)


if __name__ == "__main__":
    unittest.main()
