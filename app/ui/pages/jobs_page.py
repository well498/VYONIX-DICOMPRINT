"""Trabalhos de impressão (§12): fila, estados, detalhes e ações."""

from __future__ import annotations

from app.core.errors import VyonixError
from app.jobs.states import JobState
from app.ui.admin import current_actor
from app.ui.pages.base import Page, banner
from app.ui.pages.printers_page import choose_printer
from app.ui.qt import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QTabWidget,
                       QTimer, QVBoxLayout, QWidget)
from app.ui.widgets import button, button_row, fill_table, local_time, make_table, selected_key, status_text
from app.ui.workers import run_async

FILTERS = (
    ("Na fila e com problema", ("received", "validating", "processing", "waiting_print", "held", "failed",
                                "spooled")),
    ("Todos", None),
    ("Retidos", ("held",)),
    ("Com falha", ("failed",)),
    ("Enviados ao spooler", ("spooled",)),
    ("Concluídos", ("completed",)),
    ("Cancelados", ("cancelled",)),
)
SETTING_LABELS = {
    "printer": "Impressora", "paper": "Papel", "orientation": "Orientação", "layout": "Layout", "dpi": "Resolução (dpi)",
    "margin_mm": "Margens (mm)", "margins_mm": "Margens individuais (mm)", "spacing_mm": "Espaçamento (mm)",
    "copies": "Cópias", "border": "Borda", "header_text": "Cabeçalho", "footer_text": "Rodapé",
    "exam_info": "Informações do exame", "patient_info": "Dados do paciente", "page_numbers": "Numeração",
    "calibration": "Calibração",
    "brightness": "Brilho", "contrast": "Contraste", "gamma": "Gama", "invert": "Inverter",
    "header_enabled": "Cabeçalho BMP", "footer_enabled": "Rodapé BMP", "auto_print": "Impressão automática",
    "dicom_policy": "Prioridade DICOM Print", "extra_margin_mm": "Margem adicional (mm)",
    "header_gap_mm": "Espaço cabeçalho→imagens (mm)", "footer_gap_mm": "Espaço imagens→rodapé (mm)",
}


def _fmt(value) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items())
    if isinstance(value, list):
        return " / ".join(map(str, value))
    return str(value)


