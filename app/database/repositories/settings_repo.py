"""Persistência de configurações (chave → JSON) e do histórico de alterações."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.database.connection import Database
from app.utils.timeutil import utc_now_iso


class SettingsRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_raw(self, key: str) -> Any | None:
        row = self.db.connection().execute(
            "SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
        return None if row is None else json.loads(row["value_json"])

    def has(self, key: str) -> bool:
        return self.db.connection().execute(
            "SELECT 1 FROM settings WHERE key = ?", (key,)).fetchone() is not None

    def all_raw(self) -> dict[str, Any]:
        rows = self.db.connection().execute("SELECT key, value_json FROM settings").fetchall()
        return {r["key"]: json.loads(r["value_json"]) for r in rows}

    def upsert(self, key: str, value: Any, actor: str) -> None:
        self.db.connection().execute(
            """INSERT INTO settings(key, value_json, updated_at, updated_by)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json,
                   updated_at = excluded.updated_at, updated_by = excluded.updated_by""",
            (key, json.dumps(value, ensure_ascii=False), utc_now_iso(), actor),
        )

    def delete(self, key: str) -> None:
        self.db.connection().execute("DELETE FROM settings WHERE key = ?", (key,))


@dataclass(frozen=True)
class ChangeRecord:
    id: int
    entity_type: str
    entity_id: str
    field: str
    old_value: str | None
    new_value: str | None
    changed_at: str
    changed_by: str
    reason: str | None


class ChangeHistoryRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, *, entity_type: str, entity_id: str, field: str, old_value: Any,
               new_value: Any, actor: str, reason: str | None = None) -> int:
        cur = self.db.connection().execute(
            """INSERT INTO change_history(entity_type, entity_id, field, old_value, new_value,
                                          changed_at, changed_by, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (entity_type, str(entity_id), field, _dump(old_value), _dump(new_value),
             utc_now_iso(), actor, reason),
        )
        return int(cur.lastrowid)

    def list(self, entity_type: str | None = None, entity_id: str | None = None,
             limit: int = 200) -> list[ChangeRecord]:
        sql = "SELECT * FROM change_history WHERE 1=1"
        params: list[Any] = []
        if entity_type:
            sql += " AND entity_type = ?"
            params.append(entity_type)
        if entity_id:
            sql += " AND entity_id = ?"
            params.append(entity_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        return [ChangeRecord(**dict(r)) for r in self.db.connection().execute(sql, params)]


def _dump(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)
