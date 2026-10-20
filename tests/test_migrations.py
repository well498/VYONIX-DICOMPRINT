"""F1-03 — esquema, atomicidade, idempotência, checksum, downgrade e backup."""

import sqlite3

from app.core.errors import MigrationError
from app.database.connection import Database
from app.database.migrations import MIGRATIONS
from app.database.migrator import Migration, current_version, migrate
from tests.helpers import TempDirTestCase

EXPECTED_TABLES = {
    "schema_migrations", "settings", "change_history", "events", "printers", "print_profiles",
    "profile_bindings", "devices", "rules", "instances", "print_sessions", "jobs", "job_items",
    "job_state_history", "licenses",
}


class MigrationsTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.db = Database(self.tmp / "m.db")

    def tearDown(self):
        self.db.close()
        super().tearDown()

    def tables(self):
        return {r[0] for r in self.db.connection().execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}

    def test_initial_schema_has_all_entities(self):
        self.assertEqual(migrate(self.db, MIGRATIONS), [1])
        self.assertTrue(EXPECTED_TABLES.issubset(self.tables()))
        self.assertEqual(current_version(self.db), 1)

    def test_idempotent(self):
        migrate(self.db, MIGRATIONS)
        self.assertEqual(migrate(self.db, MIGRATIONS), [])

    def test_failed_migration_is_atomic(self):
        migrate(self.db, MIGRATIONS)
        bad = MIGRATIONS + (Migration(2, "broken",
                                      "CREATE TABLE half_done(id INTEGER); INSERT INTO nope VALUES (1);"),)
        with self.assertRaises(MigrationError):
            migrate(self.db, bad)
        self.assertNotIn("half_done", self.tables())
        self.assertEqual(current_version(self.db), 1)

    def test_checksum_mismatch_is_rejected(self):
        migrate(self.db, MIGRATIONS)
        altered = (Migration(1, "initial", MIGRATIONS[0].sql + "\n-- alterado"),)
        with self.assertRaises(MigrationError):
            migrate(self.db, altered)

    def test_newer_database_is_rejected(self):
        migrate(self.db, MIGRATIONS)
        self.db.connection().execute(
            "INSERT INTO schema_migrations VALUES (99, 'future', 'x', '2030-01-01T00:00:00.000Z')")
        with self.assertRaises(MigrationError):
            migrate(self.db, MIGRATIONS)

    def test_backup_before_migrating_existing_database(self):
        migrate(self.db, MIGRATIONS)
        backups = self.tmp / "backups"
        extra = MIGRATIONS + (Migration(2, "extra", "CREATE TABLE t2(id INTEGER);"),)
        self.assertEqual(migrate(self.db, extra, backup_dir=backups), [2])
        files = list(backups.glob("vyonix-pre-migration-v1-*.db"))
        self.assertEqual(len(files), 1)
        conn = sqlite3.connect(files[0])
        self.assertEqual(conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 1)
        conn.close()

    def test_sequence_must_be_contiguous(self):
        with self.assertRaises(MigrationError):
            migrate(self.db, (Migration(2, "gap", "SELECT 1;"),))

    def test_constraints_are_enforced(self):
        migrate(self.db, MIGRATIONS)
        conn = self.db.connection()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO settings VALUES ('k', 'not json', 'x', 'y')")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO devices(name, ae_title, created_at, updated_at) "
                         "VALUES ('x', 'MUITO_LONGO_AE_TITLE', 'a', 'b')")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO job_items(job_id, position) VALUES (999, 0)")  # FK ativa
