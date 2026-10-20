"""F1-04 — integridade, transações e conexões por thread."""

import threading

from app.core.errors import DatabaseError, DatabaseIntegrityError
from app.database.connection import Database
from tests.helpers import DatabaseTestCase, TempDirTestCase


class DatabaseTest(DatabaseTestCase):
    def test_wal_and_foreign_keys(self):
        conn = self.db.connection()
        self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_transaction_rollback(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction() as c:
                c.execute("INSERT INTO settings VALUES ('a', '1', 'x', 'y')")
                raise RuntimeError("falha")
        self.assertIsNone(self.db.connection().execute(
            "SELECT 1 FROM settings WHERE key='a'").fetchone())

    def test_nested_transaction_uses_savepoint(self):
        with self.db.transaction() as c:
            c.execute("INSERT INTO settings VALUES ('outer', '1', 'x', 'y')")
            try:
                with self.db.transaction() as c2:
                    c2.execute("INSERT INTO settings VALUES ('inner', '1', 'x', 'y')")
                    raise ValueError
            except ValueError:
                pass
        keys = {r[0] for r in self.db.connection().execute("SELECT key FROM settings")}
        self.assertEqual(keys, {"outer"})

    def test_each_thread_gets_its_own_connection(self):
        main = self.db.connection()
        seen = []
        t = threading.Thread(target=lambda: seen.append(self.db.connection()))
        t.start()
        t.join()
        self.assertIsNot(seen[0], main)

    def test_integrity_check_passes(self):
        self.db.assert_integrity()

    def test_closed_database_refuses_use(self):
        self.db.close()
        with self.assertRaises(DatabaseError):
            self.db.connection()


class CorruptionTest(TempDirTestCase):
    def test_corrupted_file_is_detected(self):
        path = self.tmp / "bad.db"
        path.write_bytes(b"isto nao e um banco sqlite" * 200)
        db = Database(path)
        try:
            with self.assertRaises((DatabaseIntegrityError, DatabaseError)):
                db.connection()
                db.assert_integrity()
        finally:
            db.close()
