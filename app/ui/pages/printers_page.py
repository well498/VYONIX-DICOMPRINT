"""Impressoras (§8): impressoras do Windows e a impressora virtual VYONIX PDF."""

from __future__ import annotations

from app.core.errors import VyonixError
from app.printing.backends.pdf import PDF_PRINTER
from app.ui.admin import current_actor, ensure_admin
from app.ui.pages.base import Page, banner
from app.ui.qt import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QSpinBox, QWidget
from app.ui.widgets import button, button_row, fill_table, local_time, make_table, selected_key, status_text
from app.ui.workers import run_async

PAPER_CHOICES = (("A4", "A4"), ("A3", "A3"), ("Letter", "Carta"), ("Legal", "Ofício"), ("A5", "A5"),
                 ("Tabloid", "Tabloide"))


def choose_printer(parent: QWidget, printers, *, title: str = "Imprimir", default: str | None = None,
                   ask_copies: bool = False, ask_paper: bool = False):
    """Diálogo simples de escolha de impressora (e, opcionalmente, cópias e papel).

    Retorna ``(nome, cópias, papel)`` ou ``None`` se o usuário cancelar.
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    form = QFormLayout(dlg)
    combo = QComboBox()
    for p in printers:
        if p.available:
            combo.addItem(p.name + ("  (padrão do VYONIX)" if p.is_vyonix_default else ""), p.name)
    combo.setCurrentIndex(max(combo.findData(default), 0) if default else 0)
    form.addRow("Impressora", combo)
    copies = QSpinBox()
    copies.setRange(1, 99)
    if ask_copies:
        form.addRow("Cópias", copies)
    paper = QComboBox()
    for value, label in PAPER_CHOICES:
        paper.addItem(label, value)
    if ask_paper:
        form.addRow("Papel", paper)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    form.addRow(bb)
    if combo.count() == 0:
        form.insertRow(0, QLabel("Nenhuma impressora disponível."))
    if not dlg.exec() or combo.currentData() is None:
        return None
    return combo.currentData(), copies.value(), paper.currentData()


class PrintersPage(Page):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__("Impressoras",
                         "Impressoras instaladas no Windows e a impressora virtual “VYONIX PDF”, que grava "
                         "cada trabalho como arquivo PDF em tamanho real. “Enviado” significa aceito "
                         "pelo spooler do Windows; só aparece “Concluído” quando o driver confirma.", parent)
        self.ctx = ctx
        self.status = banner("")
        self.status.hide()
        self.body.addWidget(self.status)
        self.backend_note = banner("")
        self.backend_note.hide()
        self.body.addWidget(self.backend_note)
        self.body.addLayout(button_row(
            button("Atualizar lista", self.refresh, primary=True),
            button("Definir como padrão do VYONIX", self.set_default),
            button("Imprimir página de teste", self.test_page)))
        self.table = make_table(["Impressora", "Tipo", "Driver", "Porta", "Padrão", "Papéis", "Resoluções (dpi)",
                                 "Cor", "Situação", "Visto em"])
        self.table.itemSelectionChanged.connect(self._show_detail)
        self.body.addWidget(self.table, 1)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setObjectName("muted")
        self.body.addWidget(self.detail)
        self.records = {}

    def on_shown(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        run_async(self.ctx.printers.refresh, self._render, self._error)

    def _render(self, printers) -> None:
        self.records = {p.name: p for p in printers}
        rows = []
        for p in printers:
            default = " / ".join(x for x, ok in (("Windows", p.is_default), ("VYONIX", p.is_vyonix_default)) if ok)
            papers = ", ".join(p.paper_sizes[:4]) + (f" (+{len(p.paper_sizes) - 4})" if len(p.paper_sizes) > 4 else "")
            rows.append((p.name, "Arquivo PDF" if p.backend == "pdf" else "Windows", p.driver, p.port, default or "—",
                         papers or "—", ", ".join(map(str, p.resolutions)) or "—",
                         {True: "Sim", False: "Não"}.get(p.color, "—"), p.status or "—", local_time(p.last_seen_at)))
        fill_table(self.table, rows, [p.name for p in printers])
        errors = self.ctx.printers.backend_errors
        if errors.get("windows"):
            status_text(self.backend_note, "Impressoras do Windows indisponíveis: " + errors["windows"], "banner")
            self.backend_note.show()
        else:
            self.backend_note.hide()
        if not any(p.is_vyonix_default for p in printers) and not any(p.is_default for p in printers):
            self._msg("Nenhuma impressora padrão definida: os trabalhos vão falhar até que uma seja escolhida.",
                      "warn")

    def _show_detail(self) -> None:
        p = self.records.get(selected_key(self.table))
        if p is None:
            self.detail.setText("")
            return
        self.detail.setText(f"<b>{p.name}</b> — formatos aceitos pelo driver: "
                            f"{', '.join(p.paper_sizes) or 'não informados'}.")

    def _selected(self):
        p = self.records.get(selected_key(self.table))
        if p is None:
            self._msg("Selecione uma impressora na lista.", "warn")
        return p

    def _msg(self, text: str, style: str) -> None:
        status_text(self.status, text, "banner")
        self.status.setProperty("state", style)
        self.status.style().polish(self.status)
        self.status.show()

    def _error(self, exc: BaseException) -> None:
        self._msg(f"Falha: {exc}", "err")

    def set_default(self) -> None:
        p = self._selected()
        if p is None or not ensure_admin(self, self.ctx.access, "definir a impressora padrão"):
            return
        try:
            self.ctx.printers.set_vyonix_default(p.name, self.ctx.settings, actor=current_actor())
        except VyonixError as exc:
            self._msg(str(exc), "err")
            return
        self._msg(f"“{p.name}” é agora a impressora padrão do VYONIX.", "ok")
        self.refresh()

    def test_page(self) -> None:
        p = self.records.get(selected_key(self.table))
        choice = choose_printer(self, [x for x in self.records.values()], title="Página de teste",
                                default=p.name if p else None, ask_paper=True)
        if choice is None:
            return
        name, _copies, paper = choice
        try:
            jid = self.ctx.jobs.test_page(printer=name, actor=current_actor(), overrides={"paper": paper})
        except VyonixError as exc:
            self._msg(str(exc), "err")
            return
        where = f" O arquivo será gravado em {self.ctx.paths.output_dir / 'pdf'}." if name == PDF_PRINTER else ""
        self._msg(f"Página de teste enviada à fila (trabalho #{jid}). Acompanhe em Trabalhos de impressão.{where}",
                  "ok")
