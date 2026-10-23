"""Barra de operação no cabeçalho: Pausar/Retomar sistema e Abrir log (Prompt Mestre §19)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.core.errors import ValidationError
from app.ui.admin import current_actor, ensure_admin
from app.ui.qt import (QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QTimer, QtCore,
                       QtGui, QWidget)
from app.utils.logging_setup import get_logger
from app.utils.timeutil import from_iso

log = get_logger("ui.operation")
REFRESH_MS = 5000


def open_folder(path: Path) -> bool:
    """Abre a pasta no Explorador (ou no gerenciador de arquivos do sistema)."""
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32" and hasattr(os, "startfile"):
        os.startfile(str(path))  # noqa: S606 - abre o Explorer na pasta de logs
        return True
    return bool(QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path))))


class OperationBar(QWidget):
    """Mostra se o sistema está pausado e permite pausar/retomar com segurança.

    O estado vem do banco (``ctx.operation``), então uma pausa feita em outra janela ou no
    serviço aparece aqui em até ``REFRESH_MS``.
    """

    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.badge = QLabel("SISTEMA PAUSADO")
        self.badge.setObjectName("pauseBadge")
        self.badge.hide()
        self.toggle = QPushButton("Pausar sistema")
        self.toggle.clicked.connect(self._toggle_clicked)
        self.log_button = QPushButton("Abrir log")
        self.log_button.setToolTip("Abre a pasta com o log operacional (arquivos de texto).")
        self.log_button.clicked.connect(self.open_log)
        for w in (self.badge, self.toggle, self.log_button):
            lay.addWidget(w)
        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    # ------------------------------------------------------------------ estado
    @property
    def available(self) -> bool:
        return getattr(self.ctx, "operation", None) is not None

    def refresh(self) -> None:
        if not self.available:
            self.toggle.setEnabled(False)
            return
        try:
            st = self.ctx.operation.state()
        except Exception:  # noqa: BLE001 - banco ocupado: tenta de novo no próximo ciclo
            log.exception("Falha ao ler o estado da operação")
            return
        self.badge.setVisible(st.paused)
        self.toggle.setText("Retomar sistema" if st.paused else "Pausar sistema")
        self.toggle.setObjectName("primary" if st.paused else "")
        self.toggle.style().unpolish(self.toggle)
        self.toggle.style().polish(self.toggle)
        if st.paused:
            since = from_iso(st.since).astimezone().strftime("%d/%m/%Y %H:%M") if st.since else "?"
            self.badge.setToolTip(f"Pausado por {st.actor} em {since}.\nMotivo: {st.reason}\n"
                                  "A recepção DICOM continua; os trabalhos aguardam na fila.")
        else:
            self.badge.setToolTip("")

    def _toggle_clicked(self) -> None:
        if self.available and self.ctx.operation.state().paused:
            self.resume_system()
        else:
            self.pause_system()

    # ------------------------------------------------------------------ ações
    def pause_system(self, reason: str | None = None, *, ask_admin: bool = True) -> bool:
        if not self.available:
            return False
        if reason is None:
            reason, ok = QInputDialog.getText(
                self, "Pausar sistema",
                "A recepção DICOM continua recebendo imagens. O trabalho em impressão é concluído e os\n"
                "demais aguardam na fila até “Retomar sistema”.\n\nMotivo da pausa:", QLineEdit.Normal, "")
            if not ok:
                return False
        if ask_admin and not ensure_admin(self, self.ctx.access, "pausar o sistema"):
            return False
        try:
            self.ctx.operation.pause(actor=current_actor(), reason=reason)
        except ValidationError as exc:
            QMessageBox.warning(self, "Pausar sistema", str(exc))
            return False
        self.refresh()
        return True

    def resume_system(self, *, confirm: bool = True, ask_admin: bool = True) -> bool:
        if not self.available:
            return False
        if confirm and QMessageBox.question(
                self, "Retomar sistema", "Retomar o processamento da fila de impressão?") != QMessageBox.Yes:
            return False
        if ask_admin and not ensure_admin(self, self.ctx.access, "retomar o sistema"):
            return False
        self.ctx.operation.resume(actor=current_actor())
        wake = getattr(self.ctx.runtime, "wake_queue", None)
        if callable(wake):
            wake()
        self.refresh()
        return True

    def log_folder(self) -> Path:
        """Com o serviço Windows ativo, o log que importa é o do serviço; senão, o desta janela."""
        if getattr(self.ctx.runtime, "remote", False):
            return self.ctx.paths.service_logs_dir
        return Path(self.ctx.log_file).parent

    def open_log(self) -> None:
        folder = self.log_folder()
        try:
            if not open_folder(folder):
                QMessageBox.information(self, "Abrir log", f"Os logs estão em:\n{folder}")
        except OSError as exc:
            QMessageBox.warning(self, "Abrir log", f"Não foi possível abrir {folder}: {exc}")
