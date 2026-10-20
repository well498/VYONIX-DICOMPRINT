"""F1-05 — logs JSON, histórico preservado, nível ao vivo, redação de PHI."""

import json

from app.security.redaction import MASK, redact, redact_text
from app.utils.logging_setup import get_logger, set_log_level, setup_logging, shutdown_logging
from tests.helpers import TempDirTestCase

PYDICOM_DUMP = """(0008,0060) Modality                            CS: 'CT'
(0010,0010) Patient's Name                      PN: 'SILVA^MARIA'
(0010,0020) Patient ID                          LO: '123456'
(0008,0050) Accession Number                    SH: 'ACC77'"""


class RedactionTest(TempDirTestCase):
    def test_keyword_pairs(self):
        out = redact_text("Falha PatientName=SILVA^MARIA, PatientID: 123 modality=CT")
        self.assertNotIn("SILVA", out)
        self.assertNotIn("123", out)
        self.assertIn("modality=CT", out)

    def test_pydicom_dump(self):
        out = redact_text(PYDICOM_DUMP)
        for secret in ("SILVA", "123456", "ACC77"):
            self.assertNotIn(secret, out)
        self.assertIn("'CT'", out)

    def test_nested_structures(self):
        out = redact({"patient_name": "X", "ok": [{"PatientID": "9"}, "Patient ID: 77"],
                      "cpf": "000.000.000-00", "modality": "MR"})
        self.assertEqual(out["patient_name"], MASK)
        self.assertEqual(out["ok"][0]["PatientID"], MASK)
        self.assertNotIn("77", out["ok"][1])
        self.assertEqual(out["cpf"], MASK)
        self.assertEqual(out["modality"], "MR")


class LoggingTest(TempDirTestCase):
    def read(self, path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_json_lines_with_redaction(self):
        path = setup_logging(self.tmp, "ui")
        log = get_logger("test")
        log.info("Recebido PatientName=DOE^JOHN", extra={"PatientID": "42", "ae": "CT01"})
        try:
            raise ValueError(PYDICOM_DUMP)
        except ValueError:
            log.exception("erro")
        shutdown_logging()
        records = self.read(path)
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("DOE", text)
        self.assertNotIn("SILVA", text)
        self.assertNotIn('"42"', text)
        self.assertEqual(records[0]["data"]["ae"], "CT01")
        self.assertEqual(records[0]["role"], "ui")
        self.assertIn("exc", records[1])

    def test_history_is_appended_not_overwritten(self):
        path = setup_logging(self.tmp, "ui")
        get_logger("t").info("primeira execução")
        shutdown_logging()
        setup_logging(self.tmp, "ui")
        get_logger("t").info("segunda execução")
        shutdown_logging()
        msgs = [r["msg"] for r in self.read(path)]
        self.assertEqual(msgs, ["primeira execução", "segunda execução"])

    def test_level_changes_without_restart(self):
        path = setup_logging(self.tmp, "ui", level="WARNING")
        get_logger("t").info("oculto")
        set_log_level("DEBUG")
        get_logger("t").debug("visível")
        shutdown_logging()
        self.assertEqual([r["msg"] for r in self.read(path)], ["visível"])

    def test_rotation(self):
        path = setup_logging(self.tmp, "svc", max_bytes=2000, backup_count=3)
        for i in range(200):
            get_logger("t").info("linha %d %s", i, "x" * 50)
        shutdown_logging()
        self.assertTrue(path.with_name(path.name + ".1").exists())
        self.assertFalse(path.with_name(path.name + ".4").exists())
