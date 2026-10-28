"""VYONIX RIS — primeira entrega: agendamento, worklist e Modality Worklist (C-FIND) com o ciclo fechado pelo PACS.

PostgreSQL real (RLS), API real, associação DICOM real (pynetdicom) contra o servidor de consulta do Core e o
processador de eventos real. Motor DICOM: dublê de teste ``MemoryBackend``. Dados sintéticos (pacientes fictícios).
"""

from __future__ import annotations

import secrets
import socket
import unittest
from datetime import date, datetime, timedelta, timezone

from tests_platform.pacs_support import MemoryBackend, make_dicom
from tests_platform.support import ADMIN_PW, new_org, require_db

BRT = timezone(timedelta(hours=-3))
MWL = "1.2.840.10008.5.1.4.31"
MPPS = "1.2.840.10008.3.1.2.3.3"


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs
    test_pacs.db = db


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_order(tid, name="Maria Sintetica Silva", pid=None, modality="CT"):
    from vyonix.clinical import service as clinical
    pid = pid or f"P{secrets.token_hex(4).upper()}"
    with db.session(tid) as s:
        p = clinical.create_patient(s, name=name, birth_date=date(1980, 1, 2), sex="F",
                                    identifiers=[("DICOM", pid)], actor="t")
        proc = clinical.save_procedure(s, code=f"TC{secrets.token_hex(2)}", name="TC de crânio", modality=modality,
                                       actor="t")
        o = clinical.create_order(s, patient_id=p.id, procedure_id=proc.id, requester="Dr. Teste", actor="t")
        return o.id, o.accession, pid


