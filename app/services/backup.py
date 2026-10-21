"""Backup e restauração do banco de dados (equipamentos, perfis, regras, calibrações, histórico, filas).

* Backup: cópia consistente pela API de backup do SQLite (sem parar o serviço), verificada com
  ``PRAGMA integrity_check``; automático uma vez por dia e manual (Configurações ou ``--backup-now``).
* Restauração: ``Vyonix.exe --restore-backup <arquivo>`` (Prompt de Comando como administrador, com o
  serviço Windows parado). O arquivo é verificado (integridade, produto, versão de esquema não mais nova
  que o programa), o banco atual é guardado em ``backups`` e só então substituído. As imagens recebidas
  e os modelos BMP ficam fora do banco e não são alterados.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path

from app.core.errors import ValidationError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.utils.logging_setup import get_logger
from app.utils.timeutil import utc_now

log = get_logger("backup")

PREFIX = "vyonix-backup-"
KEEP = 14


class BackupService:
    def __init__(self, db: Database, events: EventRepository, backups_dir: Path) -> None:
        self.db = db
        self.events = events
        self.dir = Path(backups_dir)

    def create(self, *, actor: str = "system", label: str = "") -> Path:
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        target = self.dir / f"{PREFIX}{stamp}{('-' + label) if label else ''}.db"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db.backup_to(target)
        problems = verify(target)
        if problems:
            target.unlink(missing_ok=True)
            raise ValidationError(f"Backup gerado com problemas e descartado: {problems}")
        self.prune()
        self.events.add(level="INFO", category=Category.SYSTEM, action="backup.create",
                        message=f"Backup do banco criado: {target.name} ({target.stat().st_size // 1024} KB).",
                        actor=actor)
        return target

    def list(self) -> list[Path]:
        return sorted(self.dir.glob(f"{PREFIX}*.db"), reverse=True) if self.dir.exists() else []

    def prune(self, keep: int = KEEP) -> int:
        auto = [p for p in self.list() if not p.stem.endswith(("-manual", "-antes-da-restauracao"))]
        removed = 0
        for old in auto[keep:]:
            try:
                old.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def daily(self) -> Path | None:
        """Cria o backup automático se o último tiver mais de 24 h."""
        latest = self.list()
        if latest:
            age = utc_now().timestamp() - latest[0].stat().st_mtime
            if age < timedelta(hours=24).total_seconds():
                return None
        return self.create()


def verify(path: Path) -> str | None:
    """None se o arquivo é um banco do VYONIX íntegro; senão, a descrição do problema."""
    try:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return f"não abre: {exc}"
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            return f"integridade: {result}"
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"schema_migrations", "devices", "settings"} <= tables:
            return "não é um banco de dados do VYONIX"
        return None
    except sqlite3.Error as exc:
        return f"arquivo inválido: {exc}"
    finally:
        conn.close()


def schema_version(path: Path) -> int:
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        return int(conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0)
    finally:
        conn.close()


def restore(backup: Path, database_file: Path, backups_dir: Path, *, max_schema: int) -> Path:
    """Substitui o banco pelo backup (o banco atual é guardado). Nenhum processo pode estar usando o banco."""
    backup = Path(backup)
    problem = verify(backup)
    if problem:
        raise ValidationError(f"Backup recusado: {problem}.")
    version = schema_version(backup)
    if version > max_schema:
        raise ValidationError(f"O backup é de uma versão mais nova do VYONIX (esquema v{version}; este programa "
                              f"vai até v{max_schema}). Atualize o programa antes de restaurar.")
    backups_dir.mkdir(parents=True, exist_ok=True)
    keep = backups_dir / f"{PREFIX}{utc_now().strftime('%Y%m%dT%H%M%SZ')}-antes-da-restauracao.db"
    if database_file.exists():
        src = sqlite3.connect(str(database_file))
        dst = sqlite3.connect(str(keep))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    tmp = database_file.with_suffix(".restore.tmp")
    shutil.copyfile(backup, tmp)
    for suffix in ("-wal", "-shm"):
        side = Path(str(database_file) + suffix)
        if side.exists():
            side.unlink()
    os.replace(tmp, database_file)
    log.info("Banco restaurado", extra={"from": str(backup), "previous": str(keep)})
    return keep
