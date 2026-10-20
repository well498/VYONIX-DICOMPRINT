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
_pyside2_error: ImportError | None = None
if _forced != "pyside6":
    try:
        from PySide2 import QtCore, QtGui, QtSvg, QtWidgets  # noqa: F401
        QT_API = "PySide2"
    except ImportError as exc:
        _pyside2_error = exc
        if _forced == "pyside2" or getattr(sys, "frozen", False):
            # O executável oficial contém só o PySide2: o erro real precisa aparecer.
            raise
if not QT_API:
    try:
        from PySide6 import QtCore, QtGui, QtSvg, QtWidgets  # noqa: F401,F811
    except ImportError as exc:
        raise ImportError(f"Nenhuma ligação Qt disponível. PySide2: {_pyside2_error}; "
                          f"PySide6: {exc}") from exc
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


# Textos padrão do Qt (botões e diálogos) para quando o arquivo .qm não existe. O Qt 5.15 não
# distribui qtbase_pt_BR.qm; o Qt 6 distribui. Os diálogos de arquivo nativos do Windows já vêm
# no idioma do sistema e não passam por aqui.
_PT_BR = {
    "&Yes": "&Sim", "Yes": "Sim", "&No": "&Não", "No": "Não", "Yes to &All": "Sim para &todos",
    "N&o to All": "Nã&o para todos", "OK": "OK", "&OK": "&OK", "Cancel": "Cancelar",
    "&Cancel": "&Cancelar", "Close": "Fechar", "&Close": "&Fechar", "Apply": "Aplicar",
    "&Apply": "&Aplicar", "Reset": "Redefinir", "&Reset": "&Redefinir", "Help": "Ajuda",
    "&Help": "&Ajuda", "Save": "Salvar", "&Save": "&Salvar", "Save All": "Salvar tudo",
    "Open": "Abrir", "&Open": "&Abrir", "Discard": "Descartar", "Don't Save": "Não salvar",
    "Abort": "Abortar", "Retry": "Tentar novamente", "Ignore": "Ignorar",
    "Restore Defaults": "Restaurar padrões", "Show Details...": "Mostrar detalhes...",
    "Hide Details...": "Ocultar detalhes...", "&Undo": "&Desfazer", "&Redo": "&Refazer",
    "Cu&t": "Recor&tar", "&Copy": "&Copiar", "&Paste": "C&olar", "Delete": "Excluir",
    "Select All": "Selecionar tudo", "Copy &Link Location": "Copiar &endereço do link",
    "Look in:": "Examinar:", "File &name:": "&Nome do arquivo:", "Files of type:": "Arquivos do tipo:",
}


class _FallbackTranslator(QtCore.QTranslator):
    def translate(self, context, source, disambiguation=None, n=-1):  # noqa: D401 - API Qt
        return _PT_BR.get(source, "")

    def isEmpty(self) -> bool:  # noqa: N802 - API Qt
        return False


def install_translations(app, locale: str = "pt_BR") -> str | None:
    """Traduz os textos padrão do Qt (Sim/Não, Cancelar…) e define pt-BR para datas e números.

    Retorna a pasta do arquivo .qm usado ou ``"interno"`` quando a tabela embutida é usada.
    """
    QtCore.QLocale.setDefault(QtCore.QLocale(QtCore.QLocale.Portuguese, QtCore.QLocale.Brazil))
    keep = getattr(app, "_vyonix_translators", [])
    for folder in _translation_dirs():
        translator = QtCore.QTranslator(app)
        if translator.load(f"qtbase_{locale}", str(folder)):
            app.installTranslator(translator)
            app._vyonix_translators = keep + [translator]
            return str(folder)
    translator = _FallbackTranslator(app)
    app.installTranslator(translator)
    app._vyonix_translators = keep + [translator]
    return "interno"
