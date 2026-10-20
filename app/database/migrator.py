"""Aplicação de migrações de esquema.

Garantias:

* cada migração é aplicada de forma **atômica** (DDL + registro da versão na mesma
  transação) — uma interrupção nunca deixa o esquema pela metade;
* idempotente: migrações já aplicadas são ignoradas;
* o *checksum* (SHA-256) de cada migração aplicada é conferido em toda inicialização;
* um banco mais novo que a aplicação (downgrade) é recusado;
* um backup é gerado antes de migrar um banco que já contém dados.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app.core.errors import MigrationError
from app.database.connection import Database
from app.utils.logging_setup import get_logger
from app.utils.timeutil import utc_now, utc_now_iso

log = get_logger("database.migrations")

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    checksum   TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""

MAX_PRE_MIGRATION_BACKUPS = 5


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.strip().encode("utf-8")).hexdigest()


def _validate_sequence(migrations: Sequence[Migration]) -> None:
    for expected, migration in enumerate(migrations, start=1):
        if migration.version != expected:
            raise MigrationError(
                f"Sequência de migrações inválida: esperado v{expected}, encontrado v{migration.version}."
            )


def applied_versions(db: Database) -> dict[int, str]:
    conn = db.connection()
    conn.execute(_BOOTSTRAP)
    return {row["version"]: row["checksum"] for row in conn.execute(
        "SELECT version, checksum FROM schema_migrations ORDER BY version")}


def current_version(db: Database) -> int:
    versions = applied_versions(db)
    return max(versions) if versions else 0


def pending(db: Database, migrations: Sequence[Migration]) -> list[Migration]:
    applied = applied_versions(db)
    return [m for m in migrations if m.version not in applied]


def migrate(
    db: Database,
    migrations: Sequence[Migration],
    *,
    backup_dir: Path | None = None,
) -> list[int]:
    """Aplica as migrações pendentes e retorna as versões aplicadas."""
    _validate_sequence(migrations)
    applied = applied_versions(db)
    known = {m.version: m for m in migrations}

    newer = sorted(v for v in applied if v not in known)
    if newer:
        raise MigrationError(
            f"O banco está na versão de esquema {max(newer)}, mais nova que esta aplicação "
            f"(máx. {len(migrations)}). Atualize o VYONIX ou restaure um backup compatível."
        )
    for version, checksum in applied.items():
        if known[version].checksum != checksum:
            raise MigrationError(
                f"A migração v{version} aplicada no banco difere da distribuída com a aplicação "
                "(checksum divergente). O banco pode ter sido alterado manualmente."
            )

    todo = [m for m in migrations if m.version not in applied]
    if not todo:
        return []

    if applied and backup_dir is not None:
        _pre_migration_backup(db, backup_dir, max(applied))

    conn = db.connection()
    done: list[int] = []
    for migration in todo:
        log.info("Aplicando migração", extra={"version": migration.version, "migration": migration.name})
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{migration.sql}\n;\n"
            "INSERT INTO schema_migrations(version, name, checksum, applied_at) "
            f"VALUES ({int(migration.version)}, {_quote(migration.name)}, "
            f"{_quote(migration.checksum)}, {_quote(utc_now_iso())});\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise MigrationError(f"Falha ao aplicar migração v{migration.version}: {exc}") from exc
        done.append(migration.version)
    return done


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _pre_migration_backup(db: Database, backup_dir: Path, from_version: int) -> Path:
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"vyonix-pre-migration-v{from_version}-{stamp}.db"
    db.backup_to(target)
    backups = sorted(backup_dir.glob("vyonix-pre-migration-*.db"))
    for old in backups[:-MAX_PRE_MIGRATION_BACKUPS]:
        try:
            old.unlink()
        except OSError:  # pragma: no cover
            log.warning("Não foi possível remover backup antigo", extra={"backup_file": str(old)})
    return target
