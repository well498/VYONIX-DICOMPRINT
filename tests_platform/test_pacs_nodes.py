"""Gestão de nós DICOM: cadastro completo do equipamento, edição auditada, isolamento entre organizações, recepção só
de equipamentos cadastrados (retenção sem exclusão, autorizar/descartar), histórico de conexões (C-STORE, associações
aceitas e recusadas no Q/R), teste de associação C-ECHO real (pynetdicom) e status do nó.

PostgreSQL real; motor DUBLÊ DE TESTE ``MemoryBackend``; dados sintéticos.
"""

from __future__ import annotations

import secrets
import shutil
import tempfile
import unittest
from pathlib import Path

from tests_platform.pacs_support import MemoryBackend, make_dicom, uid
from tests_platform.support import new_org, require_db
from tests_platform.test_pacs_qr import free_port


def setUpModule():
    global db
    db = require_db()


class Nodes(unittest.TestCase):
    def setUp(self):
        self.t = new_org(db)
        self.b = MemoryBackend()

    def add(self, ae, tid=None, **kw):
        from vyonix.pacs import nodes
        with db.session(tid or self.t) as s:
            return nodes.add(s, ae, actor="admin", **kw)

    def policy(self, value):
        from vyonix.settings import service as settings
        with db.session(self.t) as s:
            settings.put(s, "pacs", "reception", {"store_policy": value}, actor="admin")

    def sync(self):
        from vyonix.pacs import service as pacs
        with db.session(self.t) as s:
            return pacs.sync(s, self.b)

    def events(self, **kw):
        from vyonix.pacs import nodes
        with db.session(self.t) as s:
            return nodes.events(s, **kw)

    def test_full_registration_edit_audit_and_isolation(self):
        from vyonix.audit import service as audit
        from vyonix.errors import Conflict, ValidationFailed
        from vyonix.pacs import nodes
        from vyonix.tenancy import service as tenancy
        with db.session(self.t) as s:
            site = tenancy.save_site(s, name="Unidade Centro (fictícia)", actor="admin")
        other = new_org(db)
        with db.session(other) as s:
            other_site = tenancy.save_site(s, name="Unidade de outra clínica", actor="admin")
        n = self.add("tc_sala1", name="Tomógrafo sala 1", manufacturer="Fabricante Fictício", model="TC-64",
                     modality="ct", site_id=site.id, host="192.168.10.21", port=104, can_store=True, can_query=True)
        self.assertEqual((n["ae_title"], n["modality"], n["site_name"], n["status"]["code"]),
                         ("TC_SALA1", "CT", "Unidade Centro (fictícia)", "never"))
        with self.assertRaises(ValidationFailed):                     # unidade de outra organização
            self.add("RX1", site_id=other_site.id)
        with self.assertRaises(ValidationFailed):
            self.add("RX1", modality="tomografia")
        with db.session(self.t) as s:
            with self.assertRaises(Conflict):                          # versão desatualizada
                nodes.update(s, n["id"], {"port": 105}, row_version=n["row_version"] + 5, actor="admin")
            u = nodes.update(s, n["id"], {"port": 105, "enabled": False}, row_version=n["row_version"], actor="admin")
            self.assertEqual((u["port"], u["enabled"], u["status"]["code"]), (105, False, "disabled"))
            a = audit.query(s, action="pacs.node.update")[0]
            self.assertEqual(a.details["changes"]["port"], ["104", "105"])
        with db.session(other) as s:                                    # outra organização não vê o nó
            self.assertEqual(nodes.listing(s), [])
            from vyonix.errors import NotFound
            with self.assertRaises(NotFound):
                nodes.update(s, n["id"], {"port": 1}, actor="intruso")

    def test_default_policy_accepts_any_and_records_history(self):
        self.add("TC_SALA1", can_store=True, host="127.0.0.1")
        self.b.receive_cstore(make_dicom(sop=uid(1, 1, 1)), remote_aet="TC_SALA1")
        self.b.receive_cstore(make_dicom(sop=uid(1, 1, 2), instance_number=2), remote_aet="TC_SALA1")
        self.b.receive_cstore(make_dicom(study=uid(2), series=uid(2, 1), sop=uid(2, 1, 1)), remote_aet="DESCONHECIDO")
        out = self.sync()
        self.assertEqual((out["indexed"], out["held"]), (3, 0))       # padrão: comportamento homologado (aceita)
        ev = {(e["calling_ae"], e["outcome"]): e["count"] for e in self.events()}
        self.assertEqual(ev[("TC_SALA1", "accepted")], 2)              # agrupado
        self.assertEqual(ev[("DESCONHECIDO", "accepted")], 1)
        from vyonix.pacs import nodes
        with db.session(self.t) as s:
            n = nodes.listing(s)[0]
        self.assertEqual(n["status"]["code"], "ok")
        self.assertIsNotNone(n["last_seen_at"])

    def test_registered_only_holds_unknown_and_admin_decides(self):
        from vyonix.errors import ValidationFailed
        from vyonix.pacs import nodes
        from vyonix.pacs import service as pacs
        self.policy("registered")
        self.add("TC_SALA1", can_store=True, host="127.0.0.1")
        self.add("SO_CONSULTA", can_query=True)                        # cadastrado, mas sem "enviar estudos"
        self.add("DESLIGADO", can_store=True, enabled=False)
        self.add("OUTRO_IP", can_store=True, host="10.9.9.9")
        self.b.receive_cstore(make_dicom(sop=uid(1, 1, 1)), remote_aet="TC_SALA1")
        bad = {}
        for i, ae in enumerate(("INTRUSO", "SO_CONSULTA", "DESLIGADO", "OUTRO_IP"), start=2):
            bad[ae] = self.b.receive_cstore(make_dicom(study=uid(i), series=uid(i, 1), sop=uid(i, 1, 1),
                                                       patient_id=f"P{i}"), remote_aet=ae)
        out = self.sync()
        self.assertEqual((out["indexed"], out["held"]), (1, 4))
        with db.session(self.t) as s:
            self.assertEqual([x["0020000D"]["Value"][0] for x in pacs.search_studies(s, {})], [uid(1)])  # só o autorizado
            h = nodes.holds(s)
        reasons = {g["remote_aet"]: g["reason"] for g in h["groups"]}
        self.assertEqual(reasons, {"INTRUSO": "AE Title não cadastrado",
                                   "SO_CONSULTA": "Equipamento sem permissão para enviar estudos",
                                   "DESLIGADO": "Equipamento desativado",
                                   "OUTRO_IP": "Endereço de origem diferente do cadastrado"})
        self.assertEqual(h["total"], 4)
        self.assertEqual(len(self.b.files), 5)                         # nada foi excluído do motor
        self.assertEqual({e["calling_ae"] for e in self.events(outcome="problems")},
                         {"INTRUSO", "SO_CONSULTA", "DESLIGADO", "OUTRO_IP"})
        with db.session(self.t) as s:
            with self.assertRaises(ValidationFailed):                  # descarte exige motivo
                nodes.decide_holds(s, self.b, remote_aet="INTRUSO", decision="discard", actor="admin")
            r = nodes.decide_holds(s, self.b, remote_aet="SO_CONSULTA", decision="release", actor="admin")
            self.assertEqual(r["indexed"], 1)
            r = nodes.decide_holds(s, self.b, remote_aet="INTRUSO", decision="discard",
                                   note="Equipamento de teste não autorizado", actor="admin")
            self.assertEqual(r["discarded"], 1)
            self.assertEqual(len(pacs.search_studies(s, {})), 2)
            self.assertEqual(nodes.holds(s)["total"], 2)
            from vyonix.audit import service as audit
            self.assertEqual(len(audit.query(s, action="pacs.hold.discard")), 1)
        self.assertIn(bad["INTRUSO"], self.b.deleted)
        # equipamento autorizado depois do cadastro: as próximas recepções entram direto
        with db.session(self.t) as s:
            nodes.add(s, "INTRUSO", can_store=True, actor="admin")
        self.b.receive_cstore(make_dicom(study=uid(9), series=uid(9, 1), sop=uid(9, 1, 1), patient_id="P9"),
                              remote_aet="INTRUSO")
        self.assertEqual(self.sync()["indexed"], 1)

    def test_rest_uploads_are_not_subject_to_reception_policy(self):
        self.policy("registered")
        self.b.store(make_dicom())                                     # STOW/REST: autorização por usuário, não AE
        self.assertEqual(self.sync()["held"], 0)


