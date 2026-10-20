"""Composição da aplicação — sem dependência de Qt.

Usado pela interface (``role="ui"``), pela verificação ``--check`` e, na Fase 7, pelo
serviço Windows (``role="service"``). A ordem de inicialização é:

1. resolver e criar diretórios (nunca no diretório do executável);
2. iniciar o logging estruturado;
3. abrir o banco, verificar integridade e aplicar migrações (com backup prévio);
4. compor repositórios e serviços;
5. aplicar configurações que têm efeito imediato (nível de log);
6. registrar o evento de inicialização.
"""

from __future__ import annotations

import os
import platform
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app import __phase__, __version__
from app.database.connection import Database
from app.database.migrations import MIGRATIONS
from app.database.migrator import current_version, migrate
from app.database.repositories.events_repo import Category, EventRepository
from app.database.repositories.settings_repo import ChangeHistoryRepository
from app.database.repositories.stats_repo import StatsRepository
from app.devices.service import DeviceService
from app.dicom import scu
from app.dicom.storage import InstanceStore
from app.dicom.storage_scp import StorageSCP
from app.security.access import AdminAccess
from app.services.dashboard_service import DashboardService
from app.services.retention import RetentionService
from app.services.runtime import CoreRuntime
from app.services.settings_service import SettingsService
from app.utils.logging_setup import (get_logger, install_exception_hooks, set_log_level,
                                     setup_logging, shutdown_logging)
from app.utils.paths import AppPaths, resolve_paths

log = get_logger("bootstrap")


@dataclass
class AppContext:
    role: str
    paths: AppPaths
    log_file: Path
    db: Database
    events: EventRepository
    settings: SettingsService
    changes: ChangeHistoryRepository
    stats: StatsRepository
    dashboard: DashboardService
    devices: DeviceService
    store: InstanceStore
    storage_scp: StorageSCP
    retention: RetentionService
    access: AdminAccess
    runtime: CoreRuntime
    schema_version: int
    applied_migrations: list[int] = field(default_factory=list)
    _closed: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "phase": __phase__,
            "role": self.role,
            "schema_version": self.schema_version,
            "applied_migrations": self.applied_migrations,
            "database": str(self.paths.database_file),
            "machine_data": str(self.paths.machine_root),
            "user_data": str(self.paths.user_root),
            "log_file": str(self.log_file),
            "installation_id": self.settings.get("system.installation_id"),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "sqlite_json": self.db.json_mode,
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.events.add(level="INFO", category=Category.SYSTEM, action="app.stop",
                            message=f"Encerramento ({self.role}).", actor="system")
        except Exception:  # encerramento é melhor esforço
            log.exception("Falha ao registrar encerramento")
        log.info("Encerrando", extra={"role": self.role})
        try:
            self.runtime.stop()
        except Exception:  # noqa: BLE001
            log.exception("Falha ao parar os serviços")
        self.db.close()
        shutdown_logging()


def bootstrap(*, data_dir: str | os.PathLike[str] | None = None, role: str = "ui",
              log_level: str | None = None, console_log: bool = False) -> AppContext:
    paths = resolve_paths(data_dir).ensure()
    log_file = setup_logging(paths.logs_dir_for(role), role, level=log_level or "INFO",
                             console=console_log)
    install_exception_hooks()
    log.info("Inicializando", extra={"version": __version__, "role": role,
                                     "python": platform.python_version(),
                                     "os": platform.platform()})

    db = Database(paths.database_file)
    try:
        if paths.database_file.exists() and paths.database_file.stat().st_size > 0:
            db.assert_integrity()
        applied = migrate(db, MIGRATIONS, backup_dir=paths.backups_dir)
        schema = current_version(db)

        events = EventRepository(db)
        settings = SettingsService(db, events)
        settings.ensure_defaults()
        stats = StatsRepository(db)
        get = settings.get

        def device_echo(device):
            return scu.echo(device.ip_address, device.port, device.ae_title,
                            calling_ae=get("dicom.storage.ae_title"))

        devices = DeviceService(db, events, echo=device_echo)
        store = InstanceStore(db, paths.storage_dir, paths.temp_dir)
        storage_scp = StorageSCP(db=db, settings_get=get, devices=devices.repo, store=store,
                                 events=events)
        retention = RetentionService(db, events, get, paths.storage_dir)
        runtime = CoreRuntime(storage_scp=storage_scp, retention=retention, settings_get=get)
        access = AdminAccess(db, events, lock_minutes=lambda: int(get("security.lock_minutes")))
        ctx = AppContext(
            role=role, paths=paths, log_file=log_file, db=db, events=events, settings=settings,
            changes=ChangeHistoryRepository(db), stats=stats,
            dashboard=DashboardService(stats, settings, events,
                                       service_status_provider=runtime.service_statuses,
                                       access=access),
            devices=devices, store=store, storage_scp=storage_scp, retention=retention,
            access=access, runtime=runtime,
            schema_version=schema, applied_migrations=applied,
        )
        settings.subscribe(runtime.on_settings_changed)
        _clean_temp(paths.temp_dir)
    except BaseException:
        log.exception("Falha na inicialização")
        db.close()
        shutdown_logging()
        raise

    # Nível de log: argumento de linha de comando tem precedência sobre a configuração.
    if log_level is None:
        set_log_level(settings.get("logging.level"))
    settings.subscribe(lambda changed: "logging.level" in changed
                       and set_log_level(changed["logging.level"]))

    if applied:
        events.add(level="INFO", category=Category.SYSTEM, action="db.migrate",
                   message=f"Esquema do banco atualizado para v{schema}.", actor="system",
                   details={"applied": applied})
    events.add(level="INFO", category=Category.SYSTEM, action="app.start",
               message=f"Inicialização concluída ({role}).", actor="system",
               details={"version": __version__, "schema_version": schema})
    log.info("Inicialização concluída", extra={"schema_version": schema})
    return ctx


def _clean_temp(folder: Path) -> None:
    """Remove recepções incompletas deixadas por uma queda anterior (arquivos rx-*.dcm)."""
    for leftover in folder.glob("rx-*.dcm"):
        try:
            leftover.unlink()
            log.warning("Recepção incompleta removida após reinício", extra={"file": leftover.name})
        except OSError:
            pass
