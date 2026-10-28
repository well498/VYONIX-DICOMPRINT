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


if __name__ == "__main__":
    unittest.main()
