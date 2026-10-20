"""F1-07 — eventos com filtros, redação e exportação CSV."""

import csv
from datetime import timedelta

from app.database.repositories.events_repo import Category, EventFilter
from app.utils.timeutil import utc_now
from tests.helpers import DatabaseTestCase


class EventsTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.db.connection().execute(
            "INSERT INTO devices(id, name, ae_title, created_at, updated_at) VALUES (7,'CT','CT1','a','b')")
        add = self.events.add
        add(level="INFO", category=Category.SYSTEM, action="app.start", message="início")
        add(level="WARNING", category=Category.DICOM, action="assoc.reject", message="AE recusado",
            device_id=7)
        add(level="ERROR", category=Category.SPOOLER, action="spool.fail", message="100% falhou_x")

    def test_filters(self):
        q = self.events.query
        self.assertEqual(len(q()), 3)
        self.assertEqual([e.action for e in q(EventFilter(min_level="WARNING"))],
                         ["spool.fail", "assoc.reject"])
        self.assertEqual(len(q(EventFilter(categories=(Category.DICOM,)))), 1)
        self.assertEqual(q(EventFilter(device_id=7))[0].action, "assoc.reject")
        self.assertEqual(len(q(EventFilter(start=utc_now() + timedelta(minutes=1)))), 0)
        self.assertEqual(len(q(EventFilter(end=utc_now() - timedelta(days=1)))), 0)
        self.assertEqual(self.events.count(EventFilter(min_level="ERROR")), 1)

    def test_text_search_escapes_wildcards(self):
        self.assertEqual(len(self.events.query(EventFilter(text="100%"))), 1)
        self.assertEqual(len(self.events.query(EventFilter(text="u_x"))), 1)
        self.assertEqual(len(self.events.query(EventFilter(text="A_ recusado"))), 0)  # "_" literal
        self.assertEqual(len(self.events.query(EventFilter(text="%"))), 1)

    def test_phi_is_redacted_on_write(self):
        self.events.add(level="INFO", category=Category.DICOM, action="store",
                        message="PatientName=SILVA^ANA recebido",
                        details={"PatientID": "999", "modality": "CT"})
        e = self.events.query(EventFilter(categories=(Category.DICOM,), text="recebido"))[0]
        self.assertNotIn("SILVA", e.message)
        self.assertEqual(e.details["PatientID"], "***")
        self.assertEqual(e.details["modality"], "CT")

    def test_invalid_level_rejected(self):
        with self.assertRaises(ValueError):
            self.events.add(level="TRACE", category="x", action="y", message="z")

    def test_export_csv(self):
        path = self.tmp / "out" / "eventos.csv"
        n = self.events.export_csv(path, EventFilter(limit=1000))
        self.assertEqual(n, 3)
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh, delimiter=";"))
        self.assertEqual(rows[0][0], "id")
        self.assertEqual(len(rows), 4)

    def test_purge(self):
        self.db.connection().execute("UPDATE events SET ts='2000-01-01T00:00:00.000Z' WHERE id=1")
        self.assertEqual(self.events.purge_older_than(30), 1)
        self.assertEqual(self.events.count(), 2)
