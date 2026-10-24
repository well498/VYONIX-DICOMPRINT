"""PACS no modo cloud: isolamento entre organizações num motor DICOM compartilhado.

Cenários de ataque e de erro, com a plataforma real (API HTTPS em processo, PostgreSQL com row level security,
licenciamento real) e o motor DUBLÊ DE TESTE ``MemoryBackend`` (comportamento do Orthanc reproduzido: identificador
derivado de PatientID + UIDs, ``AlreadyStored`` sem sobrescrever, registro de mudanças e ``CalledAET``):

1. acesso cruzado pela API (pesquisa, recuperação, metadados, frames, qualidade, abertura) e pelo banco (SQL direto);
2. AE Title desconhecido, AE com espaços de preenchimento DICOM, chegada por outro meio que não o DICOM;
3. associação incorreta: imagem de um paciente enviada ao AE de outra organização; mesmos UIDs com conteúdos
   diferentes em duas organizações; reenvio para o AE da outra organização; rota removida e reassumida;
4. gestão de rotas: uma organização não vê, não remove e não grava rota em nome de outra.
"""

from __future__ import annotations

import secrets
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from tests_platform.pacs_support import MemoryBackend, make_dicom, uid
from tests_platform.support import ADMIN_PW, new_org, require_db

DW = "/api/v1/pacs/dicomweb"


def setUpModule():
    global db
    db = require_db()


