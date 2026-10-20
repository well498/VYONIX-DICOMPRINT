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


class PythonJsonFallbackTest(TempDirTestCase):
    """SQLite sem JSON1 (Python 3.8 para Windows): a função em Python mantém o esquema válido."""

    def test_full_schema_with_python_json_valid(self):
        import os
        import sqlite3

        from app.database.connection import ENV_FORCE_PY_JSON
        from app.database.migrations import MIGRATIONS
        from app.database.migrator import migrate

        os.environ[ENV_FORCE_PY_JSON] = "1"
        try:
            db = Database(self.tmp / "py-json.db")
            self.assertEqual(migrate(db, MIGRATIONS), [1])
            self.assertEqual(db.json_mode, "python")
            conn = db.connection()
            conn.execute("INSERT INTO settings VALUES ('ok', '{\"a\": [1, 2]}', 'x', 'y')")
            for bad in ("not json", "{'a': 1}", ""):
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute("INSERT INTO settings VALUES ('bad', ?, 'x', 'y')", (bad,))
            conn.execute("INSERT INTO events(ts, level, category, action, message, details_json) "
                         "VALUES ('t', 'INFO', 'c', 'a', 'm', NULL)")  # NULL continua permitido
            db.close()
        finally:
            os.environ.pop(ENV_FORCE_PY_JSON, None)

    def test_python_matches_native_semantics(self):
        import sqlite3

        from app.database.connection import _json_valid
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("SELECT json_valid('{}')")
        except sqlite3.OperationalError:
            self.skipTest("SQLite local sem JSON1 para comparar")
        for value in ('{}', '[]', '1', '"x"', 'null', 'not json', '{"a":', "{'a':1}", "",
                      '{"a": [1, {"b": null}]}', ' {} '):
            native = conn.execute("SELECT json_valid(?)", (value,)).fetchone()[0]
            self.assertEqual(_json_valid(value), native, value)
        conn.close()


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
