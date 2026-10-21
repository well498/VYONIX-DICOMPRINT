"""Banco do DEPLOY (SQLite em ProgramData\\VYONIX\\Deploy): execuções, passos, estados anteriores,
aprovações, eventos e relatórios. Independente do PostgreSQL (existe antes dele)."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  installation_id TEXT, host TEXT, os_user TEXT, config_json TEXT NOT NULL, inventory_json TEXT,
  compat_json TEXT, plan_json TEXT, plan_sha TEXT, approval_json TEXT, message TEXT, version TEXT
);
CREATE TABLE IF NOT EXISTS steps (
  run_id TEXT NOT NULL REFERENCES runs(id), seq INTEGER NOT NULL, step_id TEXT NOT NULL, category TEXT NOT NULL,
  title TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, before_json TEXT,
  after_json TEXT, verify_msg TEXT, error TEXT, started_at TEXT, finished_at TEXT, attempts INTEGER DEFAULT 0,
  PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, at TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL,
  sha256 TEXT NOT NULL, prev_sha256 TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DeployDB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self.c = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.execute("PRAGMA synchronous=FULL")          # sobrevive a queda de energia
        self.c.executescript(SCHEMA)

    def close(self) -> None:
        self.c.close()

    def x(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.c.execute(sql, args)

    def event(self, run_id: str | None, level: str, message: str) -> None:
        self.x("INSERT INTO events(run_id, at, level, message) VALUES (?,?,?,?)", (run_id, now(), level, message))

    def run(self, run_id: str) -> dict[str, Any] | None:
        r = self.x("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(r) if r else None

    def runs(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.x("SELECT id, kind, status, created_at, updated_at, message FROM runs "
                                        "ORDER BY created_at DESC LIMIT ?", (limit,))]

    def unfinished(self) -> dict | None:
        r = self.x("SELECT * FROM runs WHERE status IN ('approved','running') ORDER BY created_at DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    def steps(self, run_id: str) -> list[dict]:
        return [dict(r) for r in self.x("SELECT * FROM steps WHERE run_id = ? ORDER BY seq", (run_id,))]

    def set_run(self, run_id: str, **fields) -> None:
        fields["updated_at"] = now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.x(f"UPDATE runs SET {cols} WHERE id = ?", (*[_j(v) for v in fields.values()], run_id))

    def set_step(self, run_id: str, seq: int, **fields) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.x(f"UPDATE steps SET {cols} WHERE run_id = ? AND seq = ?", (*[_j(v) for v in fields.values()], run_id,
                                                                           seq))

    def meta(self, key: str, value: str | None = None) -> str | None:
        if value is not None:
            self.x("INSERT INTO meta(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                   (key, value))
            return value
        r = self.x("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else None


def _j(v: Any) -> Any:
    return json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else v
