"""TELELAUDO T3 — modelos com versões (rascunho → publicado → arquivado), seções, campos dinâmicos validados e
preenchidos com dados do cadastro, publicação só com conferência, laudo registra modelo e versão.
PostgreSQL real; dados sintéticos."""

from __future__ import annotations

import unittest

from tests_platform.support import new_org, require_db
from tests_platform.test_report import make_study


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs, test_report
    test_pacs.db = test_report.db = db


class Templates(unittest.TestCase):
    def setUp(self):
        from vyonix.report import service as rep, templates as tpl
        self.tpl, self.rep = tpl, rep
        self.t = new_org(db)

    def test_fields_validation_and_rendering(self):
        from vyonix.errors import ValidationFailed
        with db.session(self.t) as s:
            with self.assertRaises(ValidationFailed) as cm:
                self.tpl.save(s, name="Ruim", findings="{{paciente.cpf}} e {{exame.data}} {{x}}", actor="a")
            self.assertEqual(cm.exception.details["unknown_fields"], ["paciente.cpf", "x"])
        ctx = {"paciente.nome": "Fulana Sintetica", "exame.data": None}
        self.assertEqual(self.tpl.render("Paciente {{ paciente.nome }}, exame em {{exame.data}}.", ctx),
                         "Paciente Fulana Sintetica, exame em [não informado].")

    def test_versions_publish_and_report_uses_published(self):
        from vyonix.errors import Conflict, ValidationFailed
        from vyonix.report.models import TemplateVersion
        study_id, _ = make_study(self.t, modality="CT")
        with db.session(self.t) as s:
            t, v1 = self.tpl.save(s, name="TC tórax", modality="CT", technique="Aquisição helicoidal.",
                                  findings="Paciente {{paciente.nome}}, {{paciente.idade}}.", conclusion="Normal.",
                                  actor="adm")
            self.assertEqual((v1.version, v1.status), (1, "draft"))
            with self.assertRaises(Conflict):                           # sem versão publicada
                self.rep.open_report(s, study_id, template_id=t.id, actor="med")
            with self.assertRaises(ValidationFailed):
                self.tpl.publish(s, t.id, reviewed=False, actor="adm")
            self.tpl.publish(s, t.id, reviewed=True, actor="adm")
            _, v2 = self.tpl.save(s, template_id=t.id, name="TC tórax", modality="CT", technique="Nova técnica.",
                                  findings="", conclusion="", actor="adm")
            self.assertEqual((v2.version, v2.status), (2, "draft"))        # publicada não é editada
            self.assertEqual(s.get(TemplateVersion, v1.id).technique, "Aquisição helicoidal.")
            r = self.rep.open_report(s, study_id, template_id=t.id, actor="med")
            self.assertEqual((r.template_id, r.template_version), (t.id, 1))
            self.assertEqual(r.body, "Técnica:\nAquisição helicoidal.\n\nAchados:\nPaciente Laudo Sintetico Teste, "
                                     "56 anos.\n\nConclusão:\nNormal.")
            self.tpl.publish(s, t.id, reviewed=True, actor="adm")
            st = {v["version"]: v["status"] for v in self.tpl.listing(s)[0]["versions"]}
            self.assertEqual(st, {1: "archived", 2: "published"})
            with self.assertRaises(Conflict):
                self.tpl.publish(s, t.id, reviewed=True, actor="adm")      # nada em rascunho

    def test_legacy_template_becomes_published_v1(self):
        from vyonix.report.models import ReportTemplate
        study_id, _ = make_study(self.t)
        with db.session(self.t) as s:
            t = ReportTemplate(name="Antigo", body="Texto antigo {{paciente.nome}}", created_by="x", active=True)
            s.add(t)
            s.flush()
            r = self.rep.open_report(s, study_id, template_id=t.id, actor="med")
            self.assertEqual((r.body, r.template_version), ("Achados:\nTexto antigo Laudo Sintetico Teste", 1))

    def test_isolation(self):
        from vyonix.errors import NotFound
        with db.session(self.t) as s:
            t, _ = self.tpl.save(s, name="Só desta clínica", findings="x", actor="adm")
            self.tpl.publish(s, t.id, reviewed=True, actor="adm")
        other = new_org(db)
        study_id, _ = make_study(other)
        with db.session(other) as s:
            self.assertEqual(self.tpl.listing(s), [])
            with self.assertRaises(NotFound):
                self.rep.open_report(s, study_id, template_id=t.id, actor="med")



