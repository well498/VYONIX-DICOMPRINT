"""Cadastro clínico: identificadores, mescla reversível, pedidos e conciliação por número de acesso."""

from __future__ import annotations

import unittest
from datetime import date

from tests_platform.support import new_org, require_db


def setUpModule():
    global db
    db = require_db()


class Clinical(unittest.TestCase):
    def setUp(self):
        self.t = new_org(db)

    def drain(self):
        from vyonix.clinical import service as clinical
        from vyonix.events.bus import Bus
        from vyonix.events.worker import process_batch
        bus = Bus()
        clinical.register_consumers(bus)
        while process_batch(db, bus):
            pass

    def test_identifier_unique_and_search(self):
        from vyonix.clinical import service as c
        from vyonix.errors import Conflict, ValidationFailed
        with db.session(self.t) as s:
            a = c.create_patient(s, name="  Maria   da Silva ", birth_date=date(1980, 5, 1), sex="F",
                                 identifiers=[("PRONTUARIO", "123")], actor="t")
            self.assertEqual(a.name, "Maria da Silva")
        with self.assertRaises(Conflict):
            with db.session(self.t) as s:
                c.create_patient(s, name="Outra", identifiers=[("PRONTUARIO", "123")], actor="t")
        with self.assertRaises(ValidationFailed):
            with db.session(self.t) as s:
                c.create_patient(s, name="X", actor="t")
        with db.session(self.t) as s:
            self.assertEqual([p.id for p in c.search_patients(s, q="maria silva")], [a.id])
            self.assertEqual([p.id for p in c.search_patients(s, identifier="123")], [a.id])
        other = new_org(db)                              # outra clínica pode usar o mesmo identificador
        with db.session(other) as s:
            c.create_patient(s, name="Maria", identifiers=[("PRONTUARIO", "123")], actor="t")
            self.assertEqual(len(c.search_patients(s, q="maria")), 1)

    def test_merge_and_unmerge_restore_everything(self):
        from vyonix.clinical import service as c
        from vyonix.errors import Conflict
        from vyonix.tenancy import service as tenancy
        with db.session(self.t) as s:
            site = tenancy.sites(s)[0].id
            a = c.create_patient(s, name="João Souza", identifiers=[("PRONTUARIO", "A1")], actor="t")
            b = c.create_patient(s, name="Joao Souza", identifiers=[("CPF", "52998224725")], actor="t")
            enc = c.create_encounter(s, patient_id=b.id, site_id=site, actor="t")
            o = c.create_order(s, patient_id=b.id, encounter_id=enc.id, actor="t")
            st = c.register_study(s, study_instance_uid="1.2.840.1.2", accession=o.accession, modality="CT",
                                  actor="pacs")
            a_id, b_id, o_id = a.id, b.id, o.id
        self.drain()
        with db.session(self.t) as s:
            m = c.merge_patients(s, source_id=b_id, target_id=a_id, reason="duplicidade", actor="t")
            merge_id = m.id
        with db.session(self.t) as s:
            self.assertEqual({i.issuer for i in c.identifiers_of(s, a_id)}, {"PRONTUARIO", "CPF"})
            self.assertEqual(c.orders(s, patient_id=a_id)[0].id, o_id)
            self.assertEqual(len(c.studies(s, patient_id=a_id)), 1)
            self.assertEqual(c.search_patients(s, q="souza")[0].id, a_id)        # origem fora da busca
            self.assertEqual(c.get_patient(s, b_id).merged_into_id, a_id)
        with self.assertRaises(Conflict):
            with db.session(self.t) as s:
                c.update_patient(s, b_id, name="Novo", actor="t")
        with db.session(self.t) as s:
            c.unmerge(s, merge_id, actor="t", reason="mescla indevida")
        with db.session(self.t) as s:
            self.assertEqual({i.issuer for i in c.identifiers_of(s, b_id)}, {"CPF"})
            self.assertEqual({i.issuer for i in c.identifiers_of(s, a_id)}, {"PRONTUARIO"})
            self.assertEqual(c.orders(s, patient_id=b_id)[0].id, o_id)
            self.assertEqual(len(c.studies(s, patient_id=b_id)), 1)
            self.assertTrue(c.get_patient(s, b_id).active)
        with self.assertRaises(Conflict):
            with db.session(self.t) as s:
                c.unmerge(s, merge_id, actor="t", reason="de novo")

    def test_auto_reconcile_by_accession_both_orders(self):
        from vyonix.clinical import service as c
        with db.session(self.t) as s:
            p = c.create_patient(s, name="Ana Lima", identifiers=[("PRONTUARIO", "9")], actor="t")
            o1 = c.create_order(s, patient_id=p.id, actor="t")
            c.register_study(s, study_instance_uid="1.2.3.4", accession=o1.accession, actor="pacs")
            # estudo chega antes do pedido
            c.register_study(s, study_instance_uid="1.2.3.5", accession="ACC0002", actor="pacs")
            pid, o1_id = p.id, o1.id
        self.drain()
        with db.session(self.t) as s:
            o2 = c.create_order(s, patient_id=pid, accession="ACC0002", actor="t")
            o2_id = o2.id
        self.drain()
        with db.session(self.t) as s:
            got = {st.study_instance_uid: (st.order_id, st.patient_id) for st in c.studies(s)}
            self.assertEqual(got["1.2.3.4"], (o1_id, pid))
            self.assertEqual(got["1.2.3.5"], (o2_id, pid))
            self.assertEqual(c.orders(s, patient_id=pid)[0].status, "in_progress")
            self.assertEqual(c.studies(s, unreconciled=True), [])

    def test_reconcile_conflict_other_patient(self):
        from vyonix.clinical import service as c
        from vyonix.errors import Conflict
        with db.session(self.t) as s:
            p1 = c.create_patient(s, name="Paciente Um", identifiers=[("PRONTUARIO", "1")], actor="t")
            p2 = c.create_patient(s, name="Paciente Dois", actor="t")
            st = c.register_study(s, study_instance_uid="1.9.9", patient_identifier=("PRONTUARIO", "1"),
                                  actor="pacs")
            self.assertEqual(st.patient_id, p1.id)
            o = c.create_order(s, patient_id=p2.id, actor="t")
            st_id, o_id = st.id, o.id
        with self.assertRaises(Conflict):
            with db.session(self.t) as s:
                c.reconcile(s, st_id, o_id, actor="t")

    def test_optimistic_concurrency(self):
        from vyonix.clinical import service as c
        from vyonix.errors import Conflict
        with db.session(self.t) as s:
            p = c.create_patient(s, name="Carlos Dias", actor="t")
            pid, v = p.id, p.row_version
        with db.session(self.t) as s:
            c.update_patient(s, pid, name="Carlos A. Dias", actor="t", expected_version=v)
        with self.assertRaises(Conflict):
            with db.session(self.t) as s:
                c.update_patient(s, pid, name="Carlos B. Dias", actor="t", expected_version=v)

    def test_events_carry_no_personal_data(self):
        from sqlalchemy import select
        from vyonix.clinical import service as c
        from vyonix.events.models import OutboxEvent
        with db.session(self.t) as s:
            c.create_patient(s, name="Nome Sigiloso", identifiers=[("CPF", "11144477735")], actor="t")
        with db.session(self.t) as s:
            for ev in s.execute(select(OutboxEvent)).scalars():
                blob = str(ev.data)
                self.assertNotIn("Sigiloso", blob)
                self.assertNotIn("11144477735", blob)


if __name__ == "__main__":
    unittest.main()
