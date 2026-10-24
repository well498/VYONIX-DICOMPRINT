"""Sincronização periódica do PACS no modo edge: indexa o que as modalidades enviaram por C-STORE direto ao
motor. Roda no serviço VyonixWorker.

Modo edge: tudo vai para a organização deste servidor, se o módulo PACS estiver habilitado e licenciado.
Modo cloud: cada instância vai para a organização dona do AE Title chamado pela modalidade (rotas do PACS);
sem rota, ou sem módulo/licença na organização, fica em quarentena (não indexada). Sem isso, não faz nada (e registra o motivo uma vez). Falhas do motor não param o worker.
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
        backend = backend_for(self.plat)
        if backend is None:
            return self._skip("motor DICOM não configurado")
        if not self.plat.edge:
            return self._cloud(backend)
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
        return self._done(out)

    def _cloud(self, backend) -> dict:
        """Modo cloud: cada instância vai para a organização dona do AE Title chamado (rotas do PACS)."""
        from vyonix.errors import NotLicensed
        from vyonix.modules import registry
        from vyonix.pacs import service as pacs
        from vyonix.pacs.backend import BackendUnavailable

        def allowed(s) -> bool:
            if not registry.is_enabled(s, "pacs"):
                return False
            try:
                self.plat.licensing.require_module(s, "pacs")
            except NotLicensed:
                return False
            return True
        try:
            out = pacs.cloud_sync(self.plat.db, backend, allowed=allowed)
        except BackendUnavailable as exc:
            return self._skip(f"motor DICOM indisponível ({exc})")
        if out["quarantined"]:
            log.warning("PACS (cloud): %d instância(s) em quarentena (AE Title sem rota, organização sem módulo ou "
                        "licença, ou recebida por outro meio)", out["quarantined"])
        return self._done(out)

    def _done(self, out: dict) -> dict:
        self._why = None
        if out["indexed"] or out["rejected"]:
            log.info("PACS: %(indexed)d instância(s) indexada(s), %(rejected)d recusada(s)", out)
        return out