class Selection(unittest.TestCase):
    """TELELAUDO T4 — seleção automática: prioridade, fallback, empate e nunca de outra organização."""

    def setUp(self):
        import uuid
        from datetime import date
        from vyonix.clinical import service as clinical
        from vyonix.report import templates as tpl
        from vyonix.tenancy.models import Site
        self.tpl = tpl
        self.t = new_org(db)
        with db.session(self.t) as s:
            site = Site(name="Unidade Leste")
            s.add(site)
            s.flush()
            self.site = site.id
            proc = clinical.save_procedure(s, code="TCCR", name="TC de crânio", modality="CT", actor="t")
            self.proc = proc.id
            p = clinical.create_patient(s, name="Selecao Sintetica Teste", birth_date=date(1980, 1, 1), sex="F",
                                        identifiers=[("DICOM", "SEL-1")], actor="t")
            o = clinical.create_order(s, patient_id=p.id, procedure_id=proc.id, actor="t")
            st = clinical.register_study(s, study_instance_uid=f"2.25.{uuid.uuid4().int}", accession=o.accession,
                                         modality="CT", study_date=date(2026, 10, 28), site_id=site.id, actor="t")
            clinical.reconcile(s, st.id, o.id, actor="t")
            self.study = st.id

    def add(self, name, **kw):
        with db.session(self.t) as s:
            t, _ = self.tpl.save(s, name=name, findings=f"Modelo {name}", actor="adm", **kw)
            self.tpl.publish(s, t.id, reviewed=True, actor="adm")
            return t.id

    def pick(self):
        with db.session(self.t) as s:
            return self.tpl.select_for(s, self.study)

    def test_priority_and_fallback(self):
        self.assertEqual(self.pick()["status"], "none")
        self.add("Genérico")
        self.assertEqual(self.pick()["name"], "Genérico")
        self.add("Org CT", modality="CT")
        self.assertEqual(self.pick()["name"], "Org CT")
        self.add("Org MR", modality="MR")                        # outra modalidade não interfere
        self.add("Org procedimento", procedure_id=self.proc)
        self.assertEqual(self.pick()["name"], "Org procedimento")
        self.add("Unidade CT", modality="CT", site_id=self.site)
        self.assertEqual(self.pick()["level"], "unidade + modalidade")
        self.add("Unidade procedimento", procedure_id=self.proc, site_id=self.site)
        r = self.pick()
        self.assertEqual((r["name"], r["level"]), ("Unidade procedimento", "unidade + procedimento"))
        with db.session(self.t) as s:                            # rascunho não conta: só publicada
            self.tpl.save(s, name="Só rascunho", findings="x", procedure_id=self.proc, site_id=self.site, actor="a")
        self.assertEqual(self.pick()["name"], "Unidade procedimento")

    def test_tie_requires_preferred(self):
        from vyonix.errors import Conflict
        from vyonix.report import service as rep
        a = self.add("CT A", modality="CT")
        self.add("CT B", modality="CT")
        r = self.pick()
        self.assertEqual((r["status"], len(r["candidates"])), ("ambiguous", 2))
        with db.session(self.t) as s:
            with self.assertRaises(Conflict):
                rep.open_report(s, self.study, auto=True, actor="med")
            self.tpl.save(s, template_id=a, name="CT A", modality="CT", preferred=True, findings="Modelo CT A",
                          actor="adm")
            self.tpl.publish(s, a, reviewed=True, actor="adm")
        self.assertEqual(self.pick()["name"], "CT A")
        with db.session(self.t) as s:
            r = rep.open_report(s, self.study, auto=True, actor="med")
            self.assertEqual((r.template_id, r.body), (a, "Achados:\nModelo CT A"))

    def test_never_from_other_organization(self):
        from vyonix.report import service as rep
        other = new_org(db)
        with db.session(other) as s:
            t, _ = self.tpl.save(s, name="Genérico de outra clínica", findings="NÃO USAR", actor="x")
            self.tpl.publish(s, t.id, reviewed=True, actor="x")
        self.assertEqual(self.pick()["status"], "none")
        with db.session(self.t) as s:
            r = rep.open_report(s, self.study, auto=True, actor="med")
            self.assertEqual((r.template_id, r.body), (None, self.tpl.BLANK))


if __name__ == "__main__":
    unittest.main()
