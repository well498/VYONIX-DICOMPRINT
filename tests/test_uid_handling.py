"""BKL-10 — UIDs DICOM no VYONIX DICOM Print: testes de caracterização (comportamento a preservar).

Independentes da raiz usada na geração: valem antes e depois da correção do BKL-10, e são a regressão dela.
Dados sintéticos; o equipamento é simulado com o pynetdicom (SCU) contra o Storage SCP e o Print SCP reais em
127.0.0.1; impressão na impressora virtual de PDF (nenhum teste físico é declarado aqui).

Cobertura: (1) recepção com UIDs válidos; (2) preservação dos UIDs originais; (3) geração de UIDs só nos objetos
criados pelo próprio Print; (4) unicidade; (5) UIDs inválidos; (6) recepção repetida; (7) regras de impressão;
(9) operação sem rede externa. A compatibilidade com o PACS (8) está em ``tests_platform`` (o Print não encaminha
objetos ao PACS nesta versão).
"""

import socket
import unittest

from tests.helpers import TempDirTestCase

try:
    import numpy as np  # noqa: F401
    import pynetdicom  # noqa: F401
    HAS = True
except ImportError:
    HAS = False

SC = "1.2.840.10008.5.1.4.1.1.7"
CT = "1.2.840.10008.5.1.4.1.1.2"


def is_valid_dicom_uid(u: str) -> bool:
    """PS3.5 §9.1: até 64 caracteres, componentes numéricos separados por ponto, sem zero à esquerda."""
    if not u or len(u) > 64:
        return False
    parts = u.split(".")
    return all(p.isdigit() and (p == "0" or not p.startswith("0")) for p in parts)


@unittest.skipUnless(HAS, "numpy/pynetdicom não instalados")
class ReceivedUids(TempDirTestCase):
    """Objetos recebidos das modalidades: UIDs nunca alterados; inválidos recusados; repetição tratada."""

    def setUp(self):
        super().setUp()
        from app.bootstrap import bootstrap
        from app.core.contracts import AssociationPeer
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        self.peer = AssociationPeer("CT_TESTE", "VYONIX", "127.0.0.1", 11112)

    def tearDown(self):
        self.ctx.close()
        super().tearDown()

    def ct(self, name="a.dcm", **kw):
        from tests.dicom_helpers import make_ct
        return make_ct(self.tmp / name, **kw).read_bytes()

    def store(self, data):
        return self.ctx.store.store(data, self.peer, None, max_bytes=10 ** 8)

    def test_valid_uids_preserved_byte_for_byte(self):
        study, series, sop = "1.2.3.4.5.6", "1.2.3.4.5.6.7", "1.2.3.4.5.6.7.8"
        data = self.ct(study_uid=study, series_uid=series, sop_uid=sop)
        out = self.store(data)
        self.assertIsNotNone(out.instance, out.message)
        self.assertEqual((out.instance.study_uid, out.instance.series_uid, out.instance.sop_instance_uid,
                          out.instance.sop_class_uid), (study, series, sop, CT))
        self.assertEqual(out.instance.file_path.read_bytes(), data)          # arquivo idêntico ao recebido
        from pydicom import dcmread
        ds = dcmread(out.instance.file_path)
        self.assertEqual((ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.SOPInstanceUID, ds.SOPClassUID),
                         (study, series, sop, CT))

    def test_invalid_uids_refused_nothing_stored(self):
        from app.dicom.storage import STATUS_DATASET_MISMATCH
        cases = {"letras": dict(sop_uid="1.2.3.abc"), "longo": dict(sop_uid="1." + "2" * 70),
                 "estudo vazio": dict(study_uid="")}
        for name, kw in cases.items():
            out = self.store(self.ct(name=f"{name}.dcm", **kw))
            self.assertEqual(out.status, STATUS_DATASET_MISMATCH, name)
            self.assertIsNone(out.instance, name)
        n = self.ctx.db.connection().execute("SELECT COUNT(*) FROM instances").fetchone()[0]
        self.assertEqual(n, 0)

    def test_leading_zero_component_is_tolerated(self):
        # Fora da PS3.5 §9.1, mas emitido por equipamentos antigos: recusar quebraria a impressão. Comportamento
        # atual (e proposto no BKL-10): aceitar e guardar sem alterar.
        out = self.store(self.ct(name="z.dcm", sop_uid="1.2.03.4"))
        self.assertIsNotNone(out.instance, out.message)
        self.assertEqual(out.instance.sop_instance_uid, "1.2.03.4")

    def test_repeated_object_and_uid_conflict(self):
        data = self.ct(sop_uid="1.2.3.9.1", value=100)
        first = self.store(data)
        again = self.store(data)
        self.assertTrue(again.duplicate)
        self.assertFalse(again.conflict)
        other = self.ct(name="b.dcm", sop_uid="1.2.3.9.1", value=200)        # mesmo SOP UID, outro conteúdo
        conflict = self.store(other)
        self.assertTrue(conflict.conflict)
        self.assertEqual(first.instance.file_path.read_bytes(), data)       # original mantido
        n = self.ctx.db.connection().execute("SELECT COUNT(*) FROM instances").fetchone()[0]
        self.assertEqual(n, 1)

    def test_storage_scp_end_to_end_keeps_modality_uids(self):
        from app.dicom import scu
        from tests.dicom_helpers import free_port, make_ct
        port = free_port()
        self.ctx.settings.update({"dicom.storage.bind_address": "127.0.0.1", "dicom.storage.port": port}, actor="t")
        self.ctx.devices.create({"name": "CT sala 1", "ae_title": "CT_TESTE", "modality": "CT",
                                 "ip_address": "127.0.0.1"}, actor="t", authorized=True)
        self.ctx.storage_scp.start()
        f = make_ct(self.tmp / "e2e.dcm", study_uid="1.2.3.77", series_uid="1.2.3.77.1", sop_uid="1.2.3.77.1.1")
        self.assertEqual(scu.store_files("127.0.0.1", port, "VYONIX", [f], calling_ae="CT_TESTE"), [0])
        row = self.ctx.db.connection().execute(
            "SELECT study_uid, series_uid, sop_instance_uid FROM instances").fetchone()
        self.assertEqual(tuple(row), ("1.2.3.77", "1.2.3.77.1", "1.2.3.77.1.1"))


