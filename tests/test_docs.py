"""A documentação de entrega acompanha o código (evita declaração de conformidade desatualizada)."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "release"


class DocsTest(unittest.TestCase):
    def test_conformance_lists_every_storage_class(self):
        from app.dicom import sop
        text = (DOCS / "Declaracao_Conformidade_DICOM.md").read_text(encoding="utf-8")
        missing = [uid for uid in sop.IMAGE_STORAGE if f"`{uid}`" not in text]
        self.assertEqual(missing, [])
        for uid in ("1.2.840.10008.5.1.1.9", "1.2.840.10008.5.1.1.18", "1.2.840.10008.5.1.1.23"):
            self.assertIn(uid, text)

    def test_release_docs_have_no_stale_phase_markers(self):
        for md in DOCS.glob("*.md"):
            text = md.read_text(encoding="utf-8")
            for stale in ("Não implementado — Fase", "Previsto na Fase", "será entregue na"):
                self.assertNotIn(stale, text, f"{md.name}: '{stale}'")
