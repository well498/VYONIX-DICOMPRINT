"""Utilitários de teste: cada teste usa uma pasta de dados isolada e descartável."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.database.connection import Database
from app.database.migrations import MIGRATIONS
from app.database.migrator import migrate
from app.database.repositories.events_repo import EventRepository
from app.utils.logging_setup import shutdown_logging


class TempDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vyonix-test-"))

    def tearDown(self) -> None:
        shutdown_logging()
        shutil.rmtree(self.tmp, ignore_errors=True)


class DatabaseTestCase(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db = Database(self.tmp / "test.db")
        migrate(self.db, MIGRATIONS)
        self.events = EventRepository(self.db)

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()