@unittest.skipUnless(HAS, "numpy/pynetdicom não instalados")
class PrintGeneratedUids(TempDirTestCase):
    """UIDs criados pelo próprio Print (objetos novos): válidos, únicos, separados dos UIDs das classes SOP."""

    def _harness(self):
        from tests.test_print_scp import PrintSCPTest
        h = PrintSCPTest("test_printer_status_and_full_film_to_pdf")
        h.setUp()
        self.addCleanup(h.tearDown)
        return h

    def test_generated_uids_valid_unique_and_sop_classes_untouched(self):
        from tests.test_print_scp import FILM_BOX
        h = self._harness()
        uids_seen = []
        for _assoc_n in range(3):                                    # três associações, um filme cada
            assoc = h.associate()
            st, fb_uid, boxes = h.film(assoc)
            self.assertEqual(st.Status, 0x0000)
            uids_seen += [b.ReferencedSOPInstanceUID for b in boxes]           # Image Box: criados pelo SCP
            st, _ = assoc.send_n_action(None, 1, FILM_BOX, fb_uid, meta_uid=h.meta)
            self.assertEqual(st.Status, 0x0000)
            assoc.release()
        import time
        end = time.monotonic() + 30
        while time.monotonic() < end and h.ctx.db.connection().execute(
                "SELECT COUNT(*) FROM instances WHERE source_ae = 'CR_PRINT'").fetchone()[0] < 9:
            time.sleep(0.1)
        rows = h.ctx.db.connection().execute(
            "SELECT sop_instance_uid, sop_class_uid, study_uid, series_uid FROM instances "
            "WHERE source_ae = 'CR_PRINT' ORDER BY id").fetchall()
        self.assertEqual(len(rows), 9)                               # 3 imagens × 3 filmes
        sops = [r[0] for r in rows]
        self.assertTrue(all(r[1] == SC for r in rows))               # classe SOP padronizada, não gerada
        all_generated = sops + [r[2] for r in rows] + [r[3] for r in rows] + uids_seen
        for u in all_generated:
            self.assertTrue(is_valid_dicom_uid(u), u)
        self.assertEqual(len(set(sops)), len(sops))                  # SOP Instance UIDs únicos
        self.assertEqual(len(set(uids_seen)), len(uids_seen))        # Image Box UIDs únicos
        studies = [r[2] for r in rows]
        series = [r[3] for r in rows]
        self.assertEqual(len(set(studies)), 3)                       # um estudo por associação
        self.assertEqual(len(set(series)), 3)                        # uma série por filme
        self.assertFalse(set(studies) & set(series))
        self.assertFalse(set(sops) & set(studies) | set(sops) & set(series))
        jobs = h.ctx.jobs.list()
        self.assertEqual(len(jobs), 3)
        for j in jobs:                                               # regras de impressão inalteradas
            self.assertEqual((j.source_type, j.settings["layout"], j.copies), ("dicom_print", "2x2", 2))

    def test_scu_provided_instance_uids_are_kept(self):
        from pydicom.dataset import Dataset
        from tests.test_print_scp import FILM_SESSION
        h = self._harness()
        assoc = h.associate()
        fs = Dataset()
        fs.NumberOfCopies = 1
        st, rsp = assoc.send_n_create(fs, FILM_SESSION, "1.2.3.4.555", meta_uid=h.meta)
        self.assertEqual(st.Status, 0x0000)
        self.assertEqual(st.get("AffectedSOPInstanceUID", "1.2.3.4.555"), "1.2.3.4.555")
        assoc.release()

    def test_scp_generator_uniqueness(self):
        from app.dicom.print_model import _uid
        many = [_uid() for _ in range(20000)]
        self.assertEqual(len(set(many)), len(many))
        self.assertTrue(all(is_valid_dicom_uid(u) for u in many))