class Scheduling(unittest.TestCase):
    def setUp(self):
        from vyonix.ris import service as ris
        self.ris = ris
        self.t = new_org(db)

    def test_schedule_assigns_uid_and_updates_order(self):
        from vyonix.audit import service as audit
        from vyonix.clinical.models import Order
        oid, acc, _ = make_order(self.t)
        when = datetime(2026, 11, 3, 9, 30, tzinfo=BRT)
        with db.session(self.t) as s:
            st = self.ris.schedule(s, oid, scheduled_at=when, modality="ct", station_aet="tc_sala1", actor="recep")
            self.assertRegex(st.study_instance_uid, r"^2\.25\.\d+$")
            self.assertLessEqual(len(st.study_instance_uid), 64)
            self.assertEqual((st.modality, st.station_aet, st.status), ("CT", "TC_SALA1", "scheduled"))
            self.assertEqual(len(st.sps_id), 15)
            self.assertEqual(s.get(Order, oid).status, "scheduled")
            self.assertEqual(len(audit.query(s, action="ris.schedule.create")), 1)

    def test_no_overlap_on_same_station_or_room(self):
        from vyonix.errors import Conflict, ValidationFailed
        at = lambda h, m=0: datetime(2026, 11, 5, h, m, tzinfo=BRT)   # noqa: E731
        orders = [make_order(self.t)[0] for _ in range(7)]
        with db.session(self.t) as s:
            first = self.ris.schedule(s, orders[0], scheduled_at=at(9), station_aet="TC_SALA1", room="Sala 1",
                                      duration_min=30, actor="recep")
        cases = [  # (início, estação, sala, duração, deve conflitar)
            (at(9, 15), "TC_SALA1", None, 15, True),        # dentro do exame, mesma estação
            (at(8, 45), None, "Sala 1", 30, True),          # termina depois do início, mesma sala
            (at(9, 30), "TC_SALA1", "Sala 1", 15, False),   # começa quando o anterior termina
            (at(8, 30), "TC_SALA1", None, 30, False),       # termina quando o primeiro começa
            (at(9, 10), "TC_SALA2", "Sala 2", 15, False),   # outra estação e sala
        ]
        for i, (when, aet, room, dur, clash) in enumerate(cases, start=1):
            with db.session(self.t) as s:
                if clash:
                    with self.assertRaises(Conflict, msg=str(when)) as cm:
                        self.ris.schedule(s, orders[i], scheduled_at=when, station_aet=aet, room=room,
                                          duration_min=dur, actor="recep")
                    self.assertIn("09:00", str(cm.exception))
                else:
                    self.ris.schedule(s, orders[i], scheduled_at=when, station_aet=aet, room=room,
                                      duration_min=dur, actor="recep")
        with db.session(self.t) as s:                       # cancelado libera o horário
            self.ris.set_status(s, first.id, "cancelled", reason="teste", actor="recep")
            self.ris.schedule(s, orders[6], scheduled_at=at(9, 15), station_aet="TC_SALA1", duration_min=15,
                              actor="recep")
            with self.assertRaises(ValidationFailed):
                self.ris.schedule(s, orders[6], scheduled_at=at(14), duration_min=0, actor="recep")
        other = new_org(db)                                  # outra organização não interfere
        o2, _, _ = make_order(other)
        with db.session(other) as s:
            self.ris.schedule(s, o2, scheduled_at=at(9, 30), station_aet="TC_SALA1", duration_min=15, actor="r")

    def test_rooms_defaults_and_conflict_by_registered_name(self):
        from vyonix.errors import Conflict
        with db.session(self.t) as s:
            self.ris.save_room(s, name="Sala de TC 1", modality="ct", station_aet="tc_sala1", default_duration_min=20,
                               actor="admin")
            with self.assertRaises(Conflict):
                self.ris.save_room(s, name="sala de tc 1", actor="admin")
        o1, o2 = make_order(self.t)[0], make_order(self.t)[0]
        with db.session(self.t) as s:
            st = self.ris.schedule(s, o1, scheduled_at=datetime(2026, 11, 7, 10, 0, tzinfo=BRT), room="SALA DE TC 1",
                                   actor="recep")
            self.assertEqual((st.room, st.station_aet, st.duration_min), ("Sala de TC 1", "TC_SALA1", 20))
            with self.assertRaises(Conflict):                 # nome digitado diferente, mesma sala: conflito
                self.ris.schedule(s, o2, scheduled_at=datetime(2026, 11, 7, 10, 10, tzinfo=BRT), room="sala de tc 1",
                                  modality="CT", actor="recep")
            self.assertEqual([r["name"] for r in self.ris.rooms(s)], ["Sala de TC 1"])

    def test_check_in_keeps_worklist_and_updates_order(self):
        from vyonix.clinical.models import Order
        oid, _, _ = make_order(self.t)
        with db.session(self.t) as s:
            st = self.ris.schedule(s, oid, scheduled_at=datetime(2026, 11, 6, 8, 0, tzinfo=BRT), station_aet="CR1",
                                   actor="recep")
            self.ris.set_status(s, st.id, "arrived", actor="recep")
            self.assertEqual(s.get(Order, oid).status, "arrived")
            wl = self.ris.worklist(s, date_from=datetime(2026, 11, 6).date(), date_to=datetime(2026, 11, 6).date())
            e = next(x for x in wl if x["schedule_id"] == str(st.id))
            self.assertEqual(self.ris.mwl_dataset(e).ScheduledProcedureStepSequence[0].ScheduledProcedureStepStatus,
                             "ARRIVED")
            self.ris.set_status(s, st.id, "in_progress", actor="tec")
            e = next(x for x in self.ris.worklist(s, date_from=datetime(2026, 11, 6).date(),
                                                  date_to=datetime(2026, 11, 6).date()) if x["schedule_id"] == str(st.id))
            self.assertEqual(self.ris.mwl_dataset(e).ScheduledProcedureStepSequence[0].ScheduledProcedureStepStatus,
                             "STARTED")

    def test_validations(self):
        from vyonix.errors import Conflict, NotFound, ValidationFailed
        oid, _, _ = make_order(self.t)
        ok = datetime(2026, 11, 3, 9, 0, tzinfo=BRT)
        with db.session(self.t) as s:
            with self.assertRaises(ValidationFailed):
                self.ris.schedule(s, oid, scheduled_at=datetime(2026, 11, 3, 9, 0), modality="CT", actor="t")
            with self.assertRaises(ValidationFailed):
                self.ris.schedule(s, oid, scheduled_at=ok, modality="CT", station_aet="AE*", actor="t")
            with self.assertRaises(NotFound):
                import uuid
                self.ris.schedule(s, uuid.uuid4(), scheduled_at=ok, modality="CT", actor="t")
            st = self.ris.schedule(s, oid, scheduled_at=ok, modality="CT", actor="t")
            with self.assertRaises(ValidationFailed):
                self.ris.set_status(s, st.id, "cancelled", actor="t")          # sem motivo
            self.ris.set_status(s, st.id, "cancelled", reason="paciente desistiu", actor="t")
            with self.assertRaises(Conflict):
                self.ris.set_status(s, st.id, "scheduled", actor="t")

    def test_worklist_filters_local_day_and_isolation(self):
        oid1, acc1, pid1 = make_order(self.t, name="Ana Teste Lima")
        oid2, _, _ = make_order(self.t, name="Bruno Teste Rocha", modality="MR")
        with db.session(self.t) as s:
            # 23h30 de 03/11 em Brasília = 02h30 de 04/11 em UTC: precisa cair no dia 03/11 local
            self.ris.schedule(s, oid1, scheduled_at=datetime(2026, 11, 3, 23, 30, tzinfo=BRT), modality="CT",
                              station_aet="TC1", actor="t")
            self.ris.schedule(s, oid2, scheduled_at=datetime(2026, 11, 4, 8, 0, tzinfo=BRT), modality="MR",
                              station_aet="RM1", actor="t")
            day3 = self.ris.worklist(s, date_from=date(2026, 11, 3), date_to=date(2026, 11, 3))
            self.assertEqual([e["patient_name"] for e in day3], ["Ana Teste Lima"])
            self.assertEqual(day3[0]["scheduled_date"], "20261103")
            self.assertEqual(day3[0]["patient_id"], pid1)
            self.assertEqual(day3[0]["accession"], acc1)
            self.assertEqual(len(self.ris.worklist(s, modality="mr")), 1)
            self.assertEqual(len(self.ris.worklist(s, station_aet="tc1")), 1)
            self.assertEqual(len(self.ris.worklist(s, patient_id=pid1)), 1)
            self.assertEqual(len(self.ris.worklist(s, patient_name="Bruno")), 1)
        other = new_org(db)
        with db.session(other) as s:
            self.assertEqual(self.ris.worklist(s), [])                      # outra clínica não vê nada

    def test_mwl_dataset_attributes(self):
        oid, acc, pid = make_order(self.t, name="Maria Sintetica Silva")
        with db.session(self.t) as s:
            self.ris.schedule(s, oid, scheduled_at=datetime(2026, 11, 3, 9, 30, tzinfo=BRT), modality="CT",
                              station_aet="TC1", room="Sala 1", actor="t")
            e = self.ris.worklist(s)[0]
        ds = self.ris.mwl_dataset(e)
        self.assertEqual(str(ds.PatientName), "Silva^Maria Sintetica")
        self.assertEqual((ds.PatientID, ds.IssuerOfPatientID, ds.AccessionNumber), (pid, "DICOM", acc))
        self.assertEqual((ds.PatientBirthDate, ds.PatientSex), ("19800102", "F"))
        sps = ds.ScheduledProcedureStepSequence[0]
        self.assertEqual((sps.Modality, sps.ScheduledStationAETitle, sps.ScheduledProcedureStepStartDate,
                          sps.ScheduledProcedureStepStartTime, sps.ScheduledStationName),
                         ("CT", "TC1", "20261103", "093000", "Sala 1"))


