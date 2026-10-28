"""Central de Exames — preparação técnica do estudo: recepção (equipamento de origem, imagens, recepção em
andamento), fila com etapas e filtros, checklist (obrigatórios da instituição + verificações fixas), anexos
(documento, foto, áudio; validados, cifrados, acesso só autenticado), comentários com não lidos, suspeitas técnicas,
prioridade com permissão, duplicidade, encaminhamento à fila de laudos com distribuição (fixa e equilibrada),
reserva do médico com conflito e expiração, devolução para correção, compartilhamento com prazo, cancelamento com
justificativa, isolamento entre instituições e auditoria. API real, PostgreSQL real, motor dublê; dados sintéticos.
"""

from __future__ import annotations

import io
import unittest
from datetime import date, timedelta

from tests_platform.pacs_support import MemoryBackend, make_dicom, uid
from tests_platform.support import new_org, require_db
from tests_platform.test_pacs import ApiBase

PW, NEW = "Senha-Teste-1234", "Senha-Nova-9876!"


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs, test_report, test_ris
    test_pacs.db = test_report.db = test_ris.db = db


def pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def jpeg() -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 200, 190)).save(b, "JPEG")
    return b.getvalue()


def webm() -> bytes:
    return b"\x1a\x45\xdf\xa3" + b"\x00" * 60                       # cabeçalho EBML (áudio sintético)


