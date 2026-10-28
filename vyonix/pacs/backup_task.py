"""Backup automático diário do PACS (serviço VyonixWorker), sobre ``vyonix.pacs.backup``.

Configuração do Core (gravada pelo VYONIX DEPLOY na ativação do PACS):

* ``pacs_backup_dir`` — pasta de destino; sem ela o backup automático fica desligado;
* ``pacs_backup_hour`` — hora local a partir da qual roda (padrão 2). Roda uma vez por dia; se o servidor estava
  desligado no horário, roda na primeira verificação depois dele.

Cada execução faz a exportação incremental, confere o backup contra o manifesto e grava o resultado em
``<destino>/last_run.json`` (lido pelo monitoramento). Falha não para o worker; nova tentativa em 1 hora.
Só no modo edge (uma organização por servidor); no modo cloud o backup é por organização, pelo comando
``vyonix pacs-backup --org``. Nada é apagado no motor, no índice ou no destino.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("vyonix.pacs.backup")
INTERVAL_S = 300
RETRY_S = 3600
STATUS = "last_run.json"


def read_status(dest: str | Path) -> dict[str, Any] | None:
    try:
        return json.loads((Path(dest) / STATUS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_status(dest: Path, st: dict) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / (STATUS + ".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, dest / STATUS)


class PacsBackupTask:
    __name__ = "pacs-backup"

    def __init__(self, plat, *, now: Callable[[], datetime] = datetime.now,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self.plat, self.now, self.monotonic = plat, now, monotonic
        self._failed_at: float | None = None
        self._why: str | None = None

    def _skip(self, why: str) -> dict:
        if why != self._why:
            log.info("Backup automático do PACS inativo: %s", why)
            self._why = why
        return {"skipped": why}

    def due(self, dest: Path) -> bool:
        now = self.now()
        if now.hour < int(self.plat.cfg.extra.get("pacs_backup_hour", 2)):
            return False
        if self._failed_at is not None and self.monotonic() - self._failed_at < RETRY_S:
            return False
        st = read_status(dest)
        return not (st and st.get("ok") and st.get("local_date") == now.date().isoformat())

    def __call__(self) -> dict:
        from vyonix.errors import NotLicensed
        from vyonix.modules import registry
        from vyonix.pacs import backend_for, backup
        from vyonix.tenancy import service as tenancy
        dest = self.plat.cfg.extra.get("pacs_backup_dir")
        if not dest:
            return self._skip("pasta de backup não configurada")
        dest = Path(dest)
        if not self.plat.edge:
            return self._skip("modo cloud: use 'vyonix pacs-backup --org' por organização")
        backend = backend_for(self.plat)
        if backend is None:
            return self._skip("motor DICOM não configurado")
        if not self.due(dest):
            return {"skipped": "fora do horário ou já feito hoje"}
        tid = tenancy.resolve(self.plat.db, self.plat.cfg.default_organization)
        if tid is None:
            return self._skip("organização deste servidor não encontrada")
        with self.plat.db.session(tid) as s:
            if not registry.is_enabled(s, "pacs"):
                return self._skip("módulo PACS não habilitado")
            try:
                self.plat.licensing.require_module(s, "pacs")
            except NotLicensed:
                pass            # sem licença o PACS não recebe, mas as imagens já guardadas continuam protegidas
        self._why = None
        started = self.now()
        st: dict[str, Any] = {"started_at": started.isoformat(timespec="seconds"),
                              "local_date": started.date().isoformat()}
        try:
            out = backup.export(self.plat.db, tid, backend, dest, actor="backup automático")
            v = backup.verify(dest)
            st.update(instances=out["instances"], copied=out["copied"], bytes=out["bytes"],
                      integrity_failures=len(out["integrity_failures"]), verified=v["valid"],
                      ok=v["valid"] and not out["integrity_failures"])
            if out["integrity_failures"]:
                st["error"] = (f"{len(out['integrity_failures'])} instância(s) com integridade violada no motor "
                               "não foram copiadas")
            elif not v["valid"]:
                st["error"] = "o backup gravado não confere com o manifesto"
        except Exception as exc:  # noqa: BLE001 - registrado; nova tentativa em 1 hora
            log.exception("Falha no backup automático do PACS")
            st.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:300])
        st["finished_at"] = self.now().isoformat(timespec="seconds")
        try:
            _write_status(dest, st)
        except OSError:
            log.exception("Não foi possível gravar o resultado do backup em %s", dest)
        self._failed_at = None if st.get("ok") else self.monotonic()
        (log.info if st.get("ok") else log.warning)("Backup do PACS: %s", st)
        return st
