"""Sincronização periódica do PACS no modo edge: indexa o que as modalidades enviaram por C-STORE direto ao
motor. Roda no serviço VyonixWorker.

Só executa quando: modo edge; motor configurado; módulo PACS habilitado e com licença vigente na organização
deste servidor. Sem isso, não faz nada (e registra o motivo uma vez). Falhas do motor não param o worker.
"""

from __future__ import annotations

import logging

log = logging.getLogger("vyonix.pacs.sync")
INTERVAL_S = 15


class PacsSyncTask:
    __name__ = "pacs-sync"

    def __init__(self, plat) -> None:
        self.plat = plat
        self._why: str | None = None
        self._tenant = None

    def _skip(self, why: str) -> dict:
        if why != self._why:
            log.info("Sincronização do PACS inativa: %s", why)
            self._why = why
        return {"skipped": why}

    def __call__(self) -> dict:
        from vyonix.errors import NotLicensed
        from vyonix.modules import registry
        from vyonix.pacs import backend_for
        from vyonix.pacs import service as pacs
        from vyonix.pacs.backend import BackendUnavailable
        from vyonix.tenancy import service as tenancy
        if not self.plat.edge:
            return self._skip("modo cloud (o roteamento por AE Title ainda não foi entregue)")
        backend = backend_for(self.plat)
        if backend is None:
            return self._skip("motor DICOM não configurado")
        if self._tenant is None:
            self._tenant = tenancy.resolve(self.plat.db, self.plat.cfg.default_organization)
            if self._tenant is None:
                return self._skip("organização deste servidor não encontrada")
        with self.plat.db.session(self._tenant) as s:
            if not registry.is_enabled(s, "pacs"):
                return self._skip("módulo PACS não habilitado")
            try:
                self.plat.licensing.require_module(s, "pacs")
            except NotLicensed as exc:
                return self._skip(f"sem licença vigente do PACS ({exc})")
            try:
                out = pacs.sync(s, backend)
            except BackendUnavailable as exc:
                return self._skip(f"motor DICOM indisponível ({exc})")
        self._why = None
        if out["indexed"] or out["rejected"]:
            log.info("PACS: %(indexed)d instância(s) indexada(s), %(rejected)d recusada(s)", out)
        return out
