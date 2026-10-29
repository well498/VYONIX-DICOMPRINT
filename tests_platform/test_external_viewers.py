"""Visualizadores externos — prova de conceito isolada (dados sintéticos; motor dublê do PACS).

Weasis: link ``weasis://`` só com código de manifesto de uso único; manifesto XML 2.5 com o estudo correto e a
credencial no ``httpTag``; WADO-URI só com o cabeçalho Authorization, só para o estudo da credencial, com
vencimento, revogação, permissão do usuário e isolamento entre organizações. Oviyam: desligado por padrão; quando
configurado, só o endereço do serviço (sem credencial). Ambos indisponíveis até o administrador ligar."""

from __future__ import annotations

import os
import unittest
import uuid
from urllib.parse import parse_qs, unquote_plus, urlparse
from xml.etree import ElementTree as ET

import tests_platform.test_viewer_launch as _vl
from tests_platform.pacs_support import uid
from tests_platform.support import require_db

NS = {"m": "http://www.weasis.org/xsd/2.5"}


def setUpModule():
    global db
    db = require_db()
    _vl.setUpModule()


class ExternalViewers(_vl.ViewerLaunch):
    test_protocols_comparison_and_priors = test_linked_access_limits_dicomweb_and_comparison = None
    test_patient_history_integrated_without_duplicates = None

    def enable(self, **kw):
        from vyonix.settings import service as settings
        with db.session(self.t) as s:
            cur = settings.get(s, "pacs", "external_viewers")
            settings.put(s, "pacs", "external_viewers", {**cur, **kw}, actor="admin", reason="prova de conceito")

    def weasis(self, c, sid):
        return c.post("/api/v1/pacs/external/weasis/launch", params={"study_uid": self.U[sid]})

    def manifest_path(self, uri: str) -> str:
        self.assertTrue(uri.startswith("weasis://?"), uri)
        cmd = unquote_plus(uri[len("weasis://?"):])
        self.assertTrue(cmd.startswith('$dicom:get -w "') and cmd.endswith('"'), cmd)
        url = cmd[len('$dicom:get -w "'):-1]
        self.assertNotIn("Bearer", url)
        return urlparse(url).path

    def test_weasis_manifest_wado_and_security(self):
        av = self.ana.get("/api/v1/pacs/external/viewers").json()
        self.assertEqual((av["weasis"]["available"], av["oviyam"]["available"], av["vyonix"]["available"]),
                         (False, False, True))                                  # desligados por padrão
        r = self.weasis(self.ana, self.cur)
        self.assertEqual((r.status_code, r.json()["error"]), (409, "viewer_unavailable"))
        self.enable(weasis_enabled=True, weasis_access_minutes=30)
        self.assertIn(self.ana.get(f"/api/v1/pacs/external/weasis/launch?study_uid={self.U[self.cur]}").status_code,
                      (404, 405))                                               # só POST (com anti-CSRF)
        r = self.weasis(self.ana, self.cur)
        self.assertEqual(r.status_code, 200, r.text)
        path = self.manifest_path(r.json()["uri"])
        anon = self.anon()
        m = anon.get(path)                                                      # o Weasis não tem a sessão
        self.assertEqual((m.status_code, m.headers["content-type"].split(";")[0]), (200, "application/xml"), m.text)
        self.assertEqual(m.headers["cache-control"], "no-store")
        root = ET.fromstring(m.content)
        xsd = os.environ.get("VYONIX_WEASIS_XSD")                               # manifest.xsd do Weasis (opcional)
        if xsd:
            from lxml import etree
            schema = etree.XMLSchema(etree.parse(xsd))
            self.assertTrue(schema.validate(etree.fromstring(m.content)), schema.error_log)
        arc = root.find("m:arcQuery", NS)
        self.assertTrue(arc.get("baseUrl").endswith("/api/v1/pacs/external/wado"))
        auth = arc.find("m:httpTag", NS)
        self.assertEqual(auth.get("key"), "Authorization")
        bearer = auth.get("value")
        self.assertTrue(bearer.startswith("Bearer "))
        st = arc.find("m:Patient/m:Study", NS)
        self.assertEqual(st.get("StudyInstanceUID"), self.U[self.cur])          # estudo correto, UID original
        self.assertEqual(arc.find("m:Patient", NS).get("PatientID"), "PREP1")             # PatientID DICOM original
        ser = st.findall("m:Series", NS)
        self.assertEqual(len(ser), 1)
        sops = [i.get("SOPInstanceUID") for i in ser[0].findall("m:Instance", NS)]
        self.assertEqual(sops, [uid(73, 1, 1), uid(73, 1, 2)])
        self.assertEqual(anon.get(path).status_code, 401)                       # código de uso único
        # WADO-URI com a credencial no cabeçalho
        w = {"requestType": "WADO", "studyUID": self.U[self.cur], "seriesUID": uid(73, 1), "objectUID": sops[0],
             "contentType": "application/dicom"}
        H = {"Authorization": bearer}
        r = anon.get("/api/v1/pacs/external/wado", params=w, headers=H)
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "application/dicom"), r.text)
        from pydicom import dcmread
        import io
        self.assertEqual(dcmread(io.BytesIO(r.content)).SOPInstanceUID, sops[0])
        self.assertEqual(anon.get("/api/v1/pacs/external/wado", params=w).status_code, 401)        # sem cabeçalho
        self.assertEqual(anon.get("/api/v1/pacs/external/wado",
                                  params={**w, "token": bearer[7:]}).status_code, 422)            # credencial na URL
        other = {**w, "studyUID": self.U[self.old_a], "seriesUID": uid(71, 1), "objectUID": uid(71, 1, 1)}
        self.assertEqual(anon.get("/api/v1/pacs/external/wado", params=other, headers=H).status_code, 403)
        forged = bearer[:-4] + ("AAAA" if not bearer.endswith("AAAA") else "BBBB")
        self.assertEqual(anon.get("/api/v1/pacs/external/wado", params=w,
                                  headers={"Authorization": forged}).status_code, 401)
        # outra organização: a mesma credencial com o identificador de outra organização não vale
        from tests_platform.support import new_org
        other_org = new_org(db)
        tid, secret = bearer[7:].split(".", 1)
        self.assertEqual(anon.get("/api/v1/pacs/external/wado", params=w,
                                  headers={"Authorization": f"Bearer {other_org}.{secret}"}).status_code, 401)
        # auditoria: lançamento, manifesto e abertura (uma vez)
        from vyonix.audit import service as audit
        with db.session(self.t) as s:
            self.assertTrue(audit.query(s, action="pacs.viewer.external"))
            self.assertTrue(audit.query(s, action="pacs.viewer.external.manifest"))
        # vencimento e revogação
        from sqlalchemy import update
        from vyonix.db.base import utcnow
        from vyonix.pacs import external
        from vyonix.pacs.models import ViewerToken
        with db.session(self.t) as s:
            s.execute(update(ViewerToken).where(ViewerToken.kind == "access").values(expires_at=utcnow()))
        self.assertEqual(anon.get("/api/v1/pacs/external/wado", params=w, headers=H).status_code, 401)
        r = self.weasis(self.ana, self.cur)
        m = anon.get(self.manifest_path(r.json()["uri"]))
        b2 = ET.fromstring(m.content).find("m:arcQuery/m:httpTag", NS).get("value")
        self.assertEqual(anon.get("/api/v1/pacs/external/wado", params=w, headers={"Authorization": b2}).status_code, 200)
        with db.session(self.t) as s:
            external.revoke_user(s, uuid.UUID(self.docs["ana"][2]))
        self.assertEqual(anon.get("/api/v1/pacs/external/wado", params=w, headers={"Authorization": b2}).status_code, 401)
        # código de manifesto vencido
        r = self.weasis(self.ana, self.cur)
        with db.session(self.t) as s:
            s.execute(update(ViewerToken).where(ViewerToken.kind == "manifest", ViewerToken.used_at.is_(None))
                      .values(expires_at=utcnow()))
        self.assertEqual(anon.get(self.manifest_path(r.json()["uri"])).status_code, 401)

    def test_permissions_scope_and_user_state(self):
        self.enable(weasis_enabled=True)
        recep = self.user("recep2", ["recepcionista"])
        self.assertEqual(self.weasis(recep, self.cur).status_code, 403)       # sem permissão de abrir estudos
        self.assertEqual(self.weasis(self.ana, self.cur).status_code, 200)
        r = self.ana.post("/api/v1/pacs/external/weasis/launch", params={"study_uid": uid(99)})
        self.assertEqual(r.status_code, 404)                                    # estudo inexistente
        from vyonix.settings import service as settings
        with db.session(self.t) as s:
            settings.put(s, "pacs", "viewer", {"access": "linked", "allow_personal": True}, actor="admin")
        self.assertEqual(self.weasis(self.carla, self.old_b).status_code, 404)  # fora do vínculo da médica
        self.assertEqual(self.weasis(self.carla, self.cur).status_code, 200)
        # usuário desativado depois de receber o manifesto: o download para
        r = self.weasis(self.ana, self.cur)
        m = self.anon().get(self.manifest_path(r.json()["uri"]))
        bearer = ET.fromstring(m.content).find("m:arcQuery/m:httpTag", NS).get("value")
        w = {"requestType": "WADO", "studyUID": self.U[self.cur], "seriesUID": uid(73, 1), "objectUID": uid(73, 1, 1)}
        from sqlalchemy import update
        from vyonix.auth.models import User
        with db.session(self.t) as s:
            s.execute(update(User).where(User.id == uuid.UUID(self.docs["ana"][2])).values(active=False))
        self.assertIn(self.anon().get("/api/v1/pacs/external/wado", params=w,
                                      headers={"Authorization": bearer}).status_code, (401, 403))

    def test_oviyam_only_when_configured_without_credentials(self):
        r = self.ana.post("/api/v1/pacs/external/oviyam/launch", params={"study_uid": self.U[self.cur]})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "viewer_unavailable"))
        self.enable(oviyam_enabled=True)
        av = self.ana.get("/api/v1/pacs/external/viewers").json()["oviyam"]
        self.assertEqual((av["available"], av["reason"]), (False, "Não configurado."))
        from vyonix.errors import ValidationFailed
        from vyonix.settings import service as settings
        with db.session(self.t) as s:
            with self.assertRaises(ValidationFailed):                          # só HTTPS
                settings.put(s, "pacs", "external_viewers", {**settings.get(s, "pacs", "external_viewers"),
                                                             "oviyam_url": "http://ovi.invalid/oviyam2"}, actor="admin")
        self.enable(oviyam_enabled=True, oviyam_url="https://ovi.invalid:8443/oviyam2", oviyam_server_name="VYONIX")
        r = self.ana.post("/api/v1/pacs/external/oviyam/launch", params={"study_uid": self.U[self.cur]})
        self.assertEqual(r.status_code, 200, r.text)
        u = urlparse(r.json()["url"])
        self.assertEqual((u.scheme, u.netloc, u.path), ("https", "ovi.invalid:8443", "/oviyam2/viewer.html"))
        self.assertEqual(parse_qs(u.query), {"studyUID": [self.U[self.cur]], "serverName": ["VYONIX"]})
        self.assertNotIn("token", r.json()["url"].lower())                      # nenhuma credencial do VYONIX
        self.assertEqual(self.ana.post("/api/v1/pacs/external/desconhecido/launch",
                                       params={"study_uid": self.U[self.cur]}).status_code, 404)

    def anon(self):
        from fastapi.testclient import TestClient
        return TestClient(self.client.app)


if __name__ == "__main__":
    unittest.main()
