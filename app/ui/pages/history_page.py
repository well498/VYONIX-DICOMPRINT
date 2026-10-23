"""Histórico (§18): eventos com filtros e exportação; alterações administrativas."""

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

from app.ui.responsive import FlowLayout
from app.ui.qt import QDate, Qt
from app.ui.qt import (QAbstractItemView, QComboBox, QDateEdit, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from app.database.repositories.events_repo import Category, EventFilter, EventRepository
from app.database.repositories.settings_repo import ChangeHistoryRepository
from app.ui.pages.base import Page
from app.ui.workers import run_async
from app.utils.timeutil import from_iso

PAGE_LIMIT = 500


def _local(ts: str) -> str:
    return from_iso(ts).astimezone().strftime("%d/%m/%Y %H:%M:%S")


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    t.setMinimumHeight(380)
    return t


class HistoryPage(Page):
    def __init__(self, events: EventRepository, changes: ChangeHistoryRepository,
                 exports_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__("Histórico",
                         "Eventos operacionais e de auditoria. Horários exibidos no fuso local; "
                         "armazenados em UTC. Dados de paciente são redigidos.", parent)
        self.events = events
        self.changes = changes
        self.exports_dir = exports_dir

        tabs = QTabWidget()
        self.body.addWidget(tabs)

        # --- Eventos -------------------------------------------------------
        ev = QWidget()
        ev_lay = QVBoxLayout(ev)
        filters = FlowLayout()
        today = QDate.currentDate()
        self.start = QDateEdit(today.addDays(-7))
        self.end = QDateEdit(today)
        for d in (self.start, self.end):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd/MM/yyyy")
        self.category = QComboBox()
        self.category.addItem("Todas as categorias", None)
        for key in Category.ALL:
            self.category.addItem(Category.LABELS[key], key)
        self.level = QComboBox()
        for label, value in (("Todos os níveis", None), ("Informação ou superior", "INFO"),
                             ("Alerta ou superior", "WARNING"), ("Erro ou superior", "ERROR")):
            self.level.addItem(label, value)
        self.text = QLineEdit()
        self.text.setPlaceholderText("Buscar texto…")
        btn_apply = QPushButton("Filtrar")
        btn_apply.setObjectName("primary")
        btn_export = QPushButton("Exportar CSV…")
        for w in (QLabel("De"), self.start, QLabel("até"), self.end, self.category, self.level):
            filters.addWidget(w)
        self.text.setMinimumWidth(220)
        filters.addWidget(self.text)
        filters.addWidget(btn_apply)
        filters.addWidget(btn_export)
        ev_lay.addLayout(filters)

        self.ev_table = _table(["Data/hora", "Nível", "Categoria", "Ação", "Mensagem", "Usuário"])
        ev_lay.addWidget(self.ev_table)
        self.ev_info = QLabel("")
        self.ev_info.setObjectName("muted")
        ev_lay.addWidget(self.ev_info)
        tabs.addTab(ev, "Eventos")

        # --- Alterações ----------------------------------------------------
        ch = QWidget()
        ch_lay = QVBoxLayout(ch)
        self.ch_table = _table(["Data/hora", "Entidade", "Item", "Valor anterior", "Novo valor",
                                "Usuário", "Motivo"])
        ch_lay.addWidget(self.ch_table)
        tabs.addTab(ch, "Alterações administrativas")

        btn_apply.clicked.connect(self.refresh)
        self.text.returnPressed.connect(self.refresh)
        btn_export.clicked.connect(self.export)

    # ------------------------------------------------------------------
    def current_filter(self, limit: int = PAGE_LIMIT) -> EventFilter:
        start = datetime.combine(self.start.date().toPython(), time.min).astimezone()
        end = datetime.combine(self.end.date().toPython(), time.max).astimezone()
        cat = self.category.currentData()
        return EventFilter(start=start, end=end, categories=(cat,) if cat else (),
                           min_level=self.level.currentData(),
                           text=self.text.text().strip() or None, limit=limit)

    def on_shown(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        flt = self.current_filter()
        run_async(lambda: (self.events.query(flt), self.events.count(flt),
                           self.changes.list(limit=PAGE_LIMIT)),
                  self._render, lambda exc: self.ev_info.setText(f"Falha: {exc}"))

    def _render(self, data) -> None:
        events, total, changes = data
        self._fill(self.ev_table, [
            (_local(e.ts), e.level, Category.LABELS.get(e.category, e.category), e.action,
             e.message, e.actor or "") for e in events])
        shown = len(events)
        self.ev_info.setText(f"Exibindo {shown} de {total} evento(s)." +
                             (" Refine os filtros ou exporte para ver todos." if total > shown else ""))
        self._fill(self.ch_table, [
            (_local(c.changed_at), c.entity_type, c.entity_id, c.old_value or "",
             c.new_value or "", c.changed_by, c.reason or "") for c in changes])

    @staticmethod
    def _fill(table: QTableWidget, rows: list[tuple]) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(r, c, item)

    def export(self) -> None:
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar eventos", str(self.exports_dir / f"vyonix-eventos-{stamp}.csv"),
            "CSV (*.csv)")
        if not path:
            return
        flt = self.current_filter(limit=1_000_000)
        run_async(lambda: self.events.export_csv(Path(path), flt),
                  lambda n: self.ev_info.setText(f"{n} evento(s) exportado(s) para {path}."),
                  lambda exc: self.ev_info.setText(f"Falha na exportação: {exc}"))
