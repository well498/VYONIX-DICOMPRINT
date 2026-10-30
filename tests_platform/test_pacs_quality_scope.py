"""A03-001 (auditoria 29/10/2026): com ``pacs/viewer.access = linked`` as rotas de qualidade revelavam estudos fora do
vínculo do médico (UID, data, accession, problemas), embora o DICOMweb respondesse 404 para os mesmos estudos."""

import unittest

import tests_platform.test_viewer_launch as V

setUpModule = V.setUpModule


class QualityScope(V.ViewerLaunch):
    locals().update({n: None for n in dir(V.ViewerLaunch) if n.startswith("test_")})   # só a preparação

    def test_quality_routes_follow_linked_scope(self):
        from vyonix.settings import service as settings
        with V.db.session(self.t) as s:
            settings.put(s, "pacs", "viewer", {"access": "linked", "allow_personal": True}, actor="admin",
                         reason="teste")
        out_uid = self.U[self.old_b]                                      # fora do vínculo da carla
        lst = self.carla.get("/api/v1/pacs/quality", params={"only_issues": "false"})
        self.assertEqual(lst.status_code, 200)
        self.assertNotIn(out_uid, [x["study_uid"] for x in lst.json()["studies"]])
        self.assertEqual(self.carla.get(f"/api/v1/pacs/studies/{out_uid}/quality").status_code, 404)
        self.assertEqual(self.carla.get(f"/api/v1/pacs/dicomweb/studies/{out_uid}/metadata").status_code, 404)
        self.assertEqual(self.admin.get(f"/api/v1/pacs/studies/{out_uid}/quality").status_code, 200)   # admin vê


if __name__ == "__main__":
    unittest.main()