class JobsPage(Page):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__("Trabalhos de impressão",
                         "Cada série recebida (ou pedido manual) vira um trabalho. Reenvios idênticos não "
                         "imprimem de novo; para outra cópia, use Reimprimir.", parent)
        self.ctx = ctx
        self.status = banner("")
        self.status.hide()
        self.body.addWidget(self.status)
        top = QHBoxLayout()
        self.filter = QComboBox()
        for label, states in FILTERS:
            self.filter.addItem(label, states)
        self.filter.currentIndexChanged.connect(lambda _: self.refresh())
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por nº, AE Title, equipamento, modalidade ou impressora")
        self.search.returnPressed.connect(self.refresh)
        top.addWidget(QLabel("Mostrar"))
        top.addWidget(self.filter)
        top.addWidget(self.search, 1)
        self.body.addLayout(top)
        self.body.addLayout(button_row(
            button("Detalhes", self.details, primary=True), button("Pré-visualizar página", self.preview),
            button("Reter", self.hold), button("Liberar", self.release),
            button("Tentar de novo", self.retry), button("Reprocessar com config. atuais", self.reprocess),
            button("Reimprimir…", self.reprint), button("Cancelar trabalho", self.cancel), stretch_at=7))
        self.table = make_table(["Nº", "Criado em", "Origem", "Equipamento / AE", "Modalidade", "Imagens", "Páginas",
                                 "Cópias", "Impressora", "Estado", "Detalhe"])
        self.table.doubleClicked.connect(lambda _: self.details())
        self.body.addWidget(self.table, 1)
        self.counts = QLabel("")
        self.counts.setObjectName("muted")
        self.body.addWidget(self.counts)
        self.jobs = {}
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        self._loading = False

    def on_shown(self) -> None:
        self.refresh()
        self.timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - API Qt
        self.timer.stop()
        super().hideEvent(event)

    def refresh(self) -> None:
        if self._loading:
            return
        self._loading = True
        states, text = self.filter.currentData(), self.search.text().strip()

        def work():
            return self.ctx.jobs.list(states=states, search=text), self.ctx.jobs.counts()
        run_async(work, self._render, self._error)

    def _render(self, data) -> None:
        self._loading = False
        jobs, counts = data
        self.jobs = {j.id: j for j in jobs}
        rows = []
        for j in jobs:
            rows.append((j.id, local_time(j.created_at), j.source_label, j.device_name or j.source_ae or "—",
                         j.modality or "—", j.items or "—", j.page_count or "—", j.copies,
                         j.printer or j.settings.get("printer") or "padrão", j.state.label,
                         (j.state_reason or "")[:160]))
        fill_table(self.table, rows, [j.id for j in jobs])
        order = ("received", "validating", "processing", "waiting_print", "held", "failed", "spooled", "completed",
                 "cancelled")
        self.counts.setText("  ·  ".join(f"{JobState(s).label}: {counts[s]}" for s in order if counts.get(s)))

    def _error(self, exc: BaseException) -> None:
        self._loading = False
        self._msg(f"Falha: {exc}", "err")

    def _msg(self, text: str, style: str) -> None:
        status_text(self.status, text, "banner")
        self.status.setProperty("state", style)
        self.status.style().polish(self.status)
        self.status.show()

    def _selected(self):
        j = self.jobs.get(selected_key(self.table))
        if j is None:
            self._msg("Selecione um trabalho na lista.", "warn")
        return j

    def _do(self, fn, ok: str) -> None:
        j = self._selected()
        if j is None:
            return
        try:
            fn(j.id, actor=current_actor())
        except VyonixError as exc:
            self._msg(str(exc), "err")
            return
        self._msg(ok.format(id=j.id), "ok")
        self.refresh()

    def hold(self) -> None:
        self._do(self.ctx.jobs.hold, "Trabalho #{id} retido.")

    def release(self) -> None:
        self._do(self.ctx.jobs.release, "Trabalho #{id} liberado.")

    def retry(self) -> None:
        self._do(self.ctx.jobs.retry, "Trabalho #{id} voltou para a fila.")

    def reprocess(self) -> None:
        self._do(self.ctx.jobs.reprocess, "Trabalho #{id} será reprocessado com as configurações atuais.")

    def cancel(self) -> None:
        self._do(self.ctx.jobs.cancel, "Trabalho #{id} cancelado.")

    def reprint(self) -> None:
        j = self._selected()
        if j is None:
            return
        choice = choose_printer(self, self.ctx.printers.list(), title=f"Reimprimir o trabalho #{j.id}",
                                default=j.printer or j.settings.get("printer"), ask_copies=True)
        if choice is None:
            return
        printer, copies, _ = choice
        try:
            new = self.ctx.jobs.reprint(j.id, actor=current_actor(), printer=printer, copies=copies)
        except VyonixError as exc:
            self._msg(str(exc), "err")
            return
        self._msg(f"Reimpressão criada: trabalho #{new}.", "ok")
        self.refresh()

    def preview(self) -> None:
        j = self._selected()
        if j is None:
            return
        self._msg(f"Montando a pré-visualização do trabalho #{j.id}…", "muted")

        def show(data) -> None:
            from app.ui.images import to_pixmap
            from app.ui.qt import QScrollArea, Qt
            pages, warnings = data
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Pré-visualização — trabalho #{j.id} (como será impresso)")
            dlg.resize(1000, 860)
            lay = QVBoxLayout(dlg)
            if warnings:
                w = QLabel("Avisos: " + "; ".join(warnings))
                w.setWordWrap(True)
                w.setObjectName("fieldError")
                lay.addWidget(w)
            inner = QWidget()
            il = QVBoxLayout(inner)
            for page in pages:
                lbl = QLabel()
                lbl.setPixmap(to_pixmap(page.pixels, 920, 1300))
                lbl.setAlignment(Qt.AlignCenter)
                lbl.setStyleSheet("border: 1px solid #999; background: white;")
                il.addWidget(lbl)
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setWidget(inner)
            lay.addWidget(sc, 1)
            bb = QDialogButtonBox(QDialogButtonBox.Close)
            bb.rejected.connect(dlg.reject)
            lay.addWidget(bb)
            self.status.hide()
            dlg.exec()
        run_async(lambda: self.ctx.worker.preview(j.id), show, self._error)

    def details(self) -> None:
        j = self._selected()
        if j is None:
            return

        def load():
            return self.ctx.jobs.get_job(j.id), self.ctx.jobs.history(j.id), self.ctx.jobs.items(j.id)
        run_async(load, self._show_details, self._error)

    def _show_details(self, data) -> None:
        job, history, items = data
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Trabalho #{job.id}")
        dlg.resize(900, 560)
        lay = QVBoxLayout(dlg)
        summary = QLabel(
            f"<b>{job.state.label}</b> — {job.state_reason or ''}<br>"
            f"Origem: {job.source_label} · Equipamento: {job.device_name or job.source_ae or '—'} · "
            f"Modalidade: {job.modality or '—'} · Tentativas: {job.attempts}/{job.max_attempts}<br>"
            f"Documento no spooler: {job.document_name or '—'}"
            + (f" (nº {job.spool_job_id})" if job.spool_job_id else "")
            + (f" · situação no spooler: {job.spool_status}" if job.spool_status else "")
            + (f"<br>Arquivo gerado: {job.output_path}" if job.output_path else "")
            + (f"<br>Reimpressão do trabalho #{job.parent_job_id}" if job.parent_job_id else ""))
        summary.setWordWrap(True)
        lay.addWidget(summary)
        tabs = QTabWidget()
        settings = make_table(["Configuração", "Valor aplicado", "Origem"], min_height=200)
        fill_table(settings, [(SETTING_LABELS.get(k, k), _fmt(v), job.origins.get(k, "—"))
                              for k, v in job.settings.items() if k in SETTING_LABELS])
        tabs.addTab(settings, "Configurações aplicadas")
        hist = make_table(["Data/hora", "De", "Para", "Por", "Motivo"], min_height=200)
        fill_table(hist, [(local_time(h["at"]), JobState(h["from_state"]).label if h["from_state"] else "—",
                           JobState(h["to_state"]).label, h["actor"], h["reason"] or "") for h in history])
        tabs.addTab(hist, "Histórico de estados")
        imgs = make_table(["Posição", "Quadro", "Modalidade", "Recebida em", "Disponível"], min_height=200)
        fill_table(imgs, [(it["position"] + 1, it["frame_index"] + 1, it["modality"] or "—",
                           local_time(it["received_at"]), "Sim" if it["file_path"] else "Removida (retenção)")
                          for it in items])
        tabs.addTab(imgs, f"Imagens ({len(items)})")
        lay.addWidget(tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.exec()
