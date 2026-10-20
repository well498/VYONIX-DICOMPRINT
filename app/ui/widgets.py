"""Componentes reutilizáveis da interface."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from app.ui.qt import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton, Qt,
                       QTableWidget, QTableWidgetItem, QWidget)
from app.utils.timeutil import from_iso


def local_time(ts: str | None) -> str:
    if not ts:
        return "—"
    return from_iso(ts).astimezone().strftime("%d/%m/%Y %H:%M:%S")


def make_table(headers: Sequence[str], *, min_height: int = 320) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(list(headers))
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    t.setMinimumHeight(min_height)
    return t


def fill_table(table: QTableWidget, rows: Sequence[Sequence[Any]], keys: Sequence[Any] | None = None) -> None:
    """Preenche a tabela; ``keys`` (ex.: ids) ficam em Qt.UserRole na primeira coluna."""
    selected = selected_key(table)
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = QTableWidgetItem("" if value is None else str(value))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            if c == 0 and keys is not None:
                item.setData(Qt.UserRole, keys[r])
            table.setItem(r, c, item)
    if selected is not None and keys is not None and selected in keys:
        table.selectRow(list(keys).index(selected))


def selected_key(table: QTableWidget) -> Any:
    rows = table.selectionModel().selectedRows() if table.selectionModel() else []
    if not rows:
        return None
    item = table.item(rows[0].row(), 0)
    return item.data(Qt.UserRole) if item else None


def button_row(*buttons: QPushButton, stretch_at: int | None = None) -> QHBoxLayout:
    lay = QHBoxLayout()
    for i, b in enumerate(buttons):
        if stretch_at is not None and i == stretch_at:
            lay.addStretch(1)
        lay.addWidget(b)
    if stretch_at is None:
        lay.addStretch(1)
    return lay


def button(text: str, slot: Callable[[], None] | None = None, *, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setObjectName("primary")
    if slot is not None:
        b.clicked.connect(lambda _=False: slot())
    return b


def status_text(label: QLabel, text: str, style: str) -> None:
    """style: ok | warn | err | muted"""
    label.setText(text)
    label.setObjectName(style)
    label.style().unpolish(label)
    label.style().polish(label)


__all__ = ["QWidget"]
