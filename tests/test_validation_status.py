"""Classificação das verificações do instalador: "não verificável" nunca conta como aprovado (auditoria de 23/10)."""

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"


class ValidationStatusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(TOOLS))
        try:
            import make_release
        except ImportError as exc:                     # reportlab ausente no ambiente
            raise unittest.SkipTest(f"tools/make_release.py indisponível: {exc}") from exc
        cls.m = make_release

    def test_classification(self):
        v = self.m.v_status
        self.assertEqual(v({"ok": True, "detail": "instalado"}), "aprovado")
        self.assertEqual(v({"ok": False, "detail": "x"}), "falhou")
        # resultado antigo (r5): ok=True mas o detalhe diz que o ambiente não permitiu comprovar
        self.assertEqual(v({"ok": True, "detail": "NÃO VERIFICÁVEL nesta máquina (sem TPM utilizável)"}),
                         "nao_verificavel")
        self.assertEqual(v({"ok": True, "status": "nao_verificavel", "detail": ""}), "nao_verificavel")

    def test_report_counts_separately(self):
        validation = {"machine": {}, "results": [
            {"id": "A", "area": "x", "name": "a", "ok": True, "detail": "ok"},
            {"id": "LIC-02", "area": "Licenciamento", "name": "TPM", "ok": True,
             "detail": "NÃO VERIFICÁVEL nesta máquina"}]}
        junit = {"totals": {"aprovado": 1, "falhou": 0, "erro": 0, "ignorado": 0}, "total": 1, "cases": []}
        import tempfile
        setup = Path(tempfile.mkdtemp()) / "setup.exe"
        setup.write_bytes(b"x")
        text = self.m.validation_report("1.0.0", "abc", "hoje", setup, "00", junit, validation, "env")
        self.assertIn("1 aprovadas, 1 não verificáveis neste ambiente, 0 falhas (de 2)", text)
        self.assertIn("Não verificável neste ambiente", text)

    def test_ci_script_marks_status(self):
        ps = (TOOLS / "ci_validate.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('status = $status', ps)
        self.assertIn('"nao_verificavel"', ps)


if __name__ == "__main__":
    unittest.main()
