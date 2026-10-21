"""Processamento da fila: agrupamento automático, montagem das páginas, envio e acompanhamento.

Um único processador (thread) executa os trabalhos em ordem de prioridade e chegada — adequado
a PCs modestos: uma página montada por vez, memória previsível.

Ciclo de um trabalho::

    Recebido → Validando → Processando → Aguardando impressão → Enviado → (Concluído)

* **Falhas transitórias** (spooler, impressora offline, erro inesperado) voltam a ser tentadas
  automaticamente até ``jobs.max_attempts``, com intervalo ``jobs.retry_delay_seconds``.
* **Falhas permanentes** (imagem removida, arquivo ilegível, configuração inválida) param em
  "Falhou" e aguardam ação do usuário.
* **Recuperação**: ao iniciar, trabalhos interrompidos no meio voltam para a fila; um trabalho
  que já podia ter chegado ao spooler fica **Retido** para conferência — o VYONIX nunca
  reimprime por conta própria algo que talvez já tenha saído no papel.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any, Callable

from app.core.contracts import (PresentationParams, ReceivedInstance, RenderedImage, SpoolRequest)
from app.core.errors import ValidationError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.imaging import calibration
from app.imaging.decoder import DecodeError
from app.jobs.service import Job, JobService, group_key
from app.jobs.states import JobState
from app.printing.layout_engine import Compositor, PageAnnotations
from app.printing.paper import PageGeometry
from app.printing.resolver import Resolved
from app.printing.service import PrinterService
from app.utils.logging_setup import get_logger
from app.utils.timeutil import to_iso, utc_now, utc_now_iso

log = get_logger("jobs.worker")

MAX_FRAMES_PER_INSTANCE = 16
SPOOL_POLL_S = 10
SPOOL_WATCH_HOURS = 24
ACTOR = "processador"


class PermanentError(Exception):
    """Falha que não se resolve tentando de novo."""


class AutoPrintCollector:
    """``InstanceSink`` do Storage SCP: registra a instância para impressão automática por série.

    O registro é persistido (``autoprint_pending``) antes de qualquer agrupamento, então uma queda
    do processo não perde o pedido. O trabalho é criado quando a série fica ``jobs.collect_seconds``
    sem receber imagens.
    """

    def __init__(self, db: Database, jobs: JobService, settings_get: Callable[[str], Any]) -> None:
        self.db = db
        self.jobs = jobs
        self.get = settings_get

    def on_instance_received(self, instance: ReceivedInstance) -> None:
        if not self.get("jobs.auto_print"):
            return
        conn = self.db.connection()
        row = conn.execute("SELECT id FROM instances WHERE sop_instance_uid = ?",
                           (instance.sop_instance_uid,)).fetchone()
        if row is None:
            return
        origin = str(instance.device_id) if instance.device_id else instance.peer.calling_ae
        conn.execute("""INSERT OR IGNORE INTO autoprint_pending(instance_id, group_key, device_id, source_ae,
                            modality, received_at) VALUES (?, ?, ?, ?, ?, ?)""",
                     (row["id"], f"{origin}|{instance.series_uid}", instance.device_id, instance.peer.calling_ae,
                      instance.modality, utc_now_iso()))

    def flush(self, force: bool = False) -> list[int]:
        """Cria trabalhos para as séries sem novas imagens há ``collect_seconds``."""
        conn = self.db.connection()
        cutoff = to_iso(utc_now() - timedelta(seconds=0 if force else int(self.get("jobs.collect_seconds"))))
        groups = conn.execute("""SELECT group_key, MAX(received_at) AS last FROM autoprint_pending
                                 GROUP BY group_key HAVING last <= ?""", (cutoff,)).fetchall()
        created = []
        for g in groups:
            rows = conn.execute(
                """SELECT a.instance_id, a.device_id, a.source_ae, a.modality, i.sop_instance_uid, i.file_path,
                          i.number_of_frames FROM autoprint_pending a JOIN instances i ON i.id = a.instance_id
                   WHERE a.group_key = ?""", (g["group_key"],)).fetchall()
            if not rows:
                continue
            ordered = sorted(rows, key=lambda r: (_instance_number(r["file_path"]), r["sop_instance_uid"]))
            items, truncated = [], False
            for r in ordered:
                frames = int(r["number_of_frames"] or 1)
                if frames > MAX_FRAMES_PER_INSTANCE:
                    truncated, frames = True, 1
                items += [(r["instance_id"], f) for f in range(frames)]
            key = group_key([r["sop_instance_uid"] for r in rows], "storage")
            first = rows[0]
            reason = (f"Multiframe com mais de {MAX_FRAMES_PER_INSTANCE} quadros: impresso só o 1º quadro"
                      if truncated else None)
            try:
                job_id, new = self.jobs.create(source_type="storage", items=items, idempotency_key=key,
                                               device_id=first["device_id"], source_ae=first["source_ae"],
                                               modality=first["modality"], reason=reason)
            except Exception:  # noqa: BLE001 - mantém pendente para nova tentativa
                log.exception("Falha ao criar trabalho automático")
                continue
            with self.db.transaction():
                conn.execute("DELETE FROM autoprint_pending WHERE group_key = ?", (g["group_key"],))
            if new:
                created.append(job_id)
            else:
                self.jobs.events.add(level="INFO", category=Category.JOB, action="job.duplicate",
                                     message=f"Série reenviada já tem o trabalho #{job_id}; nada foi impresso de "
                                             "novo (use Reimprimir se desejar outra cópia).",
                                     device_id=first["device_id"], job_id=job_id, actor="system")
        return created


def _instance_number(path: str) -> int:
    try:
        import pydicom
        ds = pydicom.dcmread(path, stop_before_pixels=True, specific_tags=["InstanceNumber"])
        return int(ds.get("InstanceNumber") or 0)
    except Exception:  # noqa: BLE001
        return 0


class PrintWorker:
    def __init__(self, *, db: Database, events: EventRepository, jobs: JobService, printers: PrinterService,
                 imaging, collector: AutoPrintCollector, settings_get: Callable[[str], Any],
                 license=None) -> None:
        self.license = license
        self.db = db
        self.events = events
        self.jobs = jobs
        self.printers = printers
        self.imaging = imaging
        self.collector = collector
        self.get = settings_get
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_spool_poll = 0.0
        self.current_job: int | None = None
        self.last_error: str | None = None

    # ---------------------------------------------------------------- ciclo de vida
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.recover()
        self._thread = threading.Thread(target=self._run, name="vyonix-print-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 15.0) -> None:
        self._stop.set()
        self.jobs.wakeup.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def recover(self) -> None:
        conn = self.db.connection()
        for r in conn.execute("SELECT id, state, submitted_at FROM jobs WHERE state IN "
                              "('validating','processing','waiting_print')").fetchall():
            state = JobState(r["state"])
            if state == JobState.WAITING_PRINT and r["submitted_at"]:
                self.jobs.transition(r["id"], JobState.HELD, actor="recuperação",
                                     reason="Interrompido durante o envio ao spooler: confira se a impressão saiu "
                                            "antes de liberar (evita impressão duplicada)")
                self.events.add(level="WARNING", category=Category.JOB, action="job.recover.hold",
                                message=f"Trabalho #{r['id']} retido para conferência após interrupção.",
                                job_id=r["id"], actor="system")
            else:
                self.jobs.transition(r["id"], JobState.FAILED, actor="recuperação",
                                     reason="Interrompido por encerramento do programa; será retomado",
                                     next_attempt_at=utc_now_iso())
                self.events.add(level="INFO", category=Category.JOB, action="job.recover.retry",
                                message=f"Trabalho #{r['id']} interrompido será retomado.", job_id=r["id"],
                                actor="system")

    def _run(self) -> None:
        import time
        try:
            while not self._stop.is_set():
                worked = False
                try:
                    self.collector.flush()
                    job = self._claim()
                    if job is not None:
                        worked = True
                        self.process(job)
                    if time.monotonic() - self._last_spool_poll > SPOOL_POLL_S:
                        self._last_spool_poll = time.monotonic()
                        self.poll_spooled()
                except Exception as exc:  # noqa: BLE001 - o processador não pode morrer
                    self.last_error = str(exc)
                    log.exception("Erro no processador da fila")
                if not worked:
                    self.jobs.wakeup.wait(1.0)
                    self.jobs.wakeup.clear()
        finally:
            self.db.close_thread_connection()

    def _claim(self) -> Job | None:
        now = utc_now_iso()
        r = self.db.connection().execute(
            """SELECT id FROM jobs WHERE state IN ('received','validating')
                  OR (state = 'failed' AND next_attempt_at IS NOT NULL AND next_attempt_at <= ?)
               ORDER BY priority DESC, id LIMIT 1""", (now,)).fetchone()
        return self.jobs.get_job(r["id"]) if r else None

    # ---------------------------------------------------------------- processamento
    def process(self, job: Job) -> None:
        self.current_job = job.id
        try:
            self._process(job)
        finally:
            self.current_job = None

    def _process(self, job: Job) -> None:
        jid = job.id
        if job.state in (JobState.RECEIVED, JobState.FAILED):
            if not self.jobs.transition(jid, JobState.VALIDATING, actor=ACTOR, expect=job.state, next_attempt_at=None):
                return
        self.jobs.update_fields(jid, attempts=job.attempts + 1)
        try:
            resolved = Resolved(dict(job.settings), dict(job.origins), job.profile_id)
            printer = self.printers.resolve(resolved.values.get("printer") or None)
            backend = self.printers.backend_for(printer)
            spec = resolved.spec().validate()
            items = self.jobs.items(jid)
            if job.source_type != "test_page":
                missing = [it for it in items if not it["file_path"]]
                if missing or not items:
                    raise PermanentError("Imagens do trabalho não estão mais disponíveis (removidas pela retenção).")
        except (ValidationError, PermanentError) as exc:
            self._fail(job, str(exc), permanent=True)
            return

        if not self.jobs.transition(jid, JobState.PROCESSING, actor=ACTOR, expect=JobState.VALIDATING):
            return
        try:
            first_aspect = None
            if items:
                info = self.imaging.info(items[0]["file_path"])
                first_aspect = info.columns / info.rows if info.rows else None
            comp = Compositor(spec, first_aspect)
            keep = bool(resolved.values.get("keep_positions"))
            if job.source_type == "test_page":
                count = 1
            elif keep:   # posições fixas (DICOM Print): células vazias continuam vazias
                last = max(int(it["position"]) for it in items) + 1
                count = -(-last // comp.cells) * comp.cells
            else:
                count = len(items)
            annotations = self._annotations(job, resolved, items)
            get_image = self._image_source(job, items, comp, keep)
            # Valida o primeiro quadro já aqui (decodificação), para falhar antes do spooler.
            first = 0 if not keep else (int(items[0]["position"]) if items else 0)
            if count:
                get_image(first)
            pages_total = comp.page_count(count)
        except (DecodeError, OSError, ValidationError) as exc:
            self._fail(job, f"Não foi possível preparar as imagens: {exc}", permanent=True)
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha ao preparar trabalho %s", jid)
            self._fail(job, f"Falha ao preparar as páginas: {exc}", permanent=False)
            return

        doc = f"VYONIX-{jid}" + (f"-{job.modality}" if job.modality else "")   # sem dados do paciente
        pid = self.printers.printer_id(printer)
        if not self.jobs.transition(jid, JobState.WAITING_PRINT, actor=ACTOR, expect=JobState.PROCESSING,
                                    page_count=pages_total, document_name=doc, printer_id=pid):
            return
        # Marca o envio ANTES de chamar o spooler: se o processo cair durante o envio, a
        # recuperação retém o trabalho em vez de imprimir de novo.
        self.jobs.update_fields(jid, submitted_at=utc_now_iso())
        geom = PageGeometry.build(spec.paper, comp.orientation, spec.custom_mm)
        request = SpoolRequest(printer=printer, document_name=doc,
                               pages=lambda: comp.iter_pages(count, get_image, annotations), page_count=pages_total,
                               copies=int(job.copies), paper=spec.paper, width_mm=geom.width_mm,
                               height_mm=geom.height_mm, orientation=comp.orientation, dpi=spec.dpi)
        result = backend.submit(request)
        if not result.accepted:
            self.jobs.update_fields(jid, submitted_at=None)
            job = self.jobs.get_job(jid)
            self._fail(job, result.error or "O spooler recusou o trabalho.", permanent=False)
            return
        self.jobs.transition(jid, JobState.SPOOLED, actor=ACTOR, expect=JobState.WAITING_PRINT,
                             reason=result.detail or None, spool_job_id=result.spool_job_id,
                             output_path=result.output_path, spool_status="enviado")
        self.events.add(level="INFO", category=Category.SPOOLER, action="job.spooled",
                        message=f"Trabalho #{jid}: {pages_total} página(s) enviada(s) para “{printer}”"
                                + (f" (spooler nº {result.spool_job_id})" if result.spool_job_id else "") + ".",
                        device_id=job.device_id, job_id=jid, actor="system",
                        details={"detail": result.detail, "copies": job.copies})
        if result.confirmed:
            self.jobs.transition(jid, JobState.COMPLETED, actor=ACTOR, expect=JobState.SPOOLED,
                                 reason=f"Saída confirmada: {result.detail}", spool_status="concluído")
        elif result.error:
            self.jobs.update_fields(jid, state_reason=result.error)

    def _fail(self, job: Job, message: str, *, permanent: bool) -> None:
        current = self.jobs.get_job(job.id)
        attempts = current.attempts
        auto = not permanent and attempts < current.max_attempts
        next_at = to_iso(utc_now() + timedelta(seconds=int(self.get("jobs.retry_delay_seconds")))) if auto else None
        reason = message + (f" — nova tentativa automática ({attempts}/{current.max_attempts})" if auto else "")
        if current.state.is_terminal or current.state == JobState.FAILED:
            return
        if current.state in (JobState.HELD,):
            return
        self.jobs.transition(job.id, JobState.FAILED, actor=ACTOR, reason=reason, next_attempt_at=next_at)
        self.events.add(level="WARNING" if auto else "ERROR", category=Category.JOB, action="job.fail",
                        message=f"Trabalho #{job.id}: {reason}", device_id=job.device_id, job_id=job.id,
                        actor="system")

    # ---------------------------------------------------------------- imagens e anotações
    def _image_source(self, job: Job, items: list[dict], comp: Compositor,
                      keep_positions: bool = False) -> Callable[[int], RenderedImage | None]:
        if job.source_type == "test_page":
            x, y, w, h = comp.cell_rects_mm()[0]
            wpx, hpx = round(w * comp.px_per_mm), round(h * comp.px_per_mm)

            def pattern(_i: int) -> RenderedImage:
                px = calibration.test_pattern(wpx, hpx, dpi=comp.spec.dpi, title="VYONIX — página de teste")
                return RenderedImage(pixels=px, photometric="MONOCHROME2", pixel_spacing_mm=None,
                                     applied={"source": "padrão de teste"})
            return pattern

        by_pos = {int(it["position"]): it for it in items}

        def render(i: int) -> RenderedImage | None:
            it = by_pos.get(i) if keep_positions else items[i]
            if it is None:
                return None
            return self.imaging.render(it["file_path"], PresentationParams(frame_index=int(it["frame_index"])),
                                       max_side=None)
        return render

    def _annotations(self, job: Job, resolved: Resolved, items: list[dict]) -> PageAnnotations:
        from app.utils.timeutil import from_iso as _f
        parts = []
        if job.source_type == "test_page":
            parts.append("Página de teste")
        if job.modality:
            parts.append(job.modality)
        when = items[0]["received_at"] if items and items[0].get("received_at") else job.created_at
        parts.append(_f(when).astimezone().strftime("%d/%m/%Y %H:%M"))
        if job.device_name or job.source_ae:
            parts.append(job.device_name or job.source_ae)
        footer = f"Trabalho #{job.id}"
        if self.license is not None and self.license.evaluation_mode():
            from app.licensing.license import EVALUATION_MARK
            footer = f"{EVALUATION_MARK} · {footer}"
        if resolved.values.get("patient_info") and items:
            patient = _patient_text(items[0]["file_path"])
            if patient:
                parts.insert(0, patient)
        return PageAnnotations(header_right=" · ".join(parts), footer_left=footer)

    # ---------------------------------------------------------------- acompanhamento do spooler
    def poll_spooled(self) -> None:
        since = to_iso(utc_now() - timedelta(hours=SPOOL_WATCH_HOURS))
        rows = self.db.connection().execute(
            """SELECT j.id, j.spool_job_id, j.spool_status, j.device_id, p.name AS printer FROM jobs j
               JOIN printers p ON p.id = j.printer_id
               WHERE j.state = 'spooled' AND j.spool_job_id IS NOT NULL AND j.submitted_at >= ?
                 AND (j.spool_status IS NULL OR j.spool_status NOT IN ('saiu da fila'))""", (since,)).fetchall()
        for r in rows:
            try:
                backend = self.printers.backend_for(r["printer"])
                st = backend.job_status(r["printer"], int(r["spool_job_id"]))
            except Exception as exc:  # noqa: BLE001
                log.info("Não foi possível consultar o spooler: %s", exc)
                continue
            now = utc_now_iso()
            if st.state == "printed":
                self.jobs.transition(r["id"], JobState.COMPLETED, actor="spooler",
                                     reason=f"O spooler do Windows informou: {st.detail}", spool_status="impresso")
            elif st.state == "deleted":
                self.jobs.transition(r["id"], JobState.FAILED, actor="spooler",
                                     reason=f"Excluído da fila do Windows ({st.detail})", spool_status="excluído")
                self.events.add(level="WARNING", category=Category.SPOOLER, action="spool.deleted",
                                message=f"Trabalho #{r['id']} foi excluído da fila do Windows.", job_id=r["id"],
                                device_id=r["device_id"], actor="system")
            elif st.state == "gone":
                self.jobs.update_fields(r["id"], spool_status="saiu da fila", spool_checked_at=now,
                                        state_reason="Saiu da fila do Windows; o driver não informou confirmação "
                                                     "de impressão — confira o papel")
            elif st.state == "error":
                if r["spool_status"] != f"erro: {st.detail}":
                    self.events.add(level="WARNING", category=Category.SPOOLER, action="spool.error",
                                    message=f"Trabalho #{r['id']} na impressora “{r['printer']}”: {st.detail}.",
                                    job_id=r["id"], device_id=r["device_id"], actor="system")
                self.jobs.update_fields(r["id"], spool_status=f"erro: {st.detail}", spool_checked_at=now,
                                        state_reason=f"Impressora: {st.detail}")
            else:
                self.jobs.update_fields(r["id"], spool_status=st.detail or st.state, spool_checked_at=now)


def _patient_text(path: str) -> str:
    """Nome/ID do paciente para o cabeçalho impresso (opção LGPD desativada por padrão).

    Lido do arquivo no momento da impressão; não é gravado no banco nem nos logs.
    """
    try:
        import pydicom
        ds = pydicom.dcmread(path, stop_before_pixels=True, specific_tags=["PatientName", "PatientID"])
        name = str(ds.get("PatientName") or "").replace("^", " ").strip()
        pid = str(ds.get("PatientID") or "").strip()
        return " · ".join(x for x in (name, f"ID {pid}" if pid else "") if x)
    except Exception:  # noqa: BLE001
        return ""
