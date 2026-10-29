"""Consulta e recuperação DICOM (C-FIND / C-MOVE / C-GET, Study Root) do VYONIX PACS, servidas pelo Core.

O Orthanc tem C-FIND/C-MOVE desligados (passariam por fora da autorização). Aqui:

* **Organização:** modo edge → a organização do servidor; modo cloud → a dona do AE Title chamado (rotas do PACS).
* **Quem consulta:** só nós DICOM cadastrados pela organização com permissão de consulta; se o nó tiver IP
  cadastrado, o endereço da associação precisa conferir. Os demais são recusados na associação.
* **Para onde vai o C-MOVE:** só para nós da mesma organização com permissão de receber (IP e porta cadastrados).
* **C-GET:** as imagens voltam na própria associação; só para o nó solicitante que também tem permissão de receber
  (negociação de papel SCP/SCU para as classes de armazenamento).
* **Integridade:** cada arquivo enviado tem o SHA-256 conferido com o registrado na entrada.
* **Licença:** consulta e recuperação de dados existentes não dependem de licença vigente (como no DICOMweb).
* **Auditoria:** consultas (nível e AE, sem dados do paciente) e envios (destino e quantidades).
"""

from __future__ import annotations

import io
import logging
import threading
from typing import Any

log = logging.getLogger("vyonix.pacs.qr")

FIND = "1.2.840.10008.5.1.4.1.2.2.1"        # Study Root Query/Retrieve Information Model - FIND
MOVE = "1.2.840.10008.5.1.4.1.2.2.2"        # Study Root Query/Retrieve Information Model - MOVE
GET = "1.2.840.10008.5.1.4.1.2.2.3"         # Study Root Query/Retrieve Information Model - GET
VERIFICATION = "1.2.840.10008.1.1"
MWL = "1.2.840.10008.5.1.4.31"             # Modality Worklist Information Model - FIND (VYONIX RIS)
MPPS = "1.2.840.10008.3.1.2.3.3"           # Modality Performed Procedure Step (VYONIX RIS)

STUDY_KEYS = {"PatientID": "PatientID", "PatientName": "PatientName", "StudyDate": "StudyDate",
              "AccessionNumber": "AccessionNumber", "StudyInstanceUID": "StudyInstanceUID",
              "ModalitiesInStudy": "ModalitiesInStudy", "StudyDescription": "StudyDescription"}


def _value(ds, keyword: str) -> str:
    v = ds.get(keyword)
    if v is None:
        return ""
    if isinstance(v, (list, tuple)) or getattr(v, "VM", 1) > 1 and not isinstance(v, str):
        return ",".join(str(x) for x in v)
    return str(v).strip()


