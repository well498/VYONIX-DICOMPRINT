"""Editor de laudos: texto rico seguro, compatibilidade com laudos em texto, PDF formatado, histórico do rascunho,
frases rápidas (instituição × pessoais), modelos pessoais e fluxo de revisão (segunda leitura) com versões.
PostgreSQL real (row level security); dados sintéticos."""

from __future__ import annotations

import hashlib
import io
import json
import unittest

from tests_platform import test_report as tr
from tests_platform.support import require_db
from tests_platform.test_pacs import ApiBase

make_study = tr.make_study


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs, test_report
    test_pacs.db = test_report.db = db


PW = "Senha-Nova-9876!"


class Sanitizer(unittest.TestCase):
    """Sem banco: a lista permitida não deixa passar código, links, estilos nem atributos."""

    ATTACKS = [
        '<script>alert(1)</script>ok', '<img src=x onerror=alert(1)>ok', '<a href="javascript:alert(1)">ok</a>',
        '<p onclick="alert(1)" style="color:red" class="x">ok</p>', '<svg><script>alert(1)</script></svg>ok',
        '<iframe src="https://exemplo.invalid"></iframe>ok', '<style>p{}</style>ok', '<p>ok<!-- <script> --></p>',
        '<math><mi xlink:href="javascript:alert(1)">ok</mi></math>', '<scr<script>ipt>alert(1)</script>ok',
        '<td colspan="999" onmouseover="x">ok</td>', '<object data="x"></object><embed src="x">ok',
        '<form><button formaction="javascript:alert(1)">x</button></form>ok', '<<p>>ok', '&lt;script&gt;ok',
        '<p>ok</p></p></table></ul>', '<b><i><u>ok', '<template><img src=x onerror=1></template>ok',
    ]

    def test_attacks_are_neutralized(self):
        from html.parser import HTMLParser
        from vyonix.report import richtext

        class Tags(HTMLParser):
            def __init__(self):
                super().__init__()
                self.found = []

            def handle_starttag(self, tag, attrs):
                self.found.append((tag, attrs))
        allowed = richtext.BLOCK | richtext.INLINE
        for a in self.ATTACKS:
            out = richtext.sanitize(a)
            t = Tags()
            t.feed(out)
            for tag, attrs in t.found:
                self.assertIn(tag, allowed, (a, out))
                for k, v in attrs:
                    self.assertIn(k, ("colspan", "rowspan"), (a, out))
                    self.assertTrue(v.isdigit() and 1 < int(v) <= 10, (a, out))
            low = out.lower()
            for bad in ("<script", "javascript:", "onerror", "onclick", "style=", "<img", "<a ", "<iframe", "href"):
                self.assertNotIn(bad, low, (a, out))
            self.assertEqual(richtext.sanitize(out), out, a)                    # idempotente

    def test_random_markup_never_leaks_tags(self):
        """Fuzz simples: fragmentos aleatórios de marcação nunca produzem tag fora da lista."""
        import random
        import re
        from vyonix.report import richtext
        rnd = random.Random(20261029)
        bits = ["<", ">", "/", "p", "script", "img", " src=x", " onerror=y", "\"", "'", "=", "b", "td", " colspan=3",
                "<!--", "-->", "&", "#", ";", "a", "style", "svg", "ok", " ", "\n", "<br>", "</"]
        for _ in range(3000):
            src = "".join(rnd.choice(bits) for _ in range(rnd.randint(1, 30)))
            out = richtext.sanitize(src)
            for tag, attrs in re.findall(r"<\s*/?\s*([a-zA-Z0-9]+)([^>]*)>", out):
                self.assertIn(tag.lower(), richtext.BLOCK | richtext.INLINE, (src, out))
                self.assertRegex(attrs, r'^(\s(colspan|rowspan)="\d+")*$', (src, out))

    def test_text_conversions_and_limits(self):
        from vyonix.errors import ValidationFailed
        from vyonix.report import richtext
        h = richtext.from_text("Linha 1\nLinha 2\n\n<b>não é marcação</b>")
        self.assertEqual(h, "<p>Linha 1<br>Linha 2</p><p>&lt;b&gt;não é marcação&lt;/b&gt;</p>")
        self.assertEqual(richtext.to_text("<p><strong>Achados:</strong></p><ul><li>A</li><li>B</li></ul>"
                                          "<ol><li>um</li></ol><table><tr><td>x</td><td>y</td></tr></table>"),
                         "Achados:\n\n• A\n• B\n\n1. um\n\nx | y")
        self.assertEqual(richtext.normalize("texto <b>", "text"), ("texto <b>", "text"))
        with self.assertRaises(ValidationFailed):
            richtext.normalize("x", "markdown")
        with self.assertRaises(ValidationFailed):
            richtext.sanitize("a" * (richtext.MAX_HTML + 1))

    def test_legacy_text_hash_unchanged(self):
        """Laudos em texto continuam com o mesmo conteúdo canônico (e hash) de antes do texto rico."""
        from vyonix.report.service import canonical
        old = json.dumps({"study_instance_uid": "2.25.1", "version": 1, "kind": "final", "body": "Normal.",
                          "critical": False, "signed_by": "Dr", "signed_at": "2026-01-01T00:00:00"},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        new = canonical("2.25.1", 1, "final", "Normal.", False, "Dr", "2026-01-01T00:00:00")
        self.assertEqual(hashlib.sha256(new).hexdigest(), hashlib.sha256(old).hexdigest())
        self.assertNotEqual(canonical("2.25.1", 1, "final", "<p>Normal.</p>", False, "Dr", "t", "html"),
                            canonical("2.25.1", 1, "final", "<p>Normal.</p>", False, "Dr", "t", "text"))

    def test_pdf_flowables(self):
        from reportlab.lib.styles import getSampleStyleSheet
        from vyonix.report import richtext
        st = getSampleStyleSheet()
        f = richtext.to_flowables("<h3>T</h3><p><strong>a</strong></p><ul><li>x</li></ul>"
                                  "<table><tr><th colspan=\"2\">h</th></tr><tr><td>1</td><td>2</td></tr></table>",
                                  "html", {"b": st["Normal"]}, width=400)
        self.assertEqual([type(x).__name__ for x in f], ["Paragraph", "Paragraph", "ListFlowable", "Table", "Spacer"])
        self.assertEqual(len(richtext.to_flowables("a\nb", "text", {"b": st["Normal"]}, width=400)), 1)


class EditorBase(ApiBase):
    license_report = tr.Api.license_report
    user = tr.Api.user

    def setUp(self):
        super().setUp()
        self.admin = self.login()
        self.license_report()
        self.med = self.user(self.admin, "medica", "medico")
        self.med2 = self.user(self.admin, "medico2", "medico")
        self.pid = self.physician("medica", "Dra. Medica Teste", "54321")
        self.pid2 = self.physician("medico2", "Dr. Segundo Teste", "65432")

    def physician(self, user, name, crm, **extra):
        r = self.admin.post("/api/v1/report/physicians", json={"user_id": self.ids[user], "full_name": name,
                                                               "crm": crm, "crm_uf": "PB", **extra})
        self.assertEqual(r.status_code, 201, r.text)
        pid = r.json()["id"]
        self.assertEqual(self.admin.post(f"/api/v1/report/physicians/{pid}/links",
                                         json={"valid_from": "2026-01-01"}).status_code, 201)
        return pid

    def open(self, c):
        study_id, _ = make_study(self.t)
        r = c.post("/api/v1/report/reports", json={"study_id": str(study_id)})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()



class Editor(EditorBase):
    def test_rich_draft_pdf_history_and_interop(self):
        rep = self.open(self.med)
        self.assertEqual(rep["body_format"], "text")
        body = ('<p><strong>Achados:</strong> fígado <em>normal</em> <u>sem</u> lesões.</p>'
                '<ul><li>Baço 10 cm</li></ul><table><tr><th>Órgão</th><th>Medida</th></tr>'
                '<tr><td>Rim D</td><td>11 cm</td></tr></table><script>alert(1)</script><img src=x onerror=y>')
        r = self.med.put(f"/api/v1/report/reports/{rep['id']}", json={"body": body, "body_format": "html",
                                                                      "row_version": rep["row_version"]})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["body_format"], "html")
        self.assertNotIn("script", d["body"])
        self.assertNotIn("img", d["body"])
        self.assertIn("<table>", d["body"])
        self.assertEqual(d["draft_revision"], 1)
        # salvar o mesmo conteúdo não cria revisão; conteúdo novo cria
        self.med.put(f"/api/v1/report/reports/{rep['id']}", json={"body": d["body"], "body_format": "html"})
        r = self.med.put(f"/api/v1/report/reports/{rep['id']}",
                         json={"body": d["body"] + "<p>Conclusão: normal.</p>", "body_format": "html"})
        revs = self.med.get(f"/api/v1/report/reports/{rep['id']}/revisions").json()["items"]
        self.assertEqual([(x["revision"], x["author"], x["event"]) for x in revs],
                         [(1, "medica", "save"), (2, "medica", "save")])
        # limite: texto simples continua com 20 mil caracteres
        r = self.med.put(f"/api/v1/report/reports/{rep['id']}", json={"body": "x" * 20001, "body_format": "text"})
        self.assertEqual(r.status_code, 422)
        r = self.med.post(f"/api/v1/report/reports/{rep['id']}/finalize", json={"password": PW})
        self.assertEqual(r.status_code, 200, r.text)
        v = r.json()["versions"][0]
        self.assertEqual((v["body_format"], v["author"], v["reviewer"]), ("html", "Dra. Medica Teste", None))
        self.assertEqual((v["changes"]["revisions"], v["changes"]["editors"]), (2, ["medica"]))
        self.assertTrue(self.med.get(f"/api/v1/report/reports/{rep['id']}/verify").json()["valid"])
        from pypdf import PdfReader
        pdf = self.med.get(f"/api/v1/report/reports/{rep['id']}/pdf")
        self.assertEqual(pdf.status_code, 200)
        txt = " ".join(pg.extract_text() for pg in PdfReader(io.BytesIO(pdf.content)).pages).replace("\n", " ")
        for want in ("Achados:", "fígado normal", "Baço 10 cm", "Órgão", "Rim D", "11 cm", "Conclusão: normal."):
            self.assertIn(want, txt)
        self.assertNotIn("<strong>", txt)
        self.assertNotIn("alert", txt)
        # FHIR/HL7: texto simples derivado, sem marcação
        import uuid
        from sqlalchemy import select
        from vyonix.report import interop
        from vyonix.report.models import ReportVersion
        with db.session(self.t) as s:
            vs = list(s.execute(select(ReportVersion).where(ReportVersion.report_id == uuid.UUID(rep["id"]))).scalars())
            text = interop._text(vs)
        self.assertNotIn("<", text)
        self.assertIn("• Baço 10 cm", text)
        self.assertIn("Rim D | 11 cm", text)

    def test_phrases_institution_and_personal(self):
        r = self.med.post("/api/v1/report/phrases", json={"title": "Normal", "shortcut": "normal",
                                                          "body": "<p><b>Sem</b> alterações.<script>x</script></p>"})
        self.assertEqual(r.status_code, 201, r.text)
        mine = r.json()
        self.assertEqual((mine["shortcut"], mine["personal"], mine["body"]),
                         ("/normal", True, "<p><strong>Sem</strong> alterações.</p>"))
        # médico não cria frase da instituição; administrador cria
        self.assertEqual(self.med.post("/api/v1/report/phrases", json={"title": "I", "body": "x",
                                                                       "personal": False}).status_code, 403)
        r = self.admin.post("/api/v1/report/phrases", json={"title": "Institucional", "body": "Texto padrão.",
                                                            "personal": False, "modality": "ct"})
        self.assertEqual(r.status_code, 201, r.text)
        inst = r.json()
        # o outro médico vê só a da instituição; a pessoal da colega não existe para ele
        items = self.med2.get("/api/v1/report/phrases").json()["items"]
        self.assertEqual([x["title"] for x in items], ["Institucional"])
        self.assertEqual(self.med2.put(f"/api/v1/report/phrases/{mine['id']}",
                                       json={"title": "x", "body": "y"}).status_code, 404)
        self.assertEqual(self.med2.delete(f"/api/v1/report/phrases/{mine['id']}").status_code, 404)
        self.assertEqual(self.admin.delete(f"/api/v1/report/phrases/{mine['id']}").status_code, 404)
        # e não altera a da instituição sem report.phrases.manage
        self.assertEqual(self.med.put(f"/api/v1/report/phrases/{inst['id']}",
                                      json={"title": "x", "body": "y"}).status_code, 403)
        titles = sorted(x["title"] for x in self.med.get("/api/v1/report/phrases").json()["items"])
        self.assertEqual(titles, ["Institucional", "Normal"])
        self.assertEqual([x["title"] for x in self.med.get("/api/v1/report/phrases",
                                                           params={"modality": "MR"}).json()["items"]], ["Normal"])
        self.assertEqual(self.med.post("/api/v1/report/phrases", json={"title": "Outra", "shortcut": "/normal",
                                                                      "body": "z"}).status_code, 409)
        self.assertEqual(self.med.post("/api/v1/report/phrases", json={"title": "Vazia",
                                                                      "body": "<script>x</script>"}).status_code, 422)
        self.assertEqual(self.med.delete(f"/api/v1/report/phrases/{mine['id']}").status_code, 204)
        # técnico (sem report.read) não acessa
        tec = self.user(self.admin, "tecnico", "tecnico")
        self.assertEqual(tec.get("/api/v1/report/phrases").status_code, 403)

    def test_personal_templates_are_private_and_not_auto_selected(self):
        r = self.med.post("/api/v1/report/templates", json={
            "name": "Meu modelo TC", "modality": "CT", "personal": True, "content_format": "html",
            "findings": "<p><strong>Paciente:</strong> {{paciente.nome}}</p><ul><li>item</li></ul>"})
        self.assertEqual(r.status_code, 201, r.text)
        tid = r.json()["id"]
        self.assertEqual(self.med.post(f"/api/v1/report/templates/{tid}/publish",
                                       json={"reviewed": True}).status_code, 200)
        self.assertEqual(self.med.get(f"/api/v1/report/templates/{tid}/preview").status_code, 200)
        items = {x["name"]: x for x in self.med.get("/api/v1/report/templates").json()["items"]}
        self.assertTrue(items["Meu modelo TC"]["personal"])
        self.assertEqual(items["Meu modelo TC"]["content_format"], "html")
        for other in (self.med2, self.admin):
            self.assertNotIn("Meu modelo TC", [x["name"] for x in other.get("/api/v1/report/templates").json()["items"]])
            self.assertEqual(other.put(f"/api/v1/report/templates/{tid}", json={"name": "x"}).status_code, 404)
            self.assertEqual(other.post(f"/api/v1/report/templates/{tid}/publish",
                                        json={"reviewed": True}).status_code, 404)
        # usar o modelo: só a dona; campos preenchidos e escapados
        study_id, _ = make_study(self.t)
        r = self.med2.post("/api/v1/report/reports", json={"study_id": str(study_id), "template_id": tid})
        self.assertEqual(r.status_code, 404)
        r = self.med.post("/api/v1/report/reports", json={"study_id": str(study_id), "template_id": tid})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["body_format"], "html")
        self.assertIn("<strong>Paciente:</strong> Laudo Sintetico Teste", r.json()["body"])
        self.assertIn("<ul><li>item</li></ul>", r.json()["body"])
        # seleção automática ignora modelos pessoais
        study2, _ = make_study(self.t)
        r = self.med.post("/api/v1/report/reports", json={"study_id": str(study2), "auto": True})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["body_format"], "text")
        self.assertIsNone(r.json().get("template_id"))
        # sem report.templates.own não cria pessoal
        from vyonix.auth import service as auth
        with db.session(self.t) as s:
            auth.save_role(s, code="leitor", name="Leitor", permissions=["report.read"], actor="t")
        tec = self.user(self.admin, "leitor1", "leitor")
        self.assertEqual(tec.post("/api/v1/report/templates", json={"name": "P", "personal": True}).status_code, 403)

    def test_escaped_fields_in_html_template(self):
        from vyonix.report import templates as tpl
        out = tpl.compose({"technique": "", "findings": "<p>{{paciente.nome}}</p>", "conclusion": "",
                           "content_format": "html"}, {"paciente.nome": "<script>x</script>"})
        self.assertEqual(out, "<p><strong>Achados:</strong></p><p>&lt;script&gt;x&lt;/script&gt;</p>")

    def test_review_flow(self):
        from vyonix.auth import service as auth
        # a médica 1 exige revisão; o médico 2 recebe report.review
        r = self.admin.put(f"/api/v1/report/physicians/{self.pid}", json={
            "user_id": self.ids["medica"], "full_name": "Dra. Medica Teste", "crm": "54321", "crm_uf": "PB",
            "requires_review": True})
        self.assertEqual(r.status_code, 200, r.text)
        with db.session(self.t) as s:
            auth.save_role(s, code="revisor", name="Revisor", permissions=["report.review"], actor="t")
        import uuid
        with db.session(self.t) as s:
            from vyonix.auth.models import Role, UserRole
            from sqlalchemy import select
            role = s.execute(select(Role).where(Role.code == "revisor")).scalar_one()
            s.add(UserRole(user_id=uuid.UUID(self.ids["medico2"]), role_id=role.id))
        self.med2 = self.login("medico2", PW)
        rv = self.med.get("/api/v1/report/reviewers").json()["items"]
        self.assertEqual([x["id"] for x in rv], [self.pid2])
        rep = self.open(self.med)
        rid = rep["id"]
        self.med.put(f"/api/v1/report/reports/{rid}", json={"body": "<p>Rascunho da médica.</p>",
                                                           "body_format": "html"})
        r = self.med.post(f"/api/v1/report/reports/{rid}/finalize", json={"password": PW})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "review_required"))
        r = self.med.post(f"/api/v1/report/reports/{rid}/review", json={"reviewer_id": self.pid,
                                                                       "note": "Confira o fígado"})
        self.assertEqual(r.status_code, 422, r.text)                                  # não revisa a si mesma
        r = self.med.post(f"/api/v1/report/reports/{rid}/review", json={"reviewer_id": self.pid2,
                                                                       "note": "Confira o fígado"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "review")
        # autora não edita nem libera; revisor devolve com observação
        self.assertEqual(self.med.put(f"/api/v1/report/reports/{rid}", json={"body": "x"}).status_code, 409)
        self.assertEqual(self.med.post(f"/api/v1/report/reports/{rid}/finalize",
                                       json={"password": PW}).status_code, 409)
        self.assertEqual(self.med.post(f"/api/v1/report/reports/{rid}/review/return",
                                       json={"note": "x"}).status_code, 403)
        r = self.med2.post(f"/api/v1/report/reports/{rid}/review/return", json={"note": "Descreva o baço."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["status"], r.json()["review"]["note"]), ("draft", "Descreva o baço."))
        # autora corrige e reenvia; revisor ajusta o texto e libera com a assinatura dele
        self.med.put(f"/api/v1/report/reports/{rid}", json={"body": "<p>Rascunho com baço.</p>",
                                                           "body_format": "html"})
        self.assertEqual(self.med.post(f"/api/v1/report/reports/{rid}/review",
                                       json={"reviewer_id": self.pid2}).status_code, 200)
        r = self.med2.put(f"/api/v1/report/reports/{rid}", json={"body": "<p>Rascunho com baço revisado.</p>",
                                                                "body_format": "html"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.med2.post(f"/api/v1/report/reports/{rid}/finalize", json={"password": PW})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["status"], "final")
        v = d["versions"][0]
        self.assertEqual(v["signed_by"], "Dr. Segundo Teste — CRM 65432/PB")
        self.assertEqual(v["author"], "Dra. Medica Teste")                         # quem redigiu e pediu revisão
        self.assertEqual(v["reviewer"], "Dr. Segundo Teste — CRM 65432/PB")         # quem revisou (e liberou)
        self.assertTrue(self.med.get(f"/api/v1/report/reports/{rid}/verify").json()["valid"])
        ch = v["changes"]
        self.assertEqual((ch["review_rounds"], ch["returns"], ch["reviewer_edited"]), (2, 1, True))
        self.assertEqual((ch["reviewer_added_lines"], ch["reviewer_removed_lines"]), (1, 1))
        self.assertEqual(ch["editors"], ["medica", "medico2"])
        from pypdf import PdfReader
        pdf = self.med.get(f"/api/v1/report/reports/{rid}/pdf")
        txt = " ".join(pg.extract_text() for pg in PdfReader(io.BytesIO(pdf.content)).pages).replace("\n", " ")
        self.assertIn("Redigido por Dra. Medica Teste. Revisado e liberado por Dr. Segundo Teste", txt)
        self.assertIn("Não é assinatura digital ICP-Brasil", txt)
        # integridade: alterar o revisor registrado é detectado pela verificação
        from sqlalchemy import create_engine, text as sql
        from tests_platform.support import urls
        eng = create_engine(urls().owner.replace("postgresql://", "postgresql+psycopg://", 1))
        try:
            with eng.begin() as cx:
                cx.execute(sql("SELECT set_config('vyonix.tenant_id', :t, true)"), {"t": str(self.t)})
                cx.execute(sql("UPDATE report.report_versions SET reviewer = 'Outra Pessoa' WHERE report_id = :r"),
                           {"r": rid})
        finally:
            eng.dispose()
        self.assertFalse(self.med.get(f"/api/v1/report/reports/{rid}/verify").json()["valid"])
        self.assertEqual(v["body"], "<p>Rascunho com baço revisado.</p>")
        events = [x["event"] for x in self.med.get(f"/api/v1/report/reports/{rid}/revisions").json()["items"]]
        self.assertEqual(events, ["save", "review_request", "return", "save", "review_request", "save"])
        from vyonix.audit import service as audit
        with db.session(self.t) as s:
            self.assertEqual(len(audit.query(s, action="report.review.request")), 2)
            self.assertEqual(len(audit.query(s, action="report.review.return")), 1)
            fin = audit.query(s, action="report.finalize")
            self.assertEqual(fin[0].details["reviewed_from"], "Dra. Medica Teste")

    def test_review_without_named_reviewer_and_batch_skips_review(self):
        rep = self.open(self.med)
        rid = rep["id"]
        self.med.put(f"/api/v1/report/reports/{rid}", json={"body": "Texto simples."})
        self.assertEqual(self.med.post(f"/api/v1/report/reports/{rid}/review", json={}).status_code, 200)
        # sem report.review ninguém revisa (médico comum não devolve nem libera)
        self.assertEqual(self.med2.post(f"/api/v1/report/reports/{rid}/review/return",
                                        json={"note": "x"}).status_code, 403)
        self.assertEqual(self.med2.post(f"/api/v1/report/reports/{rid}/finalize",
                                        json={"password": PW}).status_code, 409)
        r = self.med.post("/api/v1/report/reports/finalize-batch", json={"report_ids": [rid], "password": PW,
                                                                          "confirm": True})
        self.assertEqual(r.json()["released"], 0)
        self.assertEqual(self.med.get(f"/api/v1/report/reports/{rid}").json()["status"], "review")
        wl = self.med.get("/api/v1/report/worklist", params={"status": "review"}).json()["items"]
        self.assertEqual([x["report_id"] for x in wl], [rid])


class PhrasesMore(EditorBase):
    def test_duplicate_category_search_favorites_and_own_shortcuts(self):
        inst = self.admin.post("/api/v1/report/phrases", json={
            "title": "Fígado normal", "shortcut": "figado", "category": "Abdome", "personal": False,
            "body": "<p>Fígado de <strong>dimensões normais</strong>, medindo [[medida em cm]] cm, em {{paciente.nome}}.</p>"})
        self.assertEqual(inst.status_code, 201, inst.text)
        inst = inst.json()
        self.assertEqual(inst["variables"], ["medida em cm"])
        self.assertEqual(self.admin.post("/api/v1/report/phrases", json={"title": "X", "body": "{{paciente.cpf}}",
                                                                         "personal": False}).status_code, 422)
        mine = self.med.post("/api/v1/report/phrases", json={"title": "Baço", "category": "Abdome",
                                                             "body": "Baço homogêneo."}).json()
        self.med.post("/api/v1/report/phrases", json={"title": "Pulmões", "category": "Tórax", "body": "Pulmões livres."})
        # duplicar a da instituição vira pessoal e editável
        dup = self.med.post(f"/api/v1/report/phrases/{inst['id']}/duplicate")
        self.assertEqual(dup.status_code, 201, dup.text)
        dup = dup.json()
        self.assertEqual((dup["title"], dup["personal"], dup["category"], dup["shortcut"]),
                         ("Fígado normal (cópia)", True, "Abdome", None))
        self.assertIn("<strong>dimensões normais</strong>", dup["body"])
        r = self.med.put(f"/api/v1/report/phrases/{dup['id']}", json={"title": "Fígado (meu)", "body": "Fígado ok.",
                                                                     "category": "Abdome"})
        self.assertEqual(r.status_code, 200, r.text)
        # favorita e atalho próprio para a frase da instituição (só para mim)
        r = self.med.put(f"/api/v1/report/phrases/{inst['id']}/prefs", json={"favorite": True, "shortcut": "fig"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["shortcut"], r.json()["phrase_shortcut"], r.json()["favorite"]),
                         ("/fig", "/figado", True))
        self.assertEqual(self.med.put(f"/api/v1/report/phrases/{mine['id']}/prefs",
                                      json={"shortcut": "/figado"}).status_code, 409)   # atalho de frase da instituição
        items = self.med.get("/api/v1/report/phrases").json()
        self.assertEqual(items["items"][0]["title"], "Fígado normal")                 # favoritas primeiro
        self.assertEqual(items["categories"], ["Abdome", "Tórax"])
        other = {x["title"]: x for x in self.med2.get("/api/v1/report/phrases").json()["items"]}
        self.assertEqual((other["Fígado normal"]["shortcut"], other["Fígado normal"]["favorite"]), ("/figado", False))
        self.assertEqual(list(other), ["Fígado normal"])                              # pessoais dos outros não aparecem
        q = lambda **p: [x["title"] for x in self.med.get("/api/v1/report/phrases", params=p).json()["items"]]
        self.assertEqual(q(q="homogêneo"), ["Baço"])
        self.assertEqual(q(category="tórax"), ["Pulmões"])
        self.assertEqual(q(favorites=True), ["Fígado normal"])
        self.assertEqual(q(scope="own"), ["Baço", "Fígado (meu)", "Pulmões"])
        # sem report.phrases.own não duplica; favoritar exige report.write
        with db.session(self.t) as s:
            from vyonix.auth import service as auth
            auth.save_role(s, code="leitor", name="Leitor", permissions=["report.read"], actor="t")
        leitor = self.user(self.admin, "leitor1", "leitor")
        self.assertEqual(leitor.post(f"/api/v1/report/phrases/{inst['id']}/duplicate").status_code, 403)
        self.assertEqual(leitor.put(f"/api/v1/report/phrases/{inst['id']}/prefs", json={"favorite": True}).status_code, 403)
        self.assertEqual(self.med2.put(f"/api/v1/report/phrases/{mine['id']}/prefs",
                                       json={"favorite": True}).status_code, 404)        # pessoal de outro
        # excluir a da instituição remove as preferências; a cópia pessoal continua
        self.assertEqual(self.admin.delete(f"/api/v1/report/phrases/{inst['id']}").status_code, 204)
        self.assertEqual(q(favorites=True), [])
        self.assertIn("Fígado (meu)", q())
        # campos do laudo para inserir frases
        rep = self.open(self.med)
        f = self.med.get(f"/api/v1/report/reports/{rep['id']}/fields").json()["fields"]
        self.assertEqual(f["paciente.nome"], "Laudo Sintetico Teste")
        self.assertEqual(self.med2.get(f"/api/v1/report/reports/{rep['id']}/fields").status_code, 200)

    def test_other_institution_never_sees_phrases(self):
        from tests_platform.support import new_org
        from vyonix.report import phrases
        self.admin.post("/api/v1/report/phrases", json={"title": "Só desta clínica", "body": "x", "personal": False})
        other = new_org(db)
        with db.session(other) as s:
            self.assertEqual(phrases.listing(s, user_id=None), [])


class PersonalTemplates(EditorBase):
    def test_export_import_propose_and_admin_summary(self):
        r = self.med.post("/api/v1/report/templates", json={"name": "Meu TC", "personal": True, "content_format": "html",
                                                            "findings": "<p><em>Achado</em> pessoal</p>"})
        self.assertEqual(r.status_code, 201, r.text)
        tid = r.json()["id"]
        exp = self.med.get("/api/v1/report/templates/mine/export")
        self.assertEqual(exp.status_code, 200, exp.text)
        self.assertIn("attachment", exp.headers["content-disposition"])
        data = exp.json()
        self.assertEqual([t["name"] for t in data["templates"]], ["Meu TC"])
        self.assertEqual(self.med2.get("/api/v1/report/templates/mine/export").json()["templates"], [])  # só os próprios
        # adulterado: recusado
        bad = json.loads(json.dumps(data))
        bad["templates"][0]["findings"] = "<p>alterado</p>"
        self.assertEqual(self.med2.post("/api/v1/report/templates/mine/import", content=json.dumps(bad)).status_code, 422)
        # recuperação (ex.: nova conta do mesmo médico): rascunhos pessoais, formatação preservada
        r = self.med2.post("/api/v1/report/templates/mine/import", content=json.dumps(data))
        self.assertEqual(r.status_code, 201, r.text)
        new = r.json()["created"][0]
        self.assertEqual(new["name"], "Meu TC (importado)")
        items = {x["name"]: x for x in self.med2.get("/api/v1/report/templates").json()["items"]}
        self.assertTrue(items["Meu TC (importado)"]["personal"])
        self.assertEqual(items["Meu TC (importado)"]["draft"]["findings"], "<p><em>Achado</em> pessoal</p>")
        self.assertNotIn("Meu TC", items)                                             # o original segue privado
        # proposta à instituição: cópia inativa em rascunho; o original continua pessoal
        r = self.med.post(f"/api/v1/report/templates/{tid}/propose")
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["name"], r.json()["active"], r.json()["status"]), ("Meu TC (proposta)", False, "draft"))
        self.assertEqual(self.med2.post(f"/api/v1/report/templates/{tid}/propose").status_code, 404)
        adm = {x["name"]: x for x in self.admin.get("/api/v1/report/templates",
                                                    params={"include_inactive": True}).json()["items"]}
        self.assertIn("Meu TC (proposta)", adm)
        self.assertNotIn("Meu TC", adm)
        self.assertFalse(adm["Meu TC (proposta)"]["personal"])
        # resumo do administrador: só quantidades
        summ = self.admin.get("/api/v1/report/templates/personal-summary").json()["items"]
        self.assertEqual(sorted((x["username"], x["count"]) for x in summ), [("medica", 1), ("medico2", 1)])
        self.assertNotIn("Meu TC", json.dumps(summ))


if __name__ == "__main__":
    unittest.main()
