"""Montagem do licenciamento com os componentes reais do computador."""

from __future__ import annotations

import os
import sys
from typing import Any, Callable

from app.licensing.demo import DemoService
from app.licensing.hardware import HardwareProvider
from app.licensing.installation import InstallationManager
from app.licensing.license import LicenseService
from app.licensing.time_integrity import SystemClock, TimeIntegrity, db_logger
from app.licensing.tpm import NullTpm, default_tpm
from app.licensing.vault import DbBackend, FileBackend, RegistryBackend, Vault, machine_sealer


def build_vault(db, paths) -> Vault:
    state = paths.licensing_state_dir
    backends: list = [DbBackend(db), FileBackend(state)]
    if sys.platform == "win32" and not paths.isolated:
        backends.append(RegistryBackend())
    return Vault(backends, machine_sealer(state, use_registry=not paths.isolated))


def build_license_service(db, events, settings_get: Callable[[str], Any], paths, *, role: str,
                          settings_set: Callable[[str, Any], None] | None = None,
                          enforced: bool | None = None) -> LicenseService:
    vault = build_vault(db, paths)
    if paths.isolated and os.environ.get("VYONIX_TPM_ISOLATED") != "1":
        tpm = NullTpm("pasta de dados isolada (testes)")
    else:
        tpm = default_tpm()
    return LicenseService(
        db, events, settings_get, vault=vault, hardware=HardwareProvider(tpm), tpm=tpm,
        installation=InstallationManager(vault), time_integrity=TimeIntegrity(vault, SystemClock(),
                                                                              log_event=db_logger(db, role),
                                                                              process=role),
        demo=DemoService(vault), enforced=enforced, settings_set=settings_set)
