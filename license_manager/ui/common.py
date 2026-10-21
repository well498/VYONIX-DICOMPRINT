"""Componentes comuns da interface do License Manager."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

STYLE = """
QWidget { font-family: "Segoe UI", Arial; font-size: 10pt; color: #1d2433; }
QMainWindow, QDialog { background: #f4f6fa; }
#sidebar { background: #10213f; }
#sidebar QPushButton { color: #e8eefc; background: transparent; border: none; text-align: left; padding: 10px 18px; }
#sidebar QPushButton:checked { background: #1f3b6d; color: white; font-weight: 600; }
#sidebar QLabel#brand { color: white; font-size: 16pt; font-weight: 700; padding: 16px 18px 0 18px; }
#sidebar QLabel#sub { color: #9fb3d9; padding: 0 18px 14px 18px; }
QLabel#title { font-size: 15pt; font-weight: 600; }
QLabel#muted { color: #5b6476; }
QLabel#banner { padding: 8px 12px; border-radius: 6px; background: #e8eefc; }
QLabel#banner[state="err"] { background: #fde2e1; color: #8a1c13; }
QLabel#banner[state="ok"] { background: #def7e5; color: #135c2a; }
QLabel#banner[state="warn"] { background: #fff3cd; color: #6b4e00; }
QPushButton { padding: 6px 12px; border: 1px solid #b8c2d6; border-radius: 5px; background: white; }
QPushButton:hover { background: #eef2fa; }
QPushButton#primary { background: #1f5eff; color: white; border-color: #1f5eff; font-weight: 600; }
QPushButton#danger { color: #a51d12; border-color: #e1a39d; }
QTableWidget { background: white; gridline-color: #e3e7ef; selection-background-color: #cfe0ff;
               selection-color: #10213f; }
QHeaderView::section { background: #e9edf5; padding: 5px; border: none; font-weight: 600; }
QFrame#card { background: white; border: 1px solid #dfe4ee; border-radius: 8px; }
QLabel#kpi { font-size: 22pt; font-weight: 700; color: #1f3b6d; }
"""


def table(headers: Sequence[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(list(headers))
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    t.horizontalHeader().setStretchLastSection(True)
    t.setAlternatingRowColors(True)
    return t


def fill(t: QTableWidget, rows: list[Sequence], keys: list | None = None) -> None:
    t.setRowCount(0)
    for i, row in enumerate(rows):
        t.insertRow(i)
        for j, val in enumerate(row):
            item = QTableWidgetItem("" if val is None else str(val))
            if j == 0 and keys is not None:
                item.setData(Qt.UserRole, keys[i])
            t.setItem(i, j, item)
    t.resizeColumnsToContents()


def selected(t: QTableWidget):
    r = t.currentRow()
    if r < 0 or t.item(r, 0) is None:
        return None
    return t.item(r, 0).data(Qt.UserRole)


def btn(text: str, slot: Callable[[], None], kind: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    b.clicked.connect(lambda _=False: slot())
    return b


def row(*widgets, stretch: bool = True) -> QHBoxLayout:
    lay = QHBoxLayout()
    for w in widgets:
        lay.addWidget(w)
    if stretch:
        lay.addStretch(1)
    return lay


class Page(QWidget):
    def __init__(self, title: str, hint: str = "") -> None:
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(22, 18, 22, 18)
        t = QLabel(title)
        t.setObjectName("title")
        self.lay.addWidget(t)
        if hint:
            h = QLabel(hint)
            h.setObjectName("muted")
            h.setWordWrap(True)
            self.lay.addWidget(h)

    def refresh(self) -> None:  # pragma: no cover - sobrescrito
        pass


def when(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(iso)


def ask_secret(parent, title: str, label: str) -> str | None:
    text, ok = QInputDialog.getText(parent, title, label, QLineEdit.Password)
    return text if ok and text else None


def error(parent, exc: Exception | str, title: str = "VYONIX License Manager") -> None:
    QMessageBox.warning(parent, title, str(exc))


def info(parent, text: str, title: str = "VYONIX License Manager") -> None:
    QMessageBox.information(parent, title, text)


def confirm(parent, text: str, title: str = "Confirmar") -> bool:
    return QMessageBox.question(parent, title, text) == QMessageBox.Yes
