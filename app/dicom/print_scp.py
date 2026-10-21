"""DICOM Print SCP (Fase 5): recebe filmes de equipamentos que imprimem via DICOM.

* AE Title e porta próprios (``dicom.print.*``), independentes do Storage SCP.
* Mesmas regras de associação do Storage SCP: equipamento cadastrado, autorizado, IP conferido.
* Meta SOP Classes Basic Grayscale e (opcionalmente) Basic Color Print Management, Presentation
  LUT e Verification. Cada associação tem seu próprio modelo (``PrintSession``).
* O N-ACTION de impressão responde sucesso **somente depois** que as imagens foram gravadas e o
  trabalho foi criado na fila persistente.
* Auditoria em ``print_sessions`` (atributos técnicos, sem rótulos livres nem pixels) e eventos.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable

from app import __version__
from app.core.contracts import AssociationPeer, ServiceState, ServiceStatus
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.devices.repository import DeviceRepository
from app.dicom import print_model as pm
from app.dicom import sop
from app.dicom.association_manager import AssociationPolicy
from app.dicom.print_intake import PrintIntake
from app.dicom.storage_scp import _bind_error
from app.utils.logging_setup import get_logger
from app.utils.timeutil import utc_now, utc_now_iso

log = get_logger("dicom.print_scp")

NAME = "DICOM Print SCP"
PRINT_TS = ["1.2.840.10008.1.2.1", "1.2.840.10008.1.2"]   # Explicit e Implicit VR Little Endian


class _Assoc:
    def __init__(self, key: int, peer: AssociationPeer, device_id: int | None, device_name: str | None,
                 session: pm.PrintSession) -> None:
        from pydicom.uid import generate_uid
        self.key, self.peer, self.device_id, self.device_name = key, peer, device_id, device_name
        self.session = session
        self.study_uid = generate_uid(prefix="1.2.826.0.1.3680043.8.498.")
        self.operations = 0


class PrintSCP:
    def __init__(self, *, db: Database, settings_get: Callable[[str], Any], devices: DeviceRepository,
                 events: EventRepository, intake: PrintIntake,
                 printer_status: Callable[[], tuple[str, str]],
                 licensed: Callable[[], bool] | None = None) -> None:
        self.licensed = licensed or (lambda: True)
        self.db = db
        self.get = settings_get
        self.devices = devices
        self.events = events
        self.intake = intake
        self.printer_status = printer_status
        self.policy = AssociationPolicy(devices)
        self._lock = threading.Lock()
        self._server = None
        self._ae = None
        self._bound: tuple[str, int] | None = None
        self._state, self._detail, self._since = ServiceState.STOPPED, "", None
        self._assocs: dict[int, _Assoc] = {}

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        with self._lock:
            if self._server is not None:
                return
            if not self.get("dicom.print.enabled"):
                self._state, self._detail = ServiceState.STOPPED, "desativado em Configurações"
                return
            from pynetdicom import AE, evt
            ae_title = self.get("dicom.print.ae_title")
            address = self.get("dicom.storage.bind_address")
            port = int(self.get("dicom.print.port"))
            self._state = ServiceState.STARTING
            try:
                ae = AE(ae_title=ae_title)
                ae.maximum_associations = int(self.get("dicom.storage.max_associations"))
                ae.acse_timeout, ae.dimse_timeout, ae.network_timeout = 30, 120, 120
                ae.add_supported_context(sop.VERIFICATION, PRINT_TS)
                ae.add_supported_context(pm.GRAYSCALE_META, PRINT_TS)
                if self.get("dicom.print.color"):
                    ae.add_supported_context(pm.COLOR_META, PRINT_TS)
                ae.add_supported_context(pm.PRESENTATION_LUT, PRINT_TS)
                handlers = [
                    (evt.EVT_REQUESTED, self._on_requested), (evt.EVT_RELEASED, self._on_finished),
                    (evt.EVT_ABORTED, self._on_finished), (evt.EVT_CONN_CLOSE, self._on_finished),
                    (evt.EVT_C_ECHO, lambda e: 0x0000), (evt.EVT_N_CREATE, self._on_create),
                    (evt.EVT_N_SET, self._on_set), (evt.EVT_N_ACTION, self._on_action),
                    (evt.EVT_N_DELETE, self._on_delete), (evt.EVT_N_GET, self._on_get),
                ]
                self._server = ae.start_server((address, port), block=False, evt_handlers=handlers)
                self._ae, self._bound = ae, (address, port)
            except OSError as exc:
                self._state, self._detail, self._server = ServiceState.ERROR, _bind_error(exc, address, port), None
                self.events.add(level="ERROR", category=Category.DICOM, action="print_scp.start_failed",
                                message=f"Print SCP não iniciou: {self._detail}", actor="system")
                return
            self._state, self._since = ServiceState.RUNNING, utc_now()
            self._detail = f"{ae_title} em {address}:{port}"
            self.events.add(level="INFO", category=Category.DICOM, action="print_scp.start",
                            message=f"Print SCP iniciado ({self._detail}).", actor="system")

    def stop(self, timeout: float = 10.0) -> None:
        with self._lock:
            server, ae = self._server, self._ae
            self._server = self._ae = None
            if server is None:
                if self._state not in (ServiceState.ERROR,):
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
            self.events.add(level="INFO", category=Category.DICOM, action="print_scp.stop",
                            message="Print SCP parado.", actor="system")

    def restart(self) -> None:
        self.stop()
        self.start()

    def status(self) -> ServiceStatus:
        with self._lock:
            detail = self._detail
            if self._state == ServiceState.RUNNING:
                detail += f" · {len(self._assocs)} associação(ões) ativa(s)"
                if not self.licensed():
                    detail += " · SUSPENSO pela licença (associações recusadas)"
            return ServiceStatus(NAME, self._state, detail, self._since)

    @property
    def bound(self) -> tuple[str, int] | None:
        return self._bound

    # ------------------------------------------------------------------ associação
    def _on_requested(self, event) -> None:
        assoc = event.assoc
        rq = assoc.requestor.primitive
        calling, called = str(rq.calling_ae_title).strip(), str(rq.called_ae_title).strip()
        address, port = assoc.requestor.address, assoc.requestor.port
        try:
            decision = self.policy.evaluate(
                calling_ae=calling, called_ae=called, address=address, local_ae=self.get("dicom.print.ae_title"),
                accept_unknown=bool(self.get("dicom.storage.accept_unknown")),
                local_addresses=frozenset({self._bound[0]} if self._bound else ()))
            if decision.accepted and not self.licensed():
                assoc.acse.send_reject(0x02, 0x01, 0x01)        # transitória: o equipamento pode tentar depois
                self.events.add(level="WARNING", category=Category.LICENSE, action="print_assoc.unlicensed",
                                message=f"Impressão DICOM de {calling}@{address} recusada: funções suspensas pela "
                                        "licença.", device_id=decision.device_id, actor="system")
                return
            if not decision.accepted:
                assoc.acse.send_reject(0x01, 0x01, decision.diagnostic)
                self.events.add(level="WARNING", category=Category.SECURITY, action="print_assoc.reject",
                                message=f"Associação de impressão recusada de {calling}@{address}: {decision.reason}.",
                                device_id=decision.device_id, actor="system")
                return
            peer = AssociationPeer(calling_ae=calling, called_ae=called, address=address, port=port)
            ctx_ref: dict[str, _Assoc] = {}

            def on_print(film: pm.PrintedFilm) -> int:
                a = ctx_ref["a"]
                return self.intake.submit(film, peer=a.peer, device_id=a.device_id, study_uid=a.study_uid)

            session = pm.PrintSession(color_allowed=False, on_print=on_print, printer_status=self.printer_status,
                                      honor_density=bool(self.get("dicom.print.honor_density")))
            a = _Assoc(id(assoc), peer, decision.device_id, decision.device_name, session)
            ctx_ref["a"] = a
            with self._lock:
                self._assocs[a.key] = a
            if decision.device_id:
                self.devices.touch_seen(decision.device_id, "impressão")
        except Exception:  # noqa: BLE001
            log.exception("Falha ao avaliar associação de impressão")
            try:
                assoc.acse.send_reject(0x02, 0x01, 0x01)
            except Exception:  # noqa: BLE001
                pass
        finally:
            if assoc.is_rejected:
                self.db.close_thread_connection()

    def _assoc(self, event) -> _Assoc | None:
        with self._lock:
            return self._assocs.get(id(event.assoc))

    def _meta(self, event) -> str:
        return str(event.context.abstract_syntax)

    # ------------------------------------------------------------------ DIMSE-N
    def _on_create(self, event):
        a = self._assoc(event)
        if a is None:
            return pm.PROCESSING_FAILURE, None
        req = event.request
        sop_class = str(req.AffectedSOPClassUID)
        a.session.color_allowed = self._meta(event) == pm.COLOR_META
        uid = str(req.AffectedSOPInstanceUID) if req.AffectedSOPInstanceUID else None
        try:
            ds = event.attribute_list
        except Exception:  # noqa: BLE001 - lista de atributos ausente ou ilegível
            ds = None
        if ds is None:
            from pydicom.dataset import Dataset
            ds = Dataset()
        status, rsp = a.session.n_create(sop_class, uid, ds)
        a.operations += 1
        if status == pm.SUCCESS:
            new_uid = uid or (str(rsp.get("AffectedSOPInstanceUID")) if rsp is not None else None)
            kind = {pm.FILM_SESSION: "film_session", pm.FILM_BOX: "film_box",
                    pm.PRESENTATION_LUT: "presentation_lut"}.get(sop_class)
            if kind and new_uid:
                attrs = (a.session.session_attrs if kind == "film_session" else
                         a.session.film_boxes[new_uid].attrs if kind == "film_box" else
                         {"shape": a.session.luts[new_uid].shape})
                self._audit(a, kind, new_uid, attrs)
        else:
            self._problem(a, f"N-CREATE {_name(sop_class)}", status)
        return status, rsp

    def _on_set(self, event):
        a = self._assoc(event)
        if a is None:
            return pm.PROCESSING_FAILURE, None
        req = event.request
        status, rsp = a.session.n_set(str(req.RequestedSOPClassUID), str(req.RequestedSOPInstanceUID),
                                      event.modification_list)
        a.operations += 1
        if status != pm.SUCCESS:
            self._problem(a, f"N-SET {_name(str(req.RequestedSOPClassUID))}", status)
        return status, rsp

    def _on_action(self, event):
        a = self._assoc(event)
        if a is None:
            return pm.PROCESSING_FAILURE, None
        req = event.request
        before = len(a.session.jobs)
        status, rsp = a.session.n_action(str(req.RequestedSOPClassUID), str(req.RequestedSOPInstanceUID),
                                         event.action_type)
        new_jobs = a.session.jobs[before:]
        if new_jobs:
            self.events.add(level="INFO", category=Category.DICOM, action="print.film",
                            message=f"{a.peer.calling_ae}@{a.peer.address}: {len(new_jobs)} filme(s) recebido(s) por "
                                    f"DICOM Print → trabalho(s) " + ", ".join(f"#{j}" for j in new_jobs) + ".",
                            device_id=a.device_id, job_id=new_jobs[-1], actor="system")
        if status != pm.SUCCESS:
            self._problem(a, f"N-ACTION {_name(str(req.RequestedSOPClassUID))}", status)
        return status, rsp

    def _on_delete(self, event):
        a = self._assoc(event)
        if a is None:
            return pm.PROCESSING_FAILURE
        req = event.request
        return a.session.n_delete(str(req.RequestedSOPClassUID), str(req.RequestedSOPInstanceUID))

    def _on_get(self, event):
        a = self._assoc(event)
        if a is None:
            return pm.PROCESSING_FAILURE, None
        req = event.request
        if str(req.RequestedSOPClassUID) != pm.PRINTER:
            return pm.NO_SUCH_SOP_CLASS, None
        return a.session.n_get_printer(str(req.RequestedSOPInstanceUID), f"VYONIX {self.get('dicom.print.ae_title')}",
                                       __version__)

    def _on_finished(self, event) -> None:
        with self._lock:
            a = self._assocs.pop(id(event.assoc), None)
        try:
            if a is None:
                return
            pending = a.session.unprinted
            if pending:
                self.events.add(level="WARNING", category=Category.DICOM, action="print.unprinted",
                                message=f"{a.peer.calling_ae}: associação encerrada com {pending} filme(s) montado(s) "
                                        "e não impresso(s) (o equipamento não enviou o comando de impressão).",
                                device_id=a.device_id, actor="system")
            if a.device_id:
                self.devices.touch_seen(a.device_id, "ok")
        except Exception:  # noqa: BLE001
            log.exception("Falha ao finalizar associação de impressão")
        finally:
            self.db.close_thread_connection()

    # ------------------------------------------------------------------ auditoria
    def _audit(self, a: _Assoc, kind: str, uid: str, attrs: dict) -> None:
        now = utc_now_iso()
        parent = a.session.session_uid if kind == "film_box" else None
        try:
            self.db.connection().execute(
                """INSERT OR REPLACE INTO print_sessions(association_id, kind, sop_instance_uid, parent_uid,
                       attributes_json, device_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(a.study_uid), kind, uid, parent, json.dumps(attrs, default=str), a.device_id, now, now))
        except Exception:  # noqa: BLE001 - auditoria não pode derrubar a impressão
            log.exception("Falha ao auditar sessão de impressão")

    def _problem(self, a: _Assoc, what: str, status: int) -> None:
        level = "WARNING" if 0xB000 <= status <= 0xBFFF else "ERROR"
        self.events.add(level=level, category=Category.DICOM, action="print.problem",
                        message=f"{a.peer.calling_ae}: {what} respondido com status 0x{status:04X}.",
                        device_id=a.device_id, actor="system")


def _name(uid: str) -> str:
    return {pm.FILM_SESSION: "Film Session", pm.FILM_BOX: "Film Box", pm.GRAY_IMAGE_BOX: "Grayscale Image Box",
            pm.COLOR_IMAGE_BOX: "Color Image Box", pm.PRESENTATION_LUT: "Presentation LUT",
            pm.PRINTER: "Printer", pm.ANNOTATION_BOX: "Annotation Box"}.get(uid, uid)