from tests_platform.test_pacs import ApiBase  # noqa: E402


class Api(ApiBase):
    def setUp(self):
        super().setUp()
        self.base = self

    def license_ris(self):
        from vyonix.modules import registry
        h = self.base.helper
        doc = h.issue("annual", modules={"core": {"kind": "contract"}, "ris": {"kind": "contract"}})["document"]
        with db.session(self.base.t) as s:
            self.base.lic.install(s, doc, actor="admin")
            registry.enable(s, "ris", actor="admin", license_check=self.base.lic.module_ok)

    def test_module_gate_and_roles(self):
        c = self.base.login()
        oid, _, _ = make_order(self.base.t)
        body = {"order_id": str(oid), "scheduled_at": "2026-11-03T09:00:00-03:00", "modality": "CT"}
        r = c.post("/api/v1/ris/schedules", json=body)
        self.assertEqual((r.status_code, r.json()["error"]), (402, "module_disabled"))
        self.license_ris()
        r = c.post("/api/v1/ris/schedules", json=body)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertTrue(r.json()["study_instance_uid"].startswith("2.25."))
        wl = c.get("/api/v1/ris/worklist", params={"date_from": "2026-11-03", "date_to": "2026-11-03"}).json()
        self.assertEqual(len(wl["items"]), 1)
        users = {}
        for role in ("tecnico", "recepcionista"):
            r = c.post("/api/v1/users", json={"username": role, "display_name": role, "password": "Senha-Teste-1234",
                                              "roles": [{"role": role}]})
            self.assertEqual(r.status_code, 201, r.text)
            u = self.base.login(role, "Senha-Teste-1234")
            u.post("/api/v1/auth/password", json={"current": "Senha-Teste-1234", "new": "Senha-Nova-9876!"})
            users[role] = self.base.login(role, "Senha-Nova-9876!")
        oid2, _, _ = make_order(self.base.t)
        body2 = {**body, "order_id": str(oid2)}
        self.assertEqual(users["tecnico"].get("/api/v1/ris/worklist").status_code, 200)       # técnico consulta
        self.assertEqual(users["tecnico"].post("/api/v1/ris/schedules", json=body2).status_code, 403)
        self.assertEqual(users["recepcionista"].post("/api/v1/ris/schedules", json=body2).status_code, 201)

    def test_pending_orders_for_scheduling(self):
        c = self.base.login()
        self.license_ris()
        oid, acc, _ = make_order(self.base.t, name="Ana Pendente Sintetica")
        items = c.get("/api/v1/ris/orders").json()["items"]
        it = next(i for i in items if i["order_id"] == str(oid))
        self.assertEqual((it["accession"], it["patient_name"], it["modality"], it["procedure"]),
                         (acc, "Ana Pendente Sintetica", "CT", "TC de crânio"))
        r = c.post("/api/v1/ris/schedules", json={"order_id": str(oid), "scheduled_at": "2026-11-04T10:00:00-03:00"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertNotIn(str(oid), [i["order_id"] for i in c.get("/api/v1/ris/orders").json()["items"]])
        other = new_org(db)
        make_order(other, name="Outra Clinica Sintetica")
        self.assertNotIn("Outra Clinica Sintetica", str(c.get("/api/v1/ris/orders").json()))   # isolamento

    def test_stations_for_scheduling(self):
        c = self.base.login()
        self.license_ris()
        self.assertEqual(c.get("/api/v1/ris/stations").json()["items"], [])
        for aet, q in (("CT_SALA1", True), ("SO_RECEBE", False)):
            r = c.post("/api/v1/pacs/nodes", json={"ae_title": aet, "can_query": q, "can_receive": not q,
                                                   "host": "10.0.0.5", "port": 104})
            self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual([x["ae_title"] for x in c.get("/api/v1/ris/stations").json()["items"]], ["CT_SALA1"])
        r = c.post("/api/v1/users", json={"username": "tec", "display_name": "tec", "password": "Senha-Teste-1234",
                                          "roles": [{"role": "tecnico"}]})
        u = self.base.login("tec", "Senha-Teste-1234")
        u.post("/api/v1/auth/password", json={"current": "Senha-Teste-1234", "new": "Senha-Nova-9876!"})
        u = self.base.login("tec", "Senha-Nova-9876!")
        self.assertEqual(u.get("/api/v1/ris/stations").status_code, 403)


class Worklist(unittest.TestCase):
    """Modality Worklist por DICOM (C-FIND) com associação real e o ciclo fechado pela chegada do estudo ao PACS."""

    def setUp(self):
        from tests.licensing_support import Computer, make_manager
        from tests_platform.test_licensing import Base
        from vyonix.config import Config
        from vyonix.context import build
        from vyonix.modules import registry
        from vyonix.pacs import service as pacs
        from vyonix.pacs.dimse_qr import QRServer
        import tempfile
        import shutil
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp(prefix="vyx-mwl-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.code = f"mwl-{secrets.token_hex(3)}"
        self.t = new_org(db, self.code)
        pc = Computer()
        lm, admin, keys, cid = make_manager(tmp / "lm", clock=lambda: pc.clock.wall)
        self.addCleanup(lm.close)
        h = Base.__new__(Base)
        h.keys, h.lm, h.admin, h.cid = keys, lm, admin, cid
        self.lic = h.licensing(pc)
        h.lic = self.lic
        self.doc = h.issue("annual", modules={"core": {"kind": "contract"}, "ris": {"kind": "contract"},
                                              "pacs": {"kind": "contract"}})["document"]
        with db.session(self.t) as s:
            self.lic.install(s, self.doc, actor="admin")
            registry.enable(s, "pacs", actor="admin", license_check=self.lic.module_ok)
            pacs.add_node(s, "MODALIDADE_TC", host="127.0.0.1", actor="admin")
        self.registry, self.pacs = registry, pacs
        self.b = MemoryBackend()
        self.plat = build(Config(data_dir=tmp / "data", default_organization=self.code), licensing=self.lic, db=db)
        self.plat.options["pacs_backend"] = self.b
        self.port = free_port()
        self.qr = QRServer(self.plat, port=self.port, ae_title="VYONIX_QR", bind="127.0.0.1", backend=self.b)
        self.qr.start()
        self.addCleanup(self.qr.stop)
        self.oid, self.acc, self.pid = make_order(self.t, name="Maria Sintetica Silva")
        from vyonix.ris import service as ris
        with db.session(self.t) as s:
            self.sch = ris.schedule(s, self.oid, scheduled_at=datetime(2026, 11, 3, 9, 30, tzinfo=BRT),
                                    modality="CT", station_aet="MODALIDADE_TC", actor="recep")
            self.sch_id, self.uid = self.sch.id, self.sch.study_instance_uid

    def find(self, **sps):
        from pydicom.dataset import Dataset
        from pynetdicom import AE
        ae = AE(ae_title="MODALIDADE_TC")
        ae.add_requested_context(MWL)
        a = ae.associate("127.0.0.1", self.port, ae_title="VYONIX_QR")
        self.assertTrue(a.is_established)
        q = Dataset()
        q.PatientName, q.PatientID, q.AccessionNumber, q.StudyInstanceUID = "", "", "", ""
        item = Dataset()
        item.Modality = sps.get("Modality", "")
        item.ScheduledStationAETitle = sps.get("ScheduledStationAETitle", "")
        item.ScheduledProcedureStepStartDate = sps.get("date", "")
        item.ScheduledProcedureStepStartTime = ""
        item.ScheduledProcedureStepID = ""
        q.ScheduledProcedureStepSequence = [item]
        try:
            return [(st.Status, ds) for st, ds in a.send_c_find(q, MWL) if st]
        finally:
            a.release()

    def test_worklist_requires_ris_module(self):
        res = self.find(Modality="CT")
        self.assertEqual([st for st, _ in res], [0xC001])                  # RIS não habilitado nesta organização

    def test_worklist_by_dicom_and_loop_closed_by_pacs(self):
        from vyonix.audit import service as audit
        from vyonix.events.worker import process_batch
        from vyonix.ris.models import Schedule
        with db.session(self.t) as s:
            self.registry.enable(s, "ris", actor="admin", license_check=self.lic.module_ok)
        hits = [ds for st, ds in self.find(Modality="CT", ScheduledStationAETitle="MODALIDADE_TC", date="20261103")
                if st == 0xFF00]
        self.assertEqual(len(hits), 1)
        ds = hits[0]
        self.assertEqual((str(ds.PatientName), ds.PatientID, ds.AccessionNumber, ds.StudyInstanceUID),
                         ("Silva^Maria Sintetica", self.pid, self.acc, self.uid))
        self.assertEqual(ds.ScheduledProcedureStepSequence[0].ScheduledProcedureStepStartDate, "20261103")
        self.assertEqual([d for st, d in self.find(Modality="MR") if st == 0xFF00], [])     # outra modalidade
        self.assertEqual([d for st, d in self.find(date="20261104") if st == 0xFF00], [])   # outro dia
        with db.session(self.t) as s:
            self.assertEqual(len(audit.query(s, action="ris.mwl.find")), 3)
        # a modalidade usa os dados da worklist: o estudo chega ao PACS com o UID e o accession agendados
        from pydicom.uid import generate_uid
        study = make_dicom(study=self.uid, series=generate_uid(prefix=None), sop=generate_uid(prefix=None),
                           patient_id=self.pid, accession=self.acc)
        with db.session(self.t) as s:
            self.pacs.ingest(s, self.b, study, actor="teste")
        while process_batch(db, self.plat.bus):
            pass
        with db.session(self.t) as s:
            self.assertEqual(s.get(Schedule, self.sch_id).status, "received")
            self.assertEqual(len([d for st, d in self.find(Modality="CT") if st == 0xFF00]), 0)   # saiu da lista

    def mpps(self):
        from pynetdicom import AE
        ae = AE(ae_title="MODALIDADE_TC")
        ae.add_requested_context(MPPS)
        a = ae.associate("127.0.0.1", self.port, ae_title="VYONIX_QR")
        self.assertTrue(a.is_established)
        self.addCleanup(a.release)
        return a

    @staticmethod
    def mpps_create_ds(sps_id="", study_uid=""):
        from pydicom.dataset import Dataset
        ds = Dataset()
        ds.PerformedProcedureStepStatus = "IN PROGRESS"
        ds.PerformedProcedureStepID = "PPS1"
        ds.PerformedStationAETitle = "MODALIDADE_TC"
        ds.Modality = "CT"
        ssa = Dataset()
        ssa.ScheduledProcedureStepID, ssa.StudyInstanceUID = sps_id, study_uid
        ssa.AccessionNumber = ""
        ds.ScheduledStepAttributesSequence = [ssa]
        return ds

    def test_mpps_in_progress_completed_and_rules(self):
        from pydicom.dataset import Dataset
        from pydicom.uid import generate_uid
        from vyonix.audit import service as audit
        from vyonix.ris.models import Schedule
        a = self.mpps()
        st, _ = a.send_n_create(self.mpps_create_ds(self.sch.sps_id), MPPS, generate_uid(prefix=None))
        self.assertEqual(st.Status, 0x0110)                               # RIS não habilitado: recusado
        with db.session(self.t) as s:
            self.registry.enable(s, "ris", actor="admin", license_check=self.lic.module_ok)
        uid = generate_uid(prefix=None)
        st, _ = a.send_n_create(self.mpps_create_ds(self.sch.sps_id), MPPS, uid)
        self.assertEqual(st.Status, 0x0000)
        with db.session(self.t) as s:
            sch = s.get(Schedule, self.sch_id)
            self.assertEqual((sch.status, sch.mpps_uid, sch.mpps_status), ("in_progress", uid, "IN PROGRESS"))
            from vyonix.ris import service as ris
            wl = ris.worklist(s, date_from=date(2026, 11, 3), date_to=date(2026, 11, 3))
            self.assertEqual([e["mpps_status"] for e in wl if e["schedule_id"] == str(self.sch_id)], ["IN PROGRESS"])
        st, _ = a.send_n_create(self.mpps_create_ds(self.sch.sps_id), MPPS, uid)
        self.assertEqual(st.Status, 0x0111)                               # MPPS duplicado
        hits = [d for s_, d in self.find(Modality="CT") if s_ == 0xFF00]  # continua na worklist, como STARTED
        self.assertEqual(hits[0].ScheduledProcedureStepSequence[0].ScheduledProcedureStepID, self.sch.sps_id)
        done = Dataset()
        done.PerformedProcedureStepStatus = "COMPLETED"
        st, _ = a.send_n_set(done, MPPS, uid)
        self.assertEqual(st.Status, 0x0000)
        with db.session(self.t) as s:
            self.assertEqual(s.get(Schedule, self.sch_id).status, "completed")
            self.assertEqual(len(audit.query(s, action="ris.mpps.set")), 1)
        again = Dataset()
        again.PerformedProcedureStepStatus = "DISCONTINUED"
        st, _ = a.send_n_set(again, MPPS, uid)
        self.assertEqual(st.Status, 0x0110)                               # finalizado não muda
        self.assertEqual([d for s_, d in self.find(Modality="CT") if s_ == 0xFF00], [])     # saiu da worklist
        # exame sem agendamento: aceito e só registrado
        st, _ = a.send_n_create(self.mpps_create_ds("S-NAO-EXISTE"), MPPS, generate_uid(prefix=None))
        self.assertEqual(st.Status, 0x0000)
        with db.session(self.t) as s:
            self.assertEqual(len(audit.query(s, action="ris.mpps.unscheduled")), 1)

    def test_mpps_discontinued_returns_to_worklist(self):
        from pydicom.dataset import Dataset
        from pydicom.uid import generate_uid
        from vyonix.ris.models import Schedule
        with db.session(self.t) as s:
            self.registry.enable(s, "ris", actor="admin", license_check=self.lic.module_ok)
        a = self.mpps()
        uid = generate_uid(prefix=None)
        self.assertEqual(a.send_n_create(self.mpps_create_ds(study_uid=self.uid), MPPS, uid)[0].Status, 0x0000)
        stop = Dataset()
        stop.PerformedProcedureStepStatus = "DISCONTINUED"
        self.assertEqual(a.send_n_set(stop, MPPS, uid)[0].Status, 0x0000)
        with db.session(self.t) as s:
            self.assertEqual(s.get(Schedule, self.sch_id).status, "scheduled")
        self.assertEqual(len([d for s_, d in self.find(Modality="CT") if s_ == 0xFF00]), 1)

    def test_mpps_from_unregistered_station_refused(self):
        from pynetdicom import AE
        ae = AE(ae_title="INTRUSO")
        ae.add_requested_context(MPPS)
        a = ae.associate("127.0.0.1", self.port, ae_title="VYONIX_QR")
        self.assertFalse(a.is_established)


if __name__ == "__main__":
    unittest.main()