class Echo(unittest.TestCase):
    def setUp(self):
        self.t = new_org(db)

    def test_echo_success_failure_and_status(self):
        from pynetdicom import AE, evt
        from pynetdicom.sop_class import Verification
        from vyonix.errors import ValidationFailed
        from vyonix.pacs import nodes
        port = free_port()
        scp = AE(ae_title="MODALIDADE_SIM")
        scp.add_supported_context(Verification)
        server = scp.start_server(("127.0.0.1", port), block=False, evt_handlers=[(evt.EVT_C_ECHO, lambda e: 0)])
        self.addCleanup(server.shutdown)
        with db.session(self.t) as s:
            ok = nodes.add(s, "MODALIDADE_SIM", host="127.0.0.1", port=port, can_receive=True, actor="admin")
            dead = nodes.add(s, "SEM_RESPOSTA", host="127.0.0.1", port=free_port(), can_receive=True, actor="admin")
            noaddr = nodes.add(s, "SEM_ENDERECO", can_query=True, actor="admin")
        with db.session(self.t) as s:
            r = nodes.echo(s, ok["id"], calling_ae="VYONIX_QR", actor="admin", timeout=5)
            self.assertTrue(r["ok"], r["detail"])
            self.assertEqual(r["node"]["status"]["code"], "ok")
            r = nodes.echo(s, dead["id"], calling_ae="VYONIX_QR", actor="admin", timeout=3)
            self.assertFalse(r["ok"])
            self.assertEqual(r["node"]["status"]["code"], "error")
            self.assertTrue(r["node"]["last_error"])
            with self.assertRaises(ValidationFailed):
                nodes.echo(s, noaddr["id"], calling_ae="VYONIX_QR", actor="admin")
            ev = nodes.events(s, node_id=dead["id"])
            self.assertEqual((ev[0]["service"], ev[0]["outcome"], ev[0]["direction"]), ("echo", "failed", "out"))
            from vyonix.audit import service as audit
            self.assertEqual(len(audit.query(s, action="pacs.node.echo")), 2)


