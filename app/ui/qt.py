"""Ponto único de importação do Qt.

Distribuição oficial: **PySide2 (Qt 5.15) + Python 3.8**, a última combinação que roda no
Windows 7 SP1 64 bits — requisito mínimo do produto. Em ambientes de desenvolvimento com
Python ≥ 3.11 (onde o PySide2 não existe), o PySide6 é usado automaticamente; as telas são as
mesmas. ``VYONIX_QT=pyside2`` ou ``VYONIX_QT=pyside6`` força uma das ligações.

Os imports são literais (e não dinâmicos) para que o PyInstaller detecte a ligação usada.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_forced = os.environ.get("VYONIX_QT", "").lower()

QT_API = ""
if _forced != "pyside6":
    try:
        from PySide2 import QtCore, QtGui, QtSvg, QtWidgets  # noqa: F401
        QT_API = "PySide2"
    except ImportError:
        if _forced == "pyside2":
            raise
if not QT_API:
    from PySide6 import QtCore, QtGui, QtSvg, QtWidgets  # noqa: F401,F811
    QT_API = "PySide6"

QT_VERSION = QtCore.qVersion()
IS_QT5 = QT_VERSION.startswith("5.")

# Nomes usados pelas telas.
Qt = QtCore.Qt
Signal = QtCore.Signal
QObject, QRunnable, QThreadPool = QtCore.QObject, QtCore.QRunnable, QtCore.QThreadPool
QTimer, QSize, QDate, QLockFile = QtCore.QTimer, QtCore.QSize, QtCore.QDate, QtCore.QLockFile
QRectF, QByteArray, QBuffer, QIODevice = QtCore.QRectF, QtCore.QByteArray, QtCore.QBuffer, QtCore.QIODevice
QIcon, QPixmap, QImage, QPainter, QColor, QFont = (QtGui.QIcon, QtGui.QPixmap, QtGui.QImage,
                                                   QtGui.QPainter, QtGui.QColor, QtGui.QFont)
QGuiApplication = QtGui.QGuiApplication
QSvgRenderer = QtSvg.QSvgRenderer
_W = QtWidgets
(QApplication, QWidget, QMainWindow, QLabel, QPushButton, QLineEdit, QSpinBox, QCheckBox,
 QComboBox, QDateEdit, QFileDialog, QMessageBox, QFormLayout, QGridLayout, QHBoxLayout,
 QVBoxLayout, QGroupBox, QFrame, QScrollArea, QSizePolicy, QListWidget, QListWidgetItem,
 QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
 QAbstractItemView) = (
    _W.QApplication, _W.QWidget, _W.QMainWindow, _W.QLabel, _W.QPushButton, _W.QLineEdit,
    _W.QSpinBox, _W.QCheckBox, _W.QComboBox, _W.QDateEdit, _W.QFileDialog, _W.QMessageBox,
    _W.QFormLayout, _W.QGridLayout, _W.QHBoxLayout, _W.QVBoxLayout, _W.QGroupBox, _W.QFrame,
    _W.QScrollArea, _W.QSizePolicy, _W.QListWidget, _W.QListWidgetItem, _W.QStackedWidget,
    _W.QTabWidget, _W.QTableWidget, _W.QTableWidgetItem, _W.QHeaderView, _W.QAbstractItemView)


def prepare_application() -> None:
    """Configurações que precisam ser feitas antes de criar o QApplication."""
    if IS_QT5:  # no Qt 6 a escala em telas de alta densidade já é padrão
        QtCore.QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QtCore.QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def exec_app(app) -> int:
    run = getattr(app, "exec", None) or getattr(app, "exec_")
    return int(run())


def _translation_dirs() -> list[Path]:
    dirs: list[Path] = []
    try:
        if IS_QT5:
            dirs.append(Path(QtCore.QLibraryInfo.location(QtCore.QLibraryInfo.TranslationsPath)))
        else:
            dirs.append(Path(QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.LibraryPath.TranslationsPath)))
    except Exception:  # noqa: BLE001
        pass
    package = Path(QtCore.__file__).resolve().parent
    dirs.append(package / "translations")
    dirs.append(package / "Qt" / "translations")
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        dirs += [Path(bundle) / QT_API / "translations", Path(bundle) / QT_API / "Qt" / "translations"]
    return dirs


def install_translations(app, locale: str = "pt_BR") -> str | None:
    """Traduz os textos padrão do Qt (Sim/Não, Cancelar, diálogos de arquivo). Retorna a pasta usada."""
    for folder in _translation_dirs():
        translator = QtCore.QTranslator(app)
        if translator.load(f"qtbase_{locale}", str(folder)):
            app.installTranslator(translator)
            app._vyonix_translators = getattr(app, "_vyonix_translators", []) + [translator]
            return str(folder)
    return None