@unittest.skipUnless(HAS, "numpy/pynetdicom não instalados")
class Offline(TempDirTestCase):
    """Recepção, geração de UIDs e impressão sem nenhuma resolução de nome nem conexão externa."""

    def test_print_flow_without_external_network(self):
        real_getaddrinfo, real_connect = socket.getaddrinfo, socket.socket.connect
        external = []

        local = {"127.0.0.1", "localhost", "0.0.0.0", "", None, socket.gethostname()}

        def guarded_getaddrinfo(host, *a, **kw):
            if host not in local:
                external.append(host)
                raise OSError("rede externa bloqueada no teste")
            return real_getaddrinfo(host, *a, **kw)

        def guarded_connect(self_sock, addr, *a, **kw):
            # UDP "connect" (app/utils/net.py) só escolhe a interface local e não envia pacotes: permitido
            if (self_sock.type == socket.SOCK_STREAM and isinstance(addr, tuple)
                    and addr[0] not in ("127.0.0.1", "localhost", "::1")):
                external.append(addr[0])
                raise OSError("rede externa bloqueada no teste")
            return real_connect(self_sock, addr, *a, **kw)

        socket.getaddrinfo, socket.socket.connect = guarded_getaddrinfo, guarded_connect
        try:
            from tests.test_print_scp import FILM_BOX, PrintSCPTest
            h = PrintSCPTest("test_printer_status_and_full_film_to_pdf")
            h.setUp()
            try:
                assoc = h.associate()
                st, fb_uid, _ = h.film(assoc)
                st, _ = assoc.send_n_action(None, 1, FILM_BOX, fb_uid, meta_uid=h.meta)
                self.assertEqual(st.Status, 0x0000)
                assoc.release()
                job = h.wait_job(h.ctx.jobs.list()[0].id)
                self.assertEqual(job.state.value, "completed", job.state_reason)
            finally:
                h.tearDown()
        finally:
            socket.getaddrinfo, socket.socket.connect = real_getaddrinfo, real_connect
        self.assertEqual(external, [])


if __name__ == "__main__":
    unittest.main()