class QRHistory(unittest.TestCase):
    """Associações ao Q/R do Core aceitas e recusadas entram no histórico, com o motivo."""

    def setUp(self):
        from tests.licensing_support import Computer
        from tests_platform.test_licensing import Base
        from vyonix.config import Config
        from vyonix.context import build
        from vyonix.pacs.dimse_qr import QRServer
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-nodes-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.code = f"nos-{secrets.token_hex(3)}"
        self.t = new_org(db, self.code)
        h = Base.__new__(Base)
        h.keys = {}
        cfg = Config(data_dir=self.tmp / "data", default_organization=self.code, mode="edge")
        plat = build(cfg, licensing=h.licensing(Computer()), db=db)
        self.port = free_port()
        self.qr = QRServer(plat, port=self.port, ae_title="VYONIX_QR", bind="127.0.0.1", backend=MemoryBackend())
        self.qr.start()
        self.addCleanup(self.qr.stop)

    def assoc(self, calling, called="VYONIX_QR"):
        from pynetdicom import AE
        from pynetdicom.sop_class import Verification
        ae = AE(ae_title=calling)
        ae.add_requested_context(Verification)
        a = ae.associate("127.0.0.1", self.port, ae_title=called)
        ok = a.is_established
        if ok:
            a.release()
        return ok

    def test_accepted_and_rejected_associations_recorded(self):
        from vyonix.pacs import nodes
        with db.session(self.t) as s:
            nodes.add(s, "ESTACAO_1", host="127.0.0.1", can_query=True, actor="admin")
            nodes.add(s, "SO_ENVIA", can_store=True, can_query=False, actor="admin")
        self.assertTrue(self.assoc("ESTACAO_1"))
        self.assertFalse(self.assoc("INTRUSA"))
        self.assertFalse(self.assoc("SO_ENVIA"))
        self.assertFalse(self.assoc("ESTACAO_1", called="AE_ERRADO"))
        with db.session(self.t) as s:
            ev = {(e["calling_ae"], e["outcome"], e["called_ae"]): e["detail"] for e in nodes.events(s)}
            st = {n["ae_title"]: n for n in nodes.listing(s)}
        self.assertIn(("ESTACAO_1", "accepted", "VYONIX_QR"), ev)
        self.assertEqual(ev[("INTRUSA", "rejected", "VYONIX_QR")], "AE Title não cadastrado")
        self.assertEqual(ev[("SO_ENVIA", "rejected", "VYONIX_QR")], "Equipamento sem permissão para consultar")
        self.assertIn("AE Title chamado desconhecido", ev[("ESTACAO_1", "rejected", "AE_ERRADO")])
        self.assertEqual(st["ESTACAO_1"]["status"]["code"], "ok")
        self.assertEqual(st["SO_ENVIA"]["last_error"], "Equipamento sem permissão para consultar")


if __name__ == "__main__":
    unittest.main()