class QRServer:
    def __init__(self, plat, *, port: int, ae_title: str = "VYONIX_QR", bind: str = "0.0.0.0", backend=None) -> None:
        self.plat, self.port, self.ae_title, self.bind = plat, int(port), ae_title, bind
        self._backend = backend
        self.server = None
        self._ctx: dict[int, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @property
    def backend(self):
        if self._backend is None:
            from vyonix.pacs import backend_for
            self._backend = backend_for(self.plat)
        return self._backend

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        from pynetdicom import AE, evt
        ae = AE(ae_title=self.ae_title)
        ae.require_called_aet = False                 # modo cloud: o AE chamado escolhe a organização
        ae.acse_timeout, ae.dimse_timeout, ae.network_timeout = 30, 60, 60
        ae.maximum_associations = 16
        from pynetdicom import ALL_TRANSFER_SYNTAXES, StoragePresentationContexts
        from vyonix.pacs.commitment import PUSH_MODEL
        for uid in (VERIFICATION, FIND, MOVE, GET, MWL, MPPS, PUSH_MODEL):
            ae.add_supported_context(uid)
        for cx in StoragePresentationContexts:            # C-GET: o VYONIX atua como SCU de armazenamento
            ae.add_supported_context(cx.abstract_syntax, ALL_TRANSFER_SYNTAXES, scu_role=True, scp_role=True)
        self.server = ae.start_server((self.bind, self.port), block=False, evt_handlers=[
            (evt.EVT_REQUESTED, self._on_requested), (evt.EVT_RELEASED, self._on_end),
            (evt.EVT_ABORTED, self._on_end), (evt.EVT_CONN_CLOSE, self._on_end),
            (evt.EVT_C_ECHO, lambda e: 0x0000), (evt.EVT_C_FIND, self._on_find), (evt.EVT_C_MOVE, self._on_move),
            (evt.EVT_C_GET, self._on_get),
            (evt.EVT_N_CREATE, self._on_n_create), (evt.EVT_N_SET, self._on_n_set),
            (evt.EVT_N_ACTION, self._on_n_action)])
        log.info("Consulta/recuperação DICOM em %s:%d (AE %s)", self.bind, self.port, self.ae_title)

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server = None

    # ------------------------------------------------------------------ associação
    def _tenant(self, called: str):
        from sqlalchemy import select
        from vyonix.pacs.models import PacsAeRoute
        from vyonix.tenancy import service as tenancy
        if self.plat.edge:
            if called.upper() != self.ae_title.upper():
                return None
            return tenancy.resolve(self.plat.db, self.plat.cfg.default_organization)
        with self.plat.db.service_session() as s:
            return s.execute(select(PacsAeRoute.tenant_id).where(PacsAeRoute.called_aet == called.upper())).scalar()

    def _on_requested(self, event) -> None:
        from vyonix.pacs import service as pacs
        assoc = event.assoc
        rq = assoc.requestor.primitive
        calling, called = str(rq.calling_ae_title).strip(), str(rq.called_ae_title).strip()
        address = assoc.requestor.address
        try:
            tid = self._tenant(called)
            if tid is None:
                log.warning("Q/R: AE chamado desconhecido %s (de %s@%s)", called, calling, address)
                if self.plat.edge:                                  # edge: a organização é a do servidor
                    self._record(self._edge_tenant(), "rejected", calling, called, address,
                                 f"AE Title chamado desconhecido ({called}); o correto é {self.ae_title}")
                assoc.acse.send_reject(0x01, 0x01, 0x07)           # called AE title not recognised
                return
            with self.plat.db.session(tid) as s:
                node = pacs.node_for(s, calling, address=address, query=True)
                # equipamento só de envio também associa, mas só para o storage commitment (N-ACTION)
                store_node = pacs.node_for(s, calling, address=address, store=True) if node is None else None
                if node is None and store_node is None:
                    from vyonix.pacs import nodes as dnodes
                    why = dnodes.refusal_reason(s, calling, address=address, service="query")
            if node is None and store_node is not None:
                self._record(tid, "accepted", calling, called, address, "Somente storage commitment")
                with self._lock:
                    self._ctx[id(assoc)] = {"tenant": tid, "calling": calling.upper(), "address": address,
                                            "can_receive": False, "can_query": False, "can_store": True}
                return
            if node is None:
                log.warning("Q/R: %s@%s não autorizado a consultar (AE chamado %s)", calling, address, called)
                self._record(tid, "rejected", calling, called, address, why)
                assoc.acse.send_reject(0x01, 0x01, 0x03)           # calling AE title not recognised
                return
            self._record(tid, "accepted", calling, called, address, None)
            with self._lock:
                self._ctx[id(assoc)] = {"tenant": tid, "calling": calling.upper(), "address": address,
                                        "can_receive": bool(node.can_receive), "can_query": True,
                                        "can_store": bool(node.can_store)}
        except Exception:  # noqa: BLE001 - na dúvida, recusa
            log.exception("Q/R: falha ao avaliar associação; recusando")
            assoc.acse.send_reject(0x02, 0x01, 0x01)

    def _edge_tenant(self):
        from vyonix.tenancy import service as tenancy
        return tenancy.resolve(self.plat.db, self.plat.cfg.default_organization)

    def _record(self, tid, outcome: str, calling: str, called: str, address: str | None, detail: str | None,
                service: str = "association") -> None:
        """Histórico de conexões da organização (aceitas e recusadas). Falha aqui nunca derruba a associação."""
        if tid is None:
            return
        try:
            from vyonix.pacs import nodes as dnodes
            with self.plat.db.session(tid) as s:
                dnodes.record(s, direction="in", service=service, outcome=outcome, calling_ae=calling,
                              called_ae=called, address=address, detail=detail)
        except Exception:  # noqa: BLE001
            log.exception("Q/R: falha ao registrar o histórico de conexões")

    def _on_end(self, event) -> None:
        with self._lock:
            self._ctx.pop(id(event.assoc), None)

    def _info(self, event, need: str = "query") -> dict[str, Any] | None:
        """Contexto da associação, se o nó tiver a permissão do serviço pedido (``query`` ou ``store``)."""
        with self._lock:
            info = self._ctx.get(id(event.assoc))
        if info is not None and not info.get("can_query" if need == "query" else "can_store"):
            self._record(info["tenant"], "rejected", info["calling"], self.ae_title, info["address"],
                         "Equipamento sem permissão para consultar" if need == "query"
                         else "Equipamento sem permissão para enviar estudos (storage commitment)")
            return None
        return info

    # ------------------------------------------------------------------ C-FIND
    def _on_find(self, event):
        from pydicom.dataset import Dataset
        from vyonix.audit import service as audit
        from vyonix.errors import NotFound, ValidationFailed
        from vyonix.pacs import service as pacs
        info = self._info(event)
        if info is None:
            yield 0xC000, None
            return
        ident = event.identifier
        if str(event.context.abstract_syntax) == MWL:
            yield from self._worklist(event, info, ident)
            return
        level = _value(ident, "QueryRetrieveLevel").upper()
        try:
            with self.plat.db.session(info["tenant"]) as s:
                if level == "STUDY":
                    params = {k: _value(ident, kw) for k, kw in STUDY_KEYS.items() if _value(ident, kw)}
                    results = pacs.search_studies(s, params, limit=500)
                elif level == "SERIES":
                    results = pacs.search_series(s, _value(ident, "StudyInstanceUID"),
                                                 {"Modality": _value(ident, "Modality")} if _value(ident, "Modality") else {})
                elif level == "IMAGE":
                    results = pacs.search_instances(s, _value(ident, "StudyInstanceUID"),
                                                    _value(ident, "SeriesInstanceUID") or None)
                else:
                    yield 0xA900, None                             # identificador não confere com a classe SOP
                    return
                audit.record(s, actor=f"dicom:{info['calling']}", action="pacs.qr.find", target_type="dicom",
                             details={"level": level, "calling_ae": info["calling"], "address": info["address"],
                                      "results": len(results)}, ip=info["address"])
        except (NotFound, ValidationFailed):
            return                                                 # sem resultados (estudo inexistente, data inválida)
        requested = {el.keyword for el in ident if el.keyword}
        for j in results:
            if event.is_cancelled:
                yield 0xFE00, None
                return
            full = Dataset.from_json(j)
            out = Dataset()
            out.QueryRetrieveLevel = level
            for kw in requested - {"QueryRetrieveLevel"}:
                out.add_new(ident[kw].tag, ident[kw].VR, full.get(kw, ident[kw].value) if kw in full else None)
            out.RetrieveAETitle = self.ae_title
            yield 0xFF00, out

    # ------------------------------------------------------------------ Modality Worklist (RIS)
    def _worklist(self, event, info, ident):
        """C-FIND da worklist: só com o RIS habilitado e licenciado (trabalho novo); filtros por modalidade, AE da
        estação, data (ou intervalo), paciente e número de acesso."""
        from datetime import date
        from vyonix.audit import service as audit
        from vyonix.errors import NotLicensed
        from vyonix.modules import registry
        from vyonix.ris import service as ris

        def day(t: str):
            t = t.strip()
            return date(int(t[:4]), int(t[4:6]), int(t[6:8])) if len(t) == 8 and t.isdigit() else None
        sps = ident.ScheduledProcedureStepSequence[0] if "ScheduledProcedureStepSequence" in ident and \
            len(ident.ScheduledProcedureStepSequence) else None
        rng = _value(sps, "ScheduledProcedureStepStartDate") if sps is not None else ""
        a, _, b = rng.partition("-")
        d_from, d_to = day(a), (day(b) if "-" in rng else day(a))
        with self.plat.db.session(info["tenant"]) as s:
            if not registry.is_enabled(s, "ris"):
                yield 0xC001, None                                   # worklist indisponível nesta organização
                return
            try:
                self.plat.licensing.require_module(s, "ris")
            except NotLicensed:
                yield 0xC001, None
                return
            if not ris.workflow(s)["worklist"]:
                yield 0xC001, None                                   # worklist desligada no fluxo da instituição
                return
            entries = ris.worklist(
                s, date_from=d_from, date_to=d_to,
                modality=(_value(sps, "Modality") if sps is not None else "") or None,
                station_aet=(_value(sps, "ScheduledStationAETitle") if sps is not None else "") or None,
                patient_id=_value(ident, "PatientID").replace("*", "") or None,
                patient_name=_value(ident, "PatientName") or None,
                accession=_value(ident, "AccessionNumber") or None)
            audit.record(s, actor=f"dicom:{info['calling']}", action="ris.mwl.find", target_type="dicom",
                         details={"calling_ae": info["calling"], "address": info["address"], "results": len(entries)},
                         ip=info["address"])
        requested = {el.keyword for el in ident if el.keyword}
        for e in entries:
            if event.is_cancelled:
                yield 0xFE00, None
                return
            full = ris.mwl_dataset(e)
            out = type(full)()
            out.SpecificCharacterSet = full.SpecificCharacterSet
            for kw in requested:
                if kw in full:
                    setattr(out, kw, full[kw].value)
            yield 0xFF00, out

    # ------------------------------------------------------------------ MPPS (RIS)
    def _ris_ok(self, s) -> bool:
        from vyonix.errors import NotLicensed
        from vyonix.modules import registry
        if not registry.is_enabled(s, "ris"):
            return False
        try:
            self.plat.licensing.require_module(s, "ris")
        except NotLicensed:
            return False
        return True

    def _on_n_create(self, event):
        """MPPS N-CREATE: exame iniciado na modalidade (vincula ao agendamento pelo SPS ID ou Study Instance UID)."""
        from pydicom.dataset import Dataset
        from vyonix.ris import service as ris
        info = self._info(event)
        if info is None or str(event.request.AffectedSOPClassUID) != MPPS:
            return 0x0110, None
        uid = str(event.request.AffectedSOPInstanceUID or "")
        if not uid:
            return 0x0120, None                                        # missing attribute (o SCU deve informar o UID)
        ds = event.attribute_list
        ssa = ds.ScheduledStepAttributesSequence[0] if "ScheduledStepAttributesSequence" in ds and \
            len(ds.ScheduledStepAttributesSequence) else Dataset()
        try:
            with self.plat.db.session(info["tenant"]) as s:
                if not self._ris_ok(s):
                    return 0x0110, None
                ris.mpps_create(s, uid, sps_id=_value(ssa, "ScheduledProcedureStepID") or None,
                                study_uid=_value(ssa, "StudyInstanceUID") or None,
                                status=_value(ds, "PerformedProcedureStepStatus"), calling_ae=info["calling"])
        except ris.MppsError as exc:
            log.warning("MPPS N-CREATE recusado (%s): %s", info["calling"], exc)
            return exc.status, None
        return 0x0000, ds

    def _on_n_set(self, event):
        """MPPS N-SET: andamento/conclusão (COMPLETED conclui o agendamento; DISCONTINUED o devolve à fila)."""
        from vyonix.ris import service as ris
        info = self._info(event)
        if info is None or str(event.request.RequestedSOPClassUID) != MPPS:
            return 0x0110, None
        uid = str(event.request.RequestedSOPInstanceUID or "")
        mod = event.modification_list
        try:
            with self.plat.db.session(info["tenant"]) as s:
                if not self._ris_ok(s):
                    return 0x0110, None
                ris.mpps_set(s, uid, status=_value(mod, "PerformedProcedureStepStatus") or None,
                             calling_ae=info["calling"], performed=ris.performed_from(mod),
                             summary=ris.summary_from(mod))
        except ris.MppsError as exc:
            log.warning("MPPS N-SET recusado (%s): %s", info["calling"], exc)
            return exc.status, None
        return 0x0000, mod

    # ------------------------------------------------------------------ Storage Commitment (N-ACTION)
    def _on_n_action(self, event):
        """Pedido de storage commitment: responde ao N-ACTION e envia o resultado (N-EVENT-REPORT) em seguida,
        numa associação nova para o equipamento (ver ``vyonix.pacs.commitment``)."""
        from vyonix.pacs.commitment import PUSH_MODEL, PUSH_MODEL_INSTANCE, handle_request
        info = self._info(event, need="store")
        req = event.request
        if info is None:
            return 0x0124, None                                    # recusado: sem permissão
        if str(req.RequestedSOPClassUID) != PUSH_MODEL or str(req.RequestedSOPInstanceUID) != PUSH_MODEL_INSTANCE \
                or event.action_type != 1:
            return 0x0123, None                                    # ação não suportada
        ds = event.action_information
        tx = str(ds.get("TransactionUID", "") or "").strip()
        seq = ds.get("ReferencedSOPSequence") or []
        refs = [(str(x.ReferencedSOPClassUID), str(x.ReferencedSOPInstanceUID)) for x in seq
                if "ReferencedSOPClassUID" in x and "ReferencedSOPInstanceUID" in x]
        if not tx or not refs:
            return 0x0120, None                                    # atributo obrigatório ausente
        if len(refs) > 10000:
            return 0x0110, None

        def later():
            try:
                handle_request(self.plat, self.backend, tenant=info["tenant"], calling=info["calling"],
                               address=info["address"], transaction_uid=tx, refs=refs, our_ae=self.ae_title)
            except Exception:  # noqa: BLE001
                log.exception("Storage commitment: falha ao processar o pedido de %s", info["calling"])
        threading.Thread(target=later, name="vyx-commitment", daemon=True).start()
        return 0x0000, None

    # ------------------------------------------------------------------ C-MOVE
    def _on_move(self, event):
        import hashlib
        from pydicom import dcmread
        from pynetdicom.presentation import build_context
        from vyonix.audit import service as audit
        from vyonix.errors import NotFound
        from vyonix.pacs import service as pacs
        info = self._info(event)
        if info is None:
            yield None, None
            return
        ident = event.identifier
        level = _value(ident, "QueryRetrieveLevel").upper()
        dest = str(event.move_destination).strip().upper()
        with self.plat.db.session(info["tenant"]) as s:
            node = pacs.node_for(s, dest, receive=True)
            if node is None:
                log.warning("Q/R: destino de C-MOVE %s não cadastrado para receber (pedido de %s)", dest,
                            info["calling"])
                from vyonix.pacs import nodes as dnodes
                dnodes.record(s, direction="in", service="move", outcome="rejected", calling_ae=info["calling"],
                              called_ae=self.ae_title, address=info["address"],
                              detail=f"Destino {dest}: " + dnodes.refusal_reason(s, dest, address=None,
                                                                                 service="receive"))
                yield None, None                                   # 0xA801: destino desconhecido
                return
            try:
                items = pacs.instances_for_retrieve(
                    s, level, _value(ident, "StudyInstanceUID"), _value(ident, "SeriesInstanceUID") or None,
                    [u for u in _value(ident, "SOPInstanceUID").split(",") if u] or None)
            except NotFound:
                items = []
            refs = [(i.backend_id, i.sha256, i.sop_class_uid, i.transfer_syntax) for i in items]
            host, port = node.host, node.port
            if items:
                pacs.open_study(s, _value(ident, "StudyInstanceUID"), actor=f"dicom:{info['calling']}",
                                ip=info["address"], purpose="dimse-move")
        contexts = []
        for pair in sorted({(c, t) for _b, _h, c, t in refs})[:128]:
            contexts.append(build_context(*pair))
        yield host, port, {"contexts": contexts or [build_context(VERIFICATION)]}
        yield len(refs)
        sent = failed = 0
        for backend_id, sha, _c, _t in refs:
            if event.is_cancelled:
                yield 0xFE00, None
                return
            data = self.backend.fetch(backend_id)
            if hashlib.sha256(data).hexdigest() != sha:
                failed += 1
                log.error("Q/R: integridade não confere para %s; instância não enviada", backend_id)
                continue
            sent += 1
            yield 0xFF00, dcmread(io.BytesIO(data))
        with self.plat.db.session(info["tenant"]) as s:
            audit.record(s, actor=f"dicom:{info['calling']}", action="pacs.qr.move", target_type="dicom",
                         details={"level": level, "calling_ae": info["calling"], "destination": dest,
                                  "instances": len(refs), "sent": sent, "integrity_failures": failed},
                         ip=info["address"])

    # ------------------------------------------------------------------ C-GET
    def _on_get(self, event):
        """Recuperação na própria associação: só se o nó solicitante também pode receber; SHA-256 conferido."""
        import hashlib
        from pydicom import dcmread
        from vyonix.audit import service as audit
        from vyonix.errors import NotFound
        from vyonix.pacs import service as pacs
        info = self._info(event)
        if info is None or not info.get("can_receive"):
            if info is not None:
                log.warning("Q/R: %s pediu C-GET sem permissão de receber", info["calling"])
            yield 1                                                        # (0 sub-operações = sucesso no pynetdicom)
            yield 0xC002, None                                             # recusado: sem permissão de receber
            return
        ident = event.identifier
        level = _value(ident, "QueryRetrieveLevel").upper()
        with self.plat.db.session(info["tenant"]) as s:
            try:
                items = pacs.instances_for_retrieve(
                    s, level, _value(ident, "StudyInstanceUID"), _value(ident, "SeriesInstanceUID") or None,
                    [u for u in _value(ident, "SOPInstanceUID").split(",") if u] or None)
            except NotFound:
                items = []
            refs = [(i.backend_id, i.sha256) for i in items]
            if items:
                pacs.open_study(s, _value(ident, "StudyInstanceUID"), actor=f"dicom:{info['calling']}",
                                ip=info["address"], purpose="dimse-get")
        yield len(refs)
        sent = failed = 0
        for backend_id, sha in refs:
            if event.is_cancelled:
                yield 0xFE00, None
                return
            data = self.backend.fetch(backend_id)
            if hashlib.sha256(data).hexdigest() != sha:
                failed += 1
                log.error("Q/R: integridade não confere para %s; instância não enviada", backend_id)
                continue
            sent += 1
            yield 0xFF00, dcmread(io.BytesIO(data))
        with self.plat.db.session(info["tenant"]) as s:
            audit.record(s, actor=f"dicom:{info['calling']}", action="pacs.qr.get", target_type="dicom",
                         details={"level": level, "calling_ae": info["calling"], "instances": len(refs),
                                  "sent": sent, "integrity_failures": failed}, ip=info["address"])
