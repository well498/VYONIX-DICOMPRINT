"""Consultas agregadas somente-leitura usadas pelo Dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.database.connection import Database
from app.jobs.states import QUEUED, JobState
from app.utils.timeutil import to_iso, utc_now


@dataclass(frozen=True)
class RecentDevice:
    name: str
    ae_title: str
    modality: str | None
    last_seen_at: str


class StatsRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def devices_total(self) -> int:
        return self._scalar("SELECT COUNT(*) FROM devices WHERE active = 1")

    def devices_authorized(self) -> int:
        return self._scalar("SELECT COUNT(*) FROM devices WHERE active = 1 AND authorized = 1")

    def recent_devices(self, hours: int = 24, limit: int = 5) -> list[RecentDevice]:
        since = to_iso(utc_now() - timedelta(hours=hours))
        rows = self.db.connection().execute(
            """SELECT name, ae_title, modality, last_seen_at FROM devices
               WHERE active = 1 AND last_seen_at >= ? ORDER BY last_seen_at DESC LIMIT ?""",
            (since, limit)).fetchall()
        return [RecentDevice(**dict(r)) for r in rows]

    def jobs_created_since(self, hours: int = 24) -> int:
        since = to_iso(utc_now() - timedelta(hours=hours))
        return self._scalar("SELECT COUNT(*) FROM jobs WHERE created_at >= ?", (since,))

    def jobs_in_queue(self) -> int:
        states = [s.value for s in QUEUED]
        return self._scalar(
            f"SELECT COUNT(*) FROM jobs WHERE state IN ({','.join('?' * len(states))})", states)

    def jobs_spooled_since(self, hours: int = 24) -> int:
        since = to_iso(utc_now() - timedelta(hours=hours))
        return self._scalar(
            "SELECT COUNT(*) FROM jobs WHERE submitted_at >= ? AND state IN (?, ?)",
            (since, JobState.SPOOLED.value, JobState.COMPLETED.value))

    def jobs_failed_since(self, hours: int = 24) -> int:
        since = to_iso(utc_now() - timedelta(hours=hours))
        return self._scalar(
            "SELECT COUNT(*) FROM jobs WHERE state = ? AND updated_at >= ?",
            (JobState.FAILED.value, since))

    def printers_total(self) -> int:
        return self._scalar("SELECT COUNT(*) FROM printers WHERE active = 1")

    def active_license(self) -> bool:
        return self._scalar("SELECT COUNT(*) FROM licenses WHERE status = 'active'") > 0

    def _scalar(self, sql: str, params: tuple | list = ()) -> int:
        return int(self.db.connection().execute(sql, params).fetchone()[0])
