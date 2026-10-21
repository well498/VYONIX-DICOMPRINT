"""Desbloqueio administrativo na interface."""

from __future__ import annotations

import getpass

from app.security.access import AccessDenied, AdminAccess
from app.ui.qt import QInputDialog, QLineEdit, QMessageBox, QWidget


def current_actor() -> str:
    try:
        return f"ui:{getpass.getuser()}"
    except Exception:  # noqa: BLE001
        return "ui:desconhecido"


def ensure_admin(parent: QWidget, access: AdminAccess, action: str) -> bool:
    """Garante o desbloqueio antes de uma ação protegida. Retorna False se o usuário desistir."""
    if access.is_unlocked():
        access.touch()
        return True
    while True:
        password, ok = QInputDialog.getText(
            parent, "Senha de administrador",
            f"A ação \"{action}\" exige a senha de administrador\n(ou usuário:senha de um Administrador ou "
            "Técnico):", QLineEdit.Password)
        if not ok:
            return False
        try:
            if access.unlock(password, actor=current_actor()):
                return True
        except AccessDenied as exc:
            QMessageBox.warning(parent, "Acesso bloqueado", str(exc))
            return False
        QMessageBox.warning(parent, "Senha incorreta", "Senha de administrador incorreta.")