class Prep(ApiBase):
    def setUp(self):
        super().setUp()
        from vyonix.modules import registry
        doc = self.helper.issue("annual", modules={"core": {"kind": "contract"}, "pacs": {"kind": "contract"},
                                                   "ris": {"kind": "contract"}, "report": {"kind": "contract"}})
        with db.session(self.t) as s:
            self.lic.install(s, doc["document"], actor="admin")
            for m in ("pacs", "ris", "report"):
                registry.enable(s, m, actor="admin", license_check=self.lic.module_ok)
        self.admin = self.login()
        self.tec = self.user("tec1", ["tecnico"])
        self.admin.post("/api/v1/role-templates/coordenador_cdi/activate")
        self.coord = self.user("coord1", ["coordenador_cdi"])
        self.docs = {}
        for name, crm in (("Dra. Ana Sintetica", "1001"), ("Dr. Bruno Sintetico", "1002")):
            login = name.split()[1].lower()
            c = self.user(login, ["medico"])
            uid_ = next(u["id"] for u in self.admin.get("/api/v1/users").json() if u["username"] == login)
            pid = self.admin.post("/api/v1/report/physicians", json={"user_id": uid_, "full_name": name, "crm": crm,
                                                                    "crm_uf": "PB"}).json()["id"]
            self.admin.post(f"/api/v1/report/physicians/{pid}/links", json={"valid_from": "2026-01-01"})
            self.docs[login] = (c, pid, uid_)
        self.b = self.b if hasattr(self, "b") else MemoryBackend()

    def user(self, login, roles):
        r = self.admin.post("/api/v1/users", json={"username": login, "display_name": login, "password": PW,
                                                   "roles": [{"role": x} for x in roles]})
        self.assertEqual(r.status_code, 201, r.text)
        c = self.login(login, PW)
        c.post("/api/v1/auth/password", json={"current": PW, "new": NEW})
        return self.login(login, NEW)

    def study(self, n, *, patient="PREP1", accession="", stable=True, station="TC_SALA_1", images=2):
        from sqlalchemy import update
        from vyonix.clinical import service as clinical
        from vyonix.db.base import utcnow
        from vyonix.pacs import service as pacs
        from vyonix.pacs.models import PacsStudy
        with db.session(self.t) as s:
            for i in range(1, images + 1):
                pacs.ingest(s, self.b, make_dicom(study=uid(70 + n), series=uid(70 + n, 1), sop=uid(70 + n, 1, i),
                                                  instance_number=i, patient_id=patient, accession=accession,
                                                  station=station), actor="pacs-sync", via="dimse")
            p = clinical.create_patient(s, name=f"Paciente Prep {n} Sintetico", identifiers=[("DICOM", f"{patient}{n}")],
                                        actor="t") if n == 1 or not hasattr(self, "pat") else None
            if p is not None:
                self.pat = p.id
            st = clinical.register_study(s, study_instance_uid=uid(70 + n), modality="CT", accession=accession or None,
                                         study_date=date(2026, 10, 28), actor="t")
            st.patient_id = self.pat
            if stable:
                s.execute(update(PacsStudy).where(PacsStudy.study_uid == uid(70 + n))
                          .values(last_received_at=utcnow() - timedelta(minutes=10)))
            return str(st.id)

    def test_preparation_flow(self):
        sid = self.study(1)
        u = f"/api/v1/ris/prep/{sid}"
        q = self.tec.get("/api/v1/ris/prep", params={"station": "TC_SALA_1"}).json()
        item = next(x for x in q["items"] if x["study_id"] == sid)
        self.assertEqual((item["stage"], item["images"], item["station"]), ("received", 2, "TC_SALA_1"))
        self.assertEqual(self.tec.get("/api/v1/ris/prep", params={"station": "OUTRO"}).json()["items"], [])
        d = self.tec.get(u).json()
        self.assertEqual(d["stage"], "received")
        self.assertTrue(all(c["ok"] for c in d["system_checks"]), d["system_checks"])
        # encaminhar sem o checklist obrigatório: recusado com o que falta
        r = self.tec.post(u + "/forward")
        self.assertEqual(r.status_code, 422)
        self.assertIn("Identificação do paciente conferida", r.json()["details"]["missing"])
        for code in ("patient_identity", "procedure", "quality"):
            self.assertEqual(self.tec.post(u + "/check", json={"code": code}).status_code, 200)
        self.assertEqual(self.tec.post(u + "/check", json={"code": "inexistente"}).status_code, 422)
        # anexos: documento, foto, áudio; tipos inválidos recusados; download protegido
        ok = [("document", pdf(), "pedido.pdf"), ("photo", jpeg(), "pedido-foto.jpg"), ("audio", webm(), "obs.webm")]
        ids = []
        for kind, data, name in ok:
            r = self.tec.post(u + f"/attachments?kind={kind}&filename={name}", content=data)
            self.assertEqual(r.status_code, 201, r.text)
            ids.append(r.json()["id"])
        for kind, data in (("document", b"<html><script>alert(1)</script>"), ("photo", pdf()), ("audio", jpeg()),
                           ("document", b"")):
            self.assertEqual(self.tec.post(u + f"/attachments?kind={kind}", content=data).status_code, 422)
        r = self.tec.get(f"/api/v1/ris/prep/attachments/{ids[0]}")
        self.assertEqual((r.status_code, r.content[:5]), (200, b"%PDF-"))
        self.assertIn("no-store", r.headers["cache-control"])
        self.assertIn("sandbox", r.headers["content-security-policy"])
        from vyonix.ris.models import ExamAttachment
        with db.session(self.t) as s:
            self.assertNotIn(b"%PDF", s.get(ExamAttachment, __import__("uuid").UUID(ids[0])).ciphertext)
        # comentários com não lidos para quem não escreveu
        self.assertEqual(self.tec.post(u + "/comments", json={"text": "Paciente com prótese (sintético)."}).status_code,
                         201)
        ana = self.docs["ana"][0]
        self.assertTrue(ana.get(u).json()["comments"][0]["unread"])
        ana.post(u + "/read")
        self.assertFalse(ana.get(u).json()["comments"][0]["unread"])
        # suspeita técnica bloqueia o encaminhamento até ser resolvida
        fid = self.tec.post(u + "/flags", json={"code": "artifacts", "note": "Artefato de movimento"}).json()["id"]
        self.assertEqual(self.tec.get(u).json()["stage"], "pending")
        self.assertEqual(self.tec.post(u + "/forward").status_code, 422)
        self.tec.post(f"/api/v1/ris/prep/flags/{fid}/resolve")
        # prioridade: técnico não altera (só solicita); coordenação altera, auditado
        self.assertEqual(self.tec.post(u + "/priority", json={"priority": "stat"}).status_code, 403)
        self.assertEqual(self.tec.post(u + "/flags", json={"code": "priority_request"}).status_code, 201)
        self.assertEqual(self.coord.post(u + "/priority", json={"priority": "urgent", "reason": "clínica"}).json(),
                         {"priority": "urgent"})
        # encaminhado; distribuição manual (padrão): sem médico; o médico reserva
        r = self.tec.post(u + "/forward")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "forwarded"), r.text)
        self.assertEqual(self.tec.post(u + "/check", json={"code": "series"}).status_code, 409)   # encerrado
        bruno = self.docs["bruno"][0]
        self.assertEqual(ana.post(f"/api/v1/report/queue/{sid}/claim").status_code, 200)
        r = bruno.post(f"/api/v1/report/queue/{sid}/claim")
        self.assertEqual((r.status_code, r.json()["error"]), (409, "already_assigned"))
        self.assertEqual(self.tec.get(u).json()["stage"], "assigned")
        # o médico devolve para correção: volta ao técnico, reserva encerrada
        self.assertEqual(ana.post(u + "/return", json={"reason": "Falta a série coronal"}).status_code, 200)
        d = self.tec.get(u).json()
        self.assertEqual((d["stage"], d["reason"], d["physician"]), ("returned", "Falta a série coronal", None))
        self.tec.post(u + "/check", json={"code": "series"})
        self.assertEqual(self.tec.post(u + "/forward").json()["status"], "forwarded")
        # cancelamento: só com permissão e justificativa
        self.assertEqual(self.tec.post(u + "/cancel", json={"reason": "x"}).status_code, 403)
        self.assertEqual(self.coord.post(u + "/cancel", json={"reason": " "}).status_code, 422)
        self.assertEqual(self.coord.post(u + "/cancel", json={"reason": "Exame repetido (teste)"}).status_code, 200)
        self.assertEqual(self.tec.get(u).json()["stage"], "cancelled")
        from vyonix.audit import service as audit
        with db.session(self.t) as s:
            acts = {e.action for e in audit.query(s, action="ris.prep.*", limit=500)}
        self.assertTrue({"ris.prep.check", "ris.prep.attachment", "ris.prep.attachment_open", "ris.prep.comment",
                         "ris.prep.flag", "ris.prep.flag_resolved", "ris.prep.priority", "ris.prep.forward",
                         "ris.prep.return", "ris.prep.cancel"} <= acts, acts)

    def test_reception_in_progress_duplicates_and_distribution(self):
        from vyonix.settings import service as settings
        s1 = self.study(1, accession="ACC-DUP")
        s2 = self.study(2, accession="ACC-DUP", stable=False)                       # ainda recebendo, mesmo accession
        u2 = f"/api/v1/ris/prep/{s2}"
        d = self.tec.get(u2).json()
        checks = {c["code"]: c["ok"] for c in d["system_checks"]}
        self.assertFalse(checks["reception_finished"])
        self.assertFalse(checks["duplicate_checked"])
        self.assertEqual([x["study_id"] for x in d["duplicates"]], [s1])
        self.assertTrue(next(x for x in self.tec.get("/api/v1/ris/prep").json()["items"] if x["study_id"] == s2)
                        ["incomplete"])
        r = self.tec.post(u2 + "/duplicate", json={"duplicate_of": s2})
        self.assertEqual(r.status_code, 422)                                          # não é duplicado de si mesmo
        self.tec.post(u2 + "/duplicate", json={"duplicate_of": s1, "note": "reenvio do equipamento"})
        self.assertEqual(self.tec.get(u2).json()["stage"], "cancelled")              # original preservado
        u1 = f"/api/v1/ris/prep/{s1}"
        self.tec.post(u1 + "/duplicate", json={})
        # distribuição fixa: vai direto para a Dra. Ana
        with db.session(self.t) as s:
            settings.put(s, "report", "distribution", {"mode": "fixed", "physician_id": self.docs["ana"][1]},
                         actor="admin", reason="teste")
        for code in ("patient_identity", "procedure", "quality"):
            self.tec.post(u1 + "/check", json={"code": code})
        r = self.tec.post(u1 + "/forward").json()
        self.assertEqual((r["status"], r["assigned_to"]), ("assigned", "Dra. Ana Sintetica"))
        # equilibrada: o próximo vai para quem tem menos exames abertos (Dr. Bruno)
        s3 = self.study(3, patient="PREP3")
        with db.session(self.t) as s:
            settings.put(s, "report", "distribution", {"mode": "balanced"}, actor="admin", reason="teste")
        u3 = f"/api/v1/ris/prep/{s3}"
        self.assertEqual(self.tec.post(u3 + "/forward").json()["details"]["missing"],
                         ["Possível duplicidade analisada", "Identificação do paciente conferida",
                          "Procedimento correto", "Qualidade técnica conferida"])   # mesmo paciente, modalidade, data
        self.tec.post(u3 + "/duplicate", json={"note": "outro exame do mesmo dia"})
        for code in ("patient_identity", "procedure", "quality"):
            self.tec.post(u3 + "/check", json={"code": code})
        self.assertEqual(self.tec.post(u3 + "/forward").json()["assigned_to"], "Dr. Bruno Sintetico")
        # a fila de laudos pode exigir a preparação: só estudos encaminhados aparecem
        with db.session(self.t) as s:
            settings.put(s, "ris", "preparation", {"require_forward": True}, actor="admin", reason="teste")
        s4 = self.study(4, patient="PREP4")
        wl = {x["study_id"] for x in self.admin.get("/api/v1/report/worklist").json()["items"]}
        self.assertIn(s1, wl)
        self.assertNotIn(s4, wl)

    def test_reservation_expires_and_share_with_deadline(self):
        from sqlalchemy import update
        from vyonix.db.base import utcnow
        from vyonix.report.models import Assignment
        sid = self.study(1)
        u = f"/api/v1/ris/prep/{sid}"
        for code in ("patient_identity", "procedure", "quality"):
            self.tec.post(u + "/check", json={"code": code})
        self.tec.post(u + "/forward")
        ana, bruno = self.docs["ana"][0], self.docs["bruno"][0]
        self.assertEqual(ana.post(f"/api/v1/report/queue/{sid}/claim").status_code, 200)
        with db.session(self.t) as s:                                                   # reserva abandonada
            s.execute(update(Assignment).values(reserved_until=utcnow() - timedelta(minutes=1)))
        bruno.get("/api/v1/report/worklist")                                            # libera as vencidas
        self.assertEqual(bruno.post(f"/api/v1/report/queue/{sid}/claim").status_code, 200)
        self.assertEqual(bruno.delete(f"/api/v1/report/queue/{sid}/claim").status_code, 200)
        # compartilhamento com prazo: usuário sem vínculo passa a ver o estudo; revogado, perde
        nolink = self.user("semvinculo", ["medico"])
        nid = next(x["id"] for x in self.admin.get("/api/v1/users").json() if x["username"] == "semvinculo")
        self.admin.post("/api/v1/report/physicians", json={"user_id": nid, "full_name": "Dra. Sem Vinculo",
                                                           "crm": "1003", "crm_uf": "PB"})
        self.assertEqual(nolink.get(u).status_code, 403)
        self.assertEqual(self.tec.post(u + "/shares", json={"user_id": nid}).status_code, 403)   # técnico não
        r = self.admin.post(u + "/shares", json={"user_id": nid, "hours": 2})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(nolink.get(u).status_code, 200)
        self.assertIn(sid, {x["study_id"] for x in nolink.get("/api/v1/report/worklist").json()["items"]})
        self.admin.delete(f"/api/v1/ris/prep/shares/{r.json()['id']}")
        self.assertEqual(nolink.get(u).status_code, 403)

    def test_isolation_between_institutions(self):
        sid = self.study(1)
        from vyonix.ris import prep
        other = new_org(db)
        with db.session(other) as s:
            from vyonix.errors import NotFound
            with self.assertRaises(NotFound):
                prep.detail(s, __import__("uuid").UUID(sid), __import__("uuid").uuid4())
            self.assertEqual(prep.queue(s, __import__("uuid").uuid4())["items"], [])


if __name__ == "__main__":
    unittest.main()
