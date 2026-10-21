"""DICOM Storage SCP: C-ECHO e C-STORE (§4.1).

Implementa ``core.contracts.DicomService``. Executa no processo da interface até a Fase 7, quando
passa para o serviço Windows sem alteração de código.

Comportamento:

* Política de associação em :mod:`app.dicom.association_manager` (AE local, AE e IP do
  equipamento, autorização). Recusas usam A-ASSOCIATE-RJ com o diagnóstico DICOM correto.
* Limite de associações simultâneas configurável (rejeição "local limit exceeded").
* Cada instância é gravada por :class:`app.dicom.storage.InstanceStore` (gravação atômica,
  detecção de duplicatas) e entregue ao ``InstanceSink`` (fila de trabalhos, Fase 4).
* Um evento consolidado por associação (recebidas, duplicadas, falhas), com o equipamento.
* Conexões interrompidas (A-ABORT, queda de rede) encerram a associação sem perder as instâncias
  já confirmadas; uma instância só é confirmada (status 0x0000) depois de gravada.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from app.core.contracts import AssociationPeer, InstanceSink, ServiceState, ServiceStatus
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.devices.repository import DeviceRepository
from app.dicom import sop
from app.dicom.association_manager import (AssociationContext, AssociationPolicy,
                                           AssociationRegistry)
from app.dicom.storage import STATUS_PROCESSING_FAILURE, STATUS_SUCCESS, InstanceStore
from app.utils.logging_setup import get_logger
from app.utils.timeutil import utc_now

log = get_logger("dicom.storage_scp")

NAME = "DICOM Storage SCP"


class StorageSCP:
    """Servidor DICOM de recepção de imagens."""

    def __init__(self, *, db: Database, settings_get: Callable[[str], Any], devices: DeviceRepository,
                 store: InstanceStore, events: EventRepository,
                 sink: InstanceSink | None = None, licensed: Callable[[], bool] | None = None) -> None:
        self.licensed = licensed or (lambda: True)
        self.db = db
        self.get = settings_get
        self.devices = devices
        self.store = store
        self.events = events
        self.sink = sink
        self.policy = AssociationPolicy(devices)
        self.registry = AssociationRegistry()
        self._lock = threading.RLock()
        self._ae = None
        self._server = None
        self._state = ServiceState.STOPPED
        self._detail = ""
        self._since = None
        self._bound: tuple[str, int] | None = None
        self.accepted_ts: list[str] = []

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        with self._lock:
            if self._server is not None:
                return
            from pynetdicom import AE, evt

            ae_title = self.get("dicom.storage.ae_title")
            address = self.get("dicom.storage.bind_address")
            port = int(self.get("dicom.storage.port"))
            self._state, self._detail = ServiceState.STARTING, ""
            try:
                ae = AE(ae_title=ae_title)
                ae.maximum_associations = int(self.get("dicom.storage.max_associations"))
                ae.acse_timeout = 30
                ae.dimse_timeout = 60
                ae.network_timeout = 60
                self.accepted_ts = sop.accepted_transfer_syntaxes()
                ae.add_supported_context(sop.VERIFICATION, sop.UNCOMPRESSED)
                for uid in sop.IMAGE_STORAGE:
                    ae.add_supported_context(uid, self.accepted_ts)
                handlers = [
                    (evt.EVT_REQUESTED, self._on_requested),
                    (evt.EVT_RELEASED, self._on_finished),
                    (evt.EVT_ABORTED, self._on_finished),
                    (evt.EVT_CONN_CLOSE, self._on_finished),
                    (evt.EVT_C_ECHO, self._on_echo),
                    (evt.EVT_C_STORE, self._on_store),
                ]
                self._server = ae.start_server((address, port), block=False, evt_handlers=handlers)
                self._ae = ae
                self._bound = (address, port)
            except OSError as exc:
                self._state = ServiceState.ERROR
                self._detail = _bind_error(exc, address, port)
                self._server = None
                self.events.add(level="ERROR", category=Category.DICOM, action="scp.start_failed",
                                message=f"Storage SCP não iniciou: {self._detail}", actor="system")
                log.error("Storage SCP não iniciou", extra={"detail": self._detail})
                return
            self._state, self._since = ServiceState.RUNNING, utc_now()
            self._detail = f"{ae_title} em {address}:{port}"
            self.events.add(level="INFO", category=Category.DICOM, action="scp.start",
                            message=f"Storage SCP iniciado ({self._detail}).", actor="system",
                            details={"transfer_syntaxes": len(self.accepted_ts),
                                     "sop_classes": len(sop.IMAGE_STORAGE)})

    def stop(self, timeout: float = 10.0) -> None:
        with self._lock:
            server, ae = self._server, self._ae
            self._server = self._ae = None
            if server is None:
                if self._state != ServiceState.ERROR:
                    self._state = ServiceState.STOPPED
                return
            self._state = ServiceState.STOPPING
        try:
            server.shutdown()
            if ae is not None:
                ae.shutdown()
        finally:
            with self._lock:
                self._state, self._detail, self._since = ServiceState.STOPPED, "", utc_now()
            self.events.add(level="INFO", category=Category.DICOM, action="scp.stop",
                            message="Storage SCP parado.", actor="system")

    def restart(self) -> None:
        self.stop()
        self.start()

    def status(self) -> ServiceStatus:
        with self._lock:
            detail = self._detail
            if self._state == ServiceState.RUNNING:
                detail = f"{detail} · {len(self.registry)} associação(ões) ativa(s)"
                if not self.licensed():
                    detail += " · SUSPENSO pela licença (associações recusadas)"
            return ServiceStatus(NAME, self._state, detail, self._since)

    @property
    def bound(self) -> tuple[str, int] | None:
        return self._bound

    def active_associations(self) -> list[dict]:
        return self.registry.snapshot()

    # ------------------------------------------------------------------ eventos pynetdicom
    def _on_requested(self, event) -> None:
        assoc = event.assoc
        rq = assoc.requestor.primitive
        calling, called = str(rq.calling_ae_title).strip(), str(rq.called_ae_title).strip()
        address, port = assoc.requestor.address, assoc.requestor.port
        try:
            decision = self.policy.evaluate(
                calling_ae=calling, called_ae=called, address=address,
                local_ae=self.get("dicom.storage.ae_title"),
                accept_unknown=bool(self.get("dicom.storage.accept_unknown")),
                local_addresses=frozenset({self._bound[0]} if self._bound else ()))
            if decision.accepted and not self.licensed():
                assoc.acse.send_reject(0x02, 0x01, 0x01)        # transitória: o equipamento reenvia depois
                self.events.add(level="WARNING", category=Category.LICENSE, action="assoc.unlicensed",
                                message=f"Recepção de {calling}@{address} recusada: funções suspensas pela licença.",
                                device_id=decision.device_id, actor="system")
                return
            if not decision.accepted:
                assoc.acse.send_reject(0x01, 0x01, decision.diagnostic)
                if decision.device_id:
                    self.devices.touch_seen(decision.device_id, "recusado")
                self.events.add(level="WARNING", category=Category.SECURITY, action="assoc.reject",
                                message=f"Associação recusada de {calling}@{address}: {decision.reason}.",
                                device_id=decision.device_id, actor="system",
                                details={"calling_ae": calling, "called_ae": called, "address": address})
                return
            self.registry.add(AssociationContext(
                key=id(assoc), calling_ae=calling, called_ae=called, address=address, port=port,
                device_id=decision.device_id, device_name=decision.device_name))
            if decision.device_id:
                self.devices.touch_seen(decision.device_id, "conectado")
        except Exception:  # noqa: BLE001
            log.exception("Falha ao avaliar associação; recusando")
            try:
                assoc.acse.send_reject(0x02, 0x01, 0x01)   # transitória, sem motivo
            except Exception:  # noqa: BLE001
                pass
        finally:
            if assoc.is_rejected:
                self.db.close_thread_connection()

    def _on_echo(self, event) -> int:
        self.registry.update(id(event.assoc), lambda c: setattr(c, "echoes", c.echoes + 1))
        return STATUS_SUCCESS

    def _on_store(self, event) -> int:
        ctx = self.registry.get(id(event.assoc))
        if ctx is None:  # não deveria ocorrer: associação não registrada
            return STATUS_PROCESSING_FAILURE
        peer = AssociationPeer(calling_ae=ctx.calling_ae, called_ae=ctx.called_ae,
                               address=ctx.address, port=ctx.port)
        try:
            encoded = event.encoded_dataset(include_meta=True)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao obter o dataset recebido")
            self.registry.update(ctx.key, lambda c: setattr(c, "failures", c.failures + 1))
            return STATUS_PROCESSING_FAILURE
        outcome = self.store.store(
            encoded, peer, ctx.device_id,
            max_bytes=int(self.get("dicom.storage.max_instance_mb")) * 1048576,
            retention_days=int(self.get("retention.images_days")))

        def bump(c: AssociationContext) -> None:
            if outcome.status != STATUS_SUCCESS:
                c.failures += 1
            elif outcome.duplicate:
                c.duplicates += 1
            else:
                c.received += 1
                c.bytes += len(encoded)
                if outcome.instance and outcome.instance.modality:
                    c.modalities.add(outcome.instance.modality)
        self.registry.update(ctx.key, bump)
        if outcome.status != STATUS_SUCCESS or outcome.conflict:
            self.events.add(level="ERROR" if outcome.status != STATUS_SUCCESS else "WARNING",
                            category=Category.DICOM, action="store.problem",
                            message=f"C-STORE de {ctx.calling_ae}: {outcome.message} "
                                    f"(status 0x{outcome.status:04X}).",
                            device_id=ctx.device_id, actor="system")
        if outcome.instance is not None and self.sink is not None:
            try:
                self.sink.on_instance_received(outcome.instance)
            except Exception:  # noqa: BLE001 - a instância já está segura no disco
                log.exception("Falha ao encaminhar instância para a fila")
        return outcome.status

    def _on_finished(self, event) -> None:
        ctx = self.registry.pop(id(event.assoc))
        try:
            if ctx is None:
                return
            aborted = event.event.name == "EVT_ABORTED" or (
                event.event.name == "EVT_CONN_CLOSE" and not event.assoc.is_released)
            if ctx.received or ctx.duplicates or ctx.failures or aborted:
                level = "WARNING" if (ctx.failures or aborted) else "INFO"
                msg = (f"{ctx.calling_ae}@{ctx.address}: {ctx.received} instância(s) recebida(s)"
                       f", {ctx.duplicates} duplicada(s), {ctx.failures} com falha"
                       + (" — conexão interrompida" if aborted else "") + ".")
                self.events.add(level=level, category=Category.DICOM,
                                action="assoc.aborted" if aborted else "assoc.complete",
                                message=msg, device_id=ctx.device_id, actor="system",
                                details={"modalities": sorted(ctx.modalities), "bytes": ctx.bytes})
            if ctx.device_id:
                self.devices.touch_seen(ctx.device_id, "interrompido" if aborted else "ok")
        except Exception:  # noqa: BLE001
            log.exception("Falha ao finalizar associação")
        finally:
            self.db.close_thread_connection()


def _bind_error(exc: OSError, address: str, port: int) -> str:
    code = getattr(exc, "winerror", None) or exc.errno
    if code in (10048, 98, 48):
        return f"a porta {port} já está em uso por outro programa"
    if code in (10013, 13):
        # No Windows, 10013 (WSAEACCES) também indica porta em uso exclusivo por outro programa
        # ou reservada pelo sistema (ex.: faixas do Hyper-V).
        if port < 1024:
            return (f"sem permissão para usar a porta {port} (portas abaixo de 1024 exigem "
                    "administrador) ou ela já está em uso")
        return f"a porta {port} já está em uso por outro programa ou reservada pelo Windows"
    if code in (10049, 99):
        return f"o endereço {address} não pertence a este computador"
    return f"{exc.strerror or exc} ({address}:{port})"