class CloudIsolation(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from tests.licensing_support import Computer, make_manager
        from tests_platform.test_licensing import Base
        from vyonix.api.app import create_app
        from vyonix.config import Config
        from vyonix.context import build
        from vyonix.modules import registry
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-cloud-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        sfx = secrets.token_hex(3)
        self.code_a, self.code_b = f"cloud-a-{sfx}", f"cloud-b-{sfx}"
        self.ta, self.tb = new_org(db, self.code_a), new_org(db, self.code_b)
        self.AE_A, self.AE_B = f"AE_A_{sfx.upper()}", f"AE_B_{sfx.upper()}"
        self.b = MemoryBackend()
        self.b.name = f"mem-{sfx}"
        pc = Computer()
        self.lm, admin, keys, cid = make_manager(self.tmp / "lm", clock=lambda: pc.clock.wall)
        self.addCleanup(self.lm.close)
        h = Base.__new__(Base)
        h.keys, h.lm, h.admin, h.cid = keys, self.lm, admin, cid
        self.lic = h.licensing(pc)
        h.lic = self.lic
        doc = h.issue("annual", modules={"core": {"kind": "contract"}, "pacs": {"kind": "contract"}})["document"]
        for t in (self.ta, self.tb):
            with db.session(t) as s:
                self.lic.install(s, doc, actor="admin")
                registry.enable(s, "pacs", actor="admin", license_check=self.lic.module_ok)
        cfg = Config(data_dir=self.tmp / "data", mode="cloud")
        self.plat = build(cfg, licensing=self.lic, db=db)
        self.plat.options["pacs_backend"] = self.b
        self.app = create_app(self.plat, cookie_secure=False)
        self.TestClient = TestClient
        from vyonix.pacs import service as pacs
        self.pacs = pacs
        with db.session(self.ta) as s:
            pacs.add_route(s, self.AE_A, actor="admin")
        with db.session(self.tb) as s:
            pacs.add_route(s, self.AE_B, actor="admin")

    # ------------------------------------------------------------------ apoio
    def client(self, org: str):
        c = self.TestClient(self.app)
        r = c.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW, "organization": org})
        self.assertEqual(r.status_code, 200, r.text)
        c.headers["X-CSRF-Token"] = r.json()["csrf"]
        return c

    def sync(self):
        return self.pacs.cloud_sync(db, self.b, allowed=lambda s: True)

    def studies(self, tid) -> set[str]:
        with db.session(tid) as s:
            return {x["0020000D"]["Value"][0] for x in self.pacs.search_studies(s, {})}

    def inst(self, study, series, sop, **kw):
        return make_dicom(study=study, series=series, sop=sop, **kw)

    # ------------------------------------------------------------------ 1. acesso cruzado
    def test_cross_access_through_api_is_refused(self):
        self.b.receive_cstore(self.inst(uid(1), uid(1, 1), uid(1, 1, 1), patient_id="PA-1"), called_aet=self.AE_A)
        self.assertEqual(self.sync()["indexed"], 1)
        ca, cb = self.client(self.code_a), self.client(self.code_b)
        st, se, sop = uid(1), uid(1, 1), uid(1, 1, 1)
        self.assertEqual(ca.get(f"{DW}/studies").status_code, 200)
        self.assertEqual(cb.get(f"{DW}/studies").status_code, 204)                         # B não vê nada
        self.assertEqual(cb.get(f"{DW}/studies", params={"StudyInstanceUID": st}).status_code, 204)
        self.assertEqual(cb.get(f"{DW}/studies", params={"PatientID": "PA-1"}).status_code, 204)
        for path in (f"/studies/{st}", f"/studies/{st}/metadata", f"/studies/{st}/series",
                     f"/studies/{st}/series/{se}/metadata", f"/studies/{st}/series/{se}/instances/{sop}",
                     f"/studies/{st}/series/{se}/instances/{sop}/frames/1"):
            self.assertEqual(cb.get(DW + path).status_code, 404, path)                    # nem existência revelada
            self.assertEqual(ca.get(DW + path).status_code, 200, path)
        self.assertEqual(cb.get(f"/api/v1/pacs/studies/{st}/quality").status_code, 404)
        self.assertEqual(cb.get("/api/v1/pacs/status").json()["index"]["instances"], 0)
        from vyonix.audit import service as audit
        with db.session(self.tb) as s:
            self.assertEqual(audit.query(s, action="pacs.study.open"), [])                 # B não "abriu" nada

    def test_cross_access_through_sql_is_blocked_by_rls(self):
        from sqlalchemy import func, select, text
        from sqlalchemy.exc import DBAPIError
        from vyonix.pacs.models import PacsAeRoute, PacsInstance, PacsStudy
        self.b.receive_cstore(self.inst(uid(2), uid(2, 1), uid(2, 1, 1)), called_aet=self.AE_A)
        self.sync()
        with db.session(self.tb) as s:
            for model in (PacsStudy, PacsInstance):
                self.assertEqual(s.execute(select(func.count()).select_from(model)).scalar(), 0, model.__name__)
            self.assertEqual(s.execute(text("SELECT count(*) FROM pacs.ae_routes")).scalar(), 1)   # só a própria
        # gravar uma rota em nome de A a partir da sessão de B: recusado pela política (WITH CHECK)
        with self.assertRaises(DBAPIError):
            with db.session(self.tb) as s:
                s.add(PacsAeRoute(called_aet=f"X_{secrets.token_hex(3).upper()}", created_by="b",
                                  tenant_id=self.ta))
                s.flush()
        # mudar o dono de uma instância de A para B: a sessão de B nem enxerga a linha
        with db.session(self.tb) as s:
            n = s.execute(text("UPDATE pacs.instances SET tenant_id = :b"), {"b": str(self.tb)}).rowcount
            self.assertEqual(n, 0)
        self.assertEqual(self.studies(self.ta), {uid(2)})

    # ------------------------------------------------------------------ 2. AE desconhecido e origem
    def test_unknown_padded_and_non_dicom_arrivals(self):
        self.b.receive_cstore(self.inst(uid(3), uid(3, 1), uid(3, 1, 1)), called_aet="DESCONHECIDO")
        self.b.receive_cstore(self.inst(uid(4), uid(4, 1), uid(4, 1, 1)), called_aet=None)
        self.b.receive_cstore(self.inst(uid(5), uid(5, 1), uid(5, 1, 1)), called_aet=self.AE_A.lower() + "  ")
        bid = self.b.receive_cstore(self.inst(uid(6), uid(6, 1), uid(6, 1, 1)), called_aet=self.AE_B)
        self.b.meta[bid]["origin"] = "RestApi"                     # mesmo com AE de B, não veio por DICOM
        out = self.sync()
        self.assertEqual((out["indexed"], out["quarantined"]), (1, 3))
        self.assertEqual(self.studies(self.ta), {uid(5)})            # AE com preenchimento e minúsculas: normalizado
        self.assertEqual(self.studies(self.tb), set())

    # ------------------------------------------------------------------ 3. associação incorreta
    def test_patient_sent_to_wrong_ae_stays_with_ae_owner_only(self):
        """O roteamento segue o AE Title chamado, nunca dados do paciente: um exame enviado por engano ao AE de B
        fica só com B (A não o vê) — a correção é operacional (reenvio ao AE certo), registrada na auditoria de B."""
        self.b.receive_cstore(self.inst(uid(7), uid(7, 1), uid(7, 1, 1), patient_id="PA-7"), called_aet=self.AE_B)
        self.sync()
        self.assertEqual((self.studies(self.ta), self.studies(self.tb)), (set(), {uid(7)}))
        from vyonix.audit import service as audit
        with db.session(self.tb) as s:
            self.assertEqual(len(audit.query(s, action="pacs.instance.store")), 1)

    def test_same_uids_different_content_in_two_orgs(self):
        a = self.inst(uid(8), uid(8, 1), uid(8, 1, 1), patient_id="PA-8", fill=1)
        b = self.inst(uid(8), uid(8, 1), uid(8, 1, 1), patient_id="PB-8", fill=9)   # outro paciente, outro conteúdo
        self.b.receive_cstore(a, called_aet=self.AE_A)
        self.b.receive_cstore(b, called_aet=self.AE_B)
        self.assertEqual(self.sync()["indexed"], 2)
        ca, cb = self.client(self.code_a), self.client(self.code_b)
        from vyonix.api.routes_pacs import parse_multipart
        for c, expected in ((ca, a), (cb, b)):
            r = c.get(f"{DW}/studies/{uid(8)}/series/{uid(8, 1)}/instances/{uid(8, 1, 1)}")
            self.assertEqual(parse_multipart(r.content, r.headers["content-type"]), [expected])

    def test_resend_to_other_org_ae_is_not_delivered_to_it(self):
        """O motor não grava de novo a mesma instância (mesmo PatientID e UIDs): o reenvio ao AE de B não gera
        entrada nova e B não recebe o exame de A."""
        data = self.inst(uid(9), uid(9, 1), uid(9, 1, 1), patient_id="PA-9")
        self.b.receive_cstore(data, called_aet=self.AE_A)
        self.sync()
        ref = self.b.store(data)                                    # mesmo arquivo chegando de novo (AE de B)
        self.assertTrue(ref.already_existed)
        self.sync()
        self.assertEqual((self.studies(self.ta), self.studies(self.tb)), ({uid(9)}, set()))

    def test_route_removed_then_claimed_by_other_org(self):
        self.b.receive_cstore(self.inst(uid(10), uid(10, 1), uid(10, 1, 1)), called_aet=self.AE_A)
        self.sync()
        with db.session(self.ta) as s:
            rid = uuid.UUID(self.pacs.routes(s)[0]["id"])
            self.pacs.remove_route(s, rid, actor="admin")
        self.b.receive_cstore(self.inst(uid(11), uid(11, 1), uid(11, 1, 1)), called_aet=self.AE_A)
        self.assertEqual(self.sync()["quarantined"], 1)               # sem dono: quarentena
        with db.session(self.tb) as s:
            self.pacs.add_route(s, self.AE_A, actor="admin")          # B assume o AE liberado
        self.b.receive_cstore(self.inst(uid(12), uid(12, 1), uid(12, 1, 1)), called_aet=self.AE_A)
        self.sync()
        self.assertEqual(self.studies(self.ta), {uid(10)})            # o que já era de A continua só de A
        self.assertEqual(self.studies(self.tb), {uid(12)})            # B recebe só o que chegou depois
        self.assertNotIn(uid(11), self.studies(self.ta) | self.studies(self.tb))   # a quarentena não é redistribuída

    # ------------------------------------------------------------------ 4. gestão de rotas
    def test_route_management_is_isolated(self):
        ca, cb = self.client(self.code_a), self.client(self.code_b)
        ra = ca.get("/api/v1/pacs/routes").json()
        self.assertEqual([r["called_aet"] for r in ra["routes"]], [self.AE_A])
        self.assertEqual(ra["mode"], "cloud")
        self.assertEqual([r["called_aet"] for r in cb.get("/api/v1/pacs/routes").json()["routes"]], [self.AE_B])
        self.assertEqual(cb.delete(f"/api/v1/pacs/routes/{ra['routes'][0]['id']}").status_code, 404)
        r = cb.post("/api/v1/pacs/routes", json={"called_aet": self.AE_A.lower()})
        self.assertEqual(r.status_code, 409)
        self.assertNotIn(self.code_a, r.text)                         # não revela a dona
        self.assertEqual(cb.post("/api/v1/pacs/sync").status_code, 422)   # ninguém "puxa" o motor no modo cloud
        self.assertEqual([r["called_aet"] for r in ca.get("/api/v1/pacs/routes").json()["routes"]], [self.AE_A])


if __name__ == "__main__":
    unittest.main()
