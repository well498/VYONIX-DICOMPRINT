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
from dataclasses import dataclass
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


@dataclass
class Prepared:
    pages: Callable[[], Any]
    pages_total: int
    paper: str
    width_mm: float
    height_mm: float
    orientation: str
    dpi: int
    warnings: list[str]
    compositor: Any = None


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
                 license=None, templates=None) -> None:
        self.license = license
        self.templates = templates
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
                    job = None if self.suspended() else self._claim()
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

    def suspended(self) -> str | None:
        """Motivo da suspensão da impressão pela licença (os trabalhos aguardam na fila)."""
        if self.license is None or self.license.allows("printing"):
            return None
        return self.license.suspension_reason() or "impressão não incluída na licença"

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
            if self.license is not None:
                ok, why = self.license.printer_allowed(printer)
                if not ok:
                    raise PermanentError(why)
            resolved.spec().validate()
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
            prep = self.prepare(job, resolved, items, printer=printer, backend=backend)
        except (DecodeError, OSError, ValidationError, PermanentError) as exc:
            self._fail(job, f"Não foi possível preparar as imagens: {exc}", permanent=True)
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha ao preparar trabalho %s", jid)
            self._fail(job, f"Falha ao preparar as páginas: {exc}", permanent=False)
            return

        doc = f"VYONIX-{jid}" + (f"-{job.modality}" if job.modality else "")   # sem dados do paciente
        pid = self.printers.printer_id(printer)
        if not self.jobs.transition(jid, JobState.WAITING_PRINT, actor=ACTOR, expect=JobState.PROCESSING,
                                    page_count=prep.pages_total, document_name=doc, printer_id=pid):
            return
        # Marca o envio ANTES de chamar o spooler: se o processo cair durante o envio, a
        # recuperação retém o trabalho em vez de imprimir de novo.
        self.jobs.update_fields(jid, submitted_at=utc_now_iso())
        request = SpoolRequest(printer=printer, document_name=doc, pages=prep.pages, page_count=prep.pages_total,
                               copies=int(job.copies), paper=prep.paper, width_mm=prep.width_mm,
                               height_mm=prep.height_mm, orientation=prep.orientation, dpi=prep.dpi)
        result = backend.submit(request)
        if not result.accepted:
            self.jobs.update_fields(jid, submitted_at=None)
            job = self.jobs.get_job(jid)
            self._fail(job, result.error or "O spooler recusou o trabalho.", permanent=False)
            return
        notes = "; ".join(x for x in (result.detail, *prep.warnings) if x) or None
        self.jobs.transition(jid, JobState.SPOOLED, actor=ACTOR, expect=JobState.WAITING_PRINT,
                             reason=notes, spool_job_id=result.spool_job_id,
                             output_path=result.output_path, spool_status="enviado")
        self.events.add(level="INFO", category=Category.SPOOLER, action="job.spooled",
                        message=f"Trabalho #{jid}: {prep.pages_total} página(s) enviada(s) para \u201c{printer}\u201d"
                                + (f" (spooler nº {result.spool_job_id})" if result.spool_job_id else "") + ".",
                        device_id=job.device_id, job_id=jid, actor="system",
                        details={"detail": result.detail, "copies": job.copies})
        for w in prep.warnings:
            self.events.add(level="WARNING", category=Category.PROCESSING, action="job.warning",
                            message=f"Trabalho #{jid}: {w}", device_id=job.device_id, job_id=jid, actor="system")
        if result.confirmed:
            self.jobs.transition(jid, JobState.COMPLETED, actor=ACTOR, expect=JobState.SPOOLED,
                                 reason="Saída confirmada: " + "; ".join(x for x in (result.detail, *prep.warnings) if x),
                                 spool_status="concluído")
        elif result.error:
            self.jobs.update_fields(jid, state_reason=result.error)

    # ---------------------------------------------------------------- preparação (impressão e pré-visualização)
    def prepare(self, job: Job, resolved: Resolved, items: list[dict], *, printer: str | None = None,
                backend=None) -> "Prepared":
        """Monta a fábrica de páginas exatamente como será impressa. Usada também pela pré-visualização,
        para que tela e papel nunca divirjam."""
        from dataclasses import replace as dc_replace
        warnings: list[str] = []
        values = resolved.values
        spec = resolved.spec()
        spec = dc_replace(spec, identity_max_height_mm=float(self.get("print_identity.max_height_mm") or 0),
                          min_effective_dpi=int(self.get("printing.min_effective_dpi") or 0))
        if values.get("sheet"):
            return self._prepare_sheet(job, resolved, printer)
        header_img = footer_img = None
        if self.templates is not None:
            if spec.header_image:
                header_img, w = self.templates.load("header")
                warnings += [w] if w else []
            if spec.footer_image:
                footer_img, w = self.templates.load("footer")
                warnings += [w] if w else []
        first_aspect = None
        if items:
            size = self.imaging.size_of(items[0]["file_path"])
            first_aspect = size[0] / size[1] if size and size[1] else None
        comp = Compositor(spec, first_aspect, header_img=header_img, footer_img=footer_img)
        # Área não imprimível da impressora (quando o driver informa): margens nunca menores que ela.
        if backend is not None and printer and hasattr(backend, "printable_margins_mm"):
            try:
                hw = backend.printable_margins_mm(printer, spec.paper, comp.geom.width_mm, comp.geom.height_mm,
                                                  comp.orientation)
            except Exception as exc:  # noqa: BLE001
                hw = None
                log.info("Área imprimível não informada: %s", exc)
            if hw:
                spec = dc_replace(spec, hardware_margins_mm=tuple(hw), orientation=comp.orientation)
                comp = Compositor(spec, first_aspect, header_img=header_img, footer_img=footer_img)
        keep = bool(values.get("keep_positions"))
        if job.source_type == "test_page":
            count = 1
        elif keep:   # posições fixas (DICOM Print): células vazias continuam vazias
            last = max(int(it["position"]) for it in items) + 1
            count = -(-last // comp.cells) * comp.cells
        else:
            count = len(items)
        annotations = self._annotations(job, resolved, items)
        get_image = self._image_source(job, items, comp, keep, resolved.tone())
        first = 0 if not keep else (int(items[0]["position"]) if items else 0)
        if count:
            get_image(first)       # decodifica já aqui, para falhar antes do spooler
        geom = PageGeometry.build(spec.paper, comp.orientation, spec.custom_mm)
        prep = Prepared(pages=lambda: comp.iter_pages(count, get_image, annotations), pages_total=comp.page_count(count),
                        paper=spec.paper, width_mm=geom.width_mm, height_mm=geom.height_mm,
                        orientation=comp.orientation, dpi=spec.dpi, warnings=warnings, compositor=comp)
        return prep

    def _prepare_sheet(self, job: Job, resolved: Resolved, printer: str | None) -> "Prepared":
        from app.imaging import tone as tone_mod
        from app.imaging.calibration import CalibrationProfile
        from app.printing import calibration_sheet as cs
        from app.printing.calibration_rounds import CalibrationService
        sheet = resolved.values["sheet"]
        matrix = cs.build_matrix(tone_mod.ToneControls.from_values(sheet["center"]), sheet["mode"], float(sheet["step"]))
        source = CalibrationService.resolve_source(sheet["source"])
        paper = resolved.values["paper"]
        orientation = resolved.values.get("orientation") or "landscape"
        orientation = orientation if orientation in ("portrait", "landscape") else "landscape"
        dpi = min(int(resolved.values.get("dpi") or 200), 300)
        cal = CalibrationProfile.from_json(resolved.values.get("calibration"))
        info = cs.sheet_info(device=sheet.get("device"), modality=sheet.get("modality"), printer=printer, paper=paper)

        def render(params, max_side):
            return self.imaging.render(source, params, max_side=max_side)
        render(matrix.cells[0].tone.to_params(), 64)      # valida a fonte antes do spooler
        geom = PageGeometry.build(paper, orientation)
        return Prepared(pages=lambda: iter([cs.compose(matrix, render, paper=paper, orientation=orientation, dpi=dpi,
                                                       info=info, calibration=cal)]),
                        pages_total=1, paper=paper, width_mm=geom.width_mm, height_mm=geom.height_mm,
                        orientation=orientation, dpi=dpi, warnings=list(matrix.notes), compositor=None)

    def preview_device(self, device_id: int | None, instance_id: int | None = None,
                       resolved: Resolved | None = None) -> tuple[list, list[str], Resolved]:
        """Página como sairia para um equipamento (com uma imagem recebida ou o padrão de teste),
        pelo mesmo caminho de impressão — sem criar trabalho."""
        from types import SimpleNamespace
        conn = self.db.connection()
        dev = conn.execute("SELECT name, ae_title, modality FROM devices WHERE id = ?", (device_id,)).fetchone() \
            if device_id else None
        modality = dev["modality"] if dev else None
        items = []
        if instance_id is not None:
            r = conn.execute("SELECT file_path, received_at, modality FROM instances WHERE id = ?",
                             (instance_id,)).fetchone()
            if r is None:
                raise ValidationError("Imagem não encontrada (pode ter sido removida pela retenção).")
            items = [{"file_path": r["file_path"], "frame_index": 0, "position": 0, "received_at": r["received_at"],
                      "instance_id": instance_id}]
            modality = r["modality"] or modality
        if resolved is None:
            ev = self.jobs.evaluate_rules(source_type="storage" if items else "test_page",
                                          source_ae=dev["ae_title"] if dev else None, device_id=device_id,
                                          modality=modality, items=[(instance_id, 0)] if items else [])
            resolved = self.jobs.resolve_for(device_id=device_id, modality=modality, rules=ev)
        job = SimpleNamespace(id=0, source_type="storage" if items else "test_page", modality=modality,
                              device_name=dev["name"] if dev else None, source_ae=dev["ae_title"] if dev else None,
                              created_at=utc_now_iso(), device_id=device_id)
        printer = backend = None
        try:
            printer = self.printers.resolve(resolved.values.get("printer") or None)
            backend = self.printers.backend_for(printer)
        except Exception:  # noqa: BLE001
            pass
        prep = self.prepare(job, resolved, items, printer=printer, backend=backend)
        pages = list(prep.pages())[:1]
        warnings = list(prep.warnings) + (list(prep.compositor.warnings) if prep.compositor else [])
        return pages, warnings, resolved

    def preview(self, job_id: int, max_pages: int = 4) -> tuple[list, list[str]]:
        """Páginas do trabalho como serão impressas (sem enviar ao spooler)."""
        job = self.jobs.get_job(job_id)
        resolved = Resolved(dict(job.settings), dict(job.origins), job.profile_id)
        printer = None
        backend = None
        try:
            printer = self.printers.resolve(resolved.values.get("printer") or None)
            backend = self.printers.backend_for(printer)
        except Exception:  # noqa: BLE001 - pré-visualização sem impressora: sem margens físicas
            pass
        prep = self.prepare(job, resolved, self.jobs.items(job_id), printer=printer, backend=backend)
        pages = []
        for page in prep.pages():
            pages.append(page)
            if len(pages) >= max_pages:
                break
        warnings = list(prep.warnings) + (list(prep.compositor.warnings) if prep.compositor else [])
        return pages, warnings

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
                      keep_positions: bool = False, tone=None) -> Callable[[int], RenderedImage | None]:
        if job.source_type == "test_page":
            x, y, w, h = comp.cell_rects_mm()[0]
            wpx, hpx = round(w * comp.px_per_mm), round(h * comp.px_per_mm)

            def pattern(_i: int) -> RenderedImage:
                px = calibration.test_pattern(wpx, hpx, dpi=comp.spec.dpi, title="VYONIX — página de teste")
                if tone is not None and not tone.is_neutral():
                    from app.imaging.pipeline import adjust, to_uint8
                    v, _ = adjust(px.astype("float32") / 255.0, tone.to_params())
                    px = to_uint8(v)
                return RenderedImage(pixels=px, photometric="MONOCHROME2", pixel_spacing_mm=None,
                                     applied={"source": "padrão de teste"})
            return pattern

        by_pos = {int(it["position"]): it for it in items}

        def render(i: int) -> RenderedImage | None:
            it = by_pos.get(i) if keep_positions else items[i]
            if it is None:
                return None
            params = PresentationParams(frame_index=int(it["frame_index"]))
            if tone is not None:
                params = tone.to_params(params)     # brilho/contraste/gama do equipamento, em ponto flutuante
            return self.imaging.render(it["file_path"], params, max_side=None)
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
        mark = self.license.mark_text() if self.license is not None else None
        if mark:
            footer = f"{mark} · {footer}"
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
