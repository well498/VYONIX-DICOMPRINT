"""Configurações (§13 item 10) — formulário gerado a partir de ``SettingsService.definitions()``."""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import Any

from app.ui.qt import Signal
from app.ui.qt import (QApplication, QCheckBox, QInputDialog, QComboBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from app.core.errors import SettingsValidationError, VyonixError
from app.security.access import AccessDenied, AdminAccess
from app.ui.admin import ensure_admin
from app.services.settings_service import GROUPS, SettingDef, SettingsService, UpdateResult
from app.ui.pages.base import Page, banner
from app.ui.workers import run_async


def current_actor() -> str:
    try:
        return f"ui:{getpass.getuser()}"
    except Exception:  # noqa: BLE001
        return "ui:desconhecido"


class SettingsPage(Page):
    settings_saved = Signal(dict)   # chaves alteradas → novos valores

    def __init__(self, service: SettingsService, exports_dir: Path, access: AdminAccess,
                 parent: QWidget | None = None, ctx=None) -> None:
        super().__init__("Configurações",
                         "Alterações são validadas, registradas no histórico e auditadas. Com senha de "
                         "administrador definida, salvar exige desbloqueio.", parent)
        self.service = service
        self._ctx = ctx
        self.access = access
        self.exports_dir = exports_dir
        self.editors: dict[str, QWidget] = {}
        self.errors: dict[str, QLabel] = {}
        self.loaded: dict[str, Any] = {}

        self.status = banner("")
        self.status.hide()
        self.body.addWidget(self.status)

        by_group: dict[str, list[SettingDef]] = {}
        for d in service.definitions():
            by_group.setdefault(d.group, []).append(d)
        for group_key, group_label in GROUPS:
            defs = by_group.get(group_key)
            if not defs:
                continue
            box = QGroupBox(group_label)
            form = QFormLayout(box)
            form.setHorizontalSpacing(18)
            form.setVerticalSpacing(10)
            for d in defs:
                form.addRow(d.label + ("  ⟳" if d.restart_required else ""), self._field(d))
            self.body.addWidget(box)
            if group_key == "print_identity" and ctx is not None:
                from app.ui.pages.identity_widgets import IdentityBox
                self.identity_box = IdentityBox(ctx)
                self.body.addWidget(self.identity_box)
        if ctx is not None:
            from app.ui.pages.identity_widgets import BackupBox
            self.backup_box = BackupBox(ctx)
            self.body.addWidget(self.backup_box)

        box = QGroupBox("Senha de administrador")
        al = QVBoxLayout(box)
        self.admin_state = QLabel("—")
        self.admin_state.setWordWrap(True)
        al.addWidget(self.admin_state)
        row = QHBoxLayout()
        for text, slot in (("Definir ou alterar senha…", self.set_password),
                           ("Remover senha…", self.clear_password), ("Bloquear agora", self.lock_now)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        al.addLayout(row)
        self.body.addWidget(box)

        note = QLabel("⟳ = o servidor DICOM é reiniciado automaticamente ao salvar.")
        note.setObjectName("muted")
        self.body.addWidget(note)

        buttons = QHBoxLayout()
        self.btn_save = QPushButton("Salvar")
        self.btn_save.setObjectName("primary")
        self.btn_discard = QPushButton("Descartar alterações")
        self.btn_defaults = QPushButton("Restaurar padrões")
        self.btn_export = QPushButton("Exportar…")
        self.btn_import = QPushButton("Importar…")
        for b in (self.btn_save, self.btn_discard, self.btn_defaults):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_export)
        buttons.addWidget(self.btn_import)
        self.body.addLayout(buttons)
        self.body.addStretch(1)

        self.btn_save.clicked.connect(self.save)
        self.btn_discard.clicked.connect(self.reload)
        self.btn_defaults.clicked.connect(self.restore_defaults)
        self.btn_export.clicked.connect(self.export)
        self.btn_import.clicked.connect(self.import_)

    # ------------------------------------------------------------ construção
    def _field(self, d: SettingDef) -> QWidget:
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        if d.kind == "bool":
            editor: QWidget = QCheckBox()
        elif d.kind == "choice":
            editor = QComboBox()
            for value, label in d.choices:
                editor.addItem(label, value)
        elif d.kind == "int":
            editor = QSpinBox()
            editor.setRange(d.minimum if d.minimum is not None else -2**31,
                            d.maximum if d.maximum is not None else 2**31 - 1)
            editor.setMaximumWidth(140)
        else:
            editor = QLineEdit()
            if d.readonly:
                editor.setReadOnly(True)

        if d.readonly and d.kind == "str":
            row = QHBoxLayout()
            row.addWidget(editor, 1)
            copy = QPushButton("Copiar")
            copy.clicked.connect(lambda: QApplication.clipboard().setText(editor.text()))
            row.addWidget(copy)
            lay.addLayout(row)
        else:
            lay.addWidget(editor)

        if d.help:
            h = QLabel(d.help)
            h.setObjectName("muted")
            h.setWordWrap(True)
            lay.addWidget(h)
        err = QLabel("")
        err.setObjectName("fieldError")
        err.setWordWrap(True)
        err.hide()
        lay.addWidget(err)

        self.editors[d.key] = editor
        self.errors[d.key] = err
        return container

    # ------------------------------------------------------------ dados
    def on_shown(self) -> None:
        self.reload()

    def reload(self) -> None:
        run_async(self.service.get_all, self._fill, self._show_failure)
        run_async(self.access.has_password, self._admin_render)

    def _admin_render(self, has: bool) -> None:
        self.admin_state.setText(
            "Senha definida. Configurações, equipamentos e o servidor DICOM exigem desbloqueio."
            if has else "Nenhuma senha definida: qualquer usuário deste computador pode alterar a "
                        "configuração. Recomendado definir uma senha.")

    def _ask(self, title: str, label: str) -> str | None:
        text, ok = QInputDialog.getText(self, title, label, QLineEdit.Password)
        return text if ok else None

    def set_password(self) -> None:
        current = None
        if self.access.has_password():
            current = self._ask("Alterar senha", "Senha atual:")
            if current is None:
                return
        new = self._ask("Nova senha", "Nova senha (mínimo de 8 caracteres):")
        if new is None:
            return
        if self._ask("Nova senha", "Repita a nova senha:") != new:
            self._message("As senhas digitadas não conferem.", "err")
            return
        try:
            self.access.set_password(new, current=current, actor=current_actor())
        except (AccessDenied, VyonixError) as exc:
            self._message(str(exc), "err")
            return
        self._message("Senha de administrador definida.", "ok")
        self._admin_render(True)

    def clear_password(self) -> None:
        if not self.access.has_password():
            self._message("Não há senha definida.", "muted")
            return
        current = self._ask("Remover senha", "Senha atual:")
        if current is None:
            return
        try:
            self.access.clear_password(current=current, actor=current_actor())
        except AccessDenied as exc:
            self._message(str(exc), "err")
            return
        self._message("Senha de administrador removida.", "warn")
        self._admin_render(False)

    def lock_now(self) -> None:
        self.access.lock()
        self._message("Administração bloqueada.", "ok")

    def _fill(self, values: dict[str, Any]) -> None:
        self.loaded = dict(values)
        for key, value in values.items():
            editor = self.editors.get(key)
            if isinstance(editor, QCheckBox):
                editor.setChecked(bool(value))
            elif isinstance(editor, QComboBox):
                idx = editor.findData(value)
                editor.setCurrentIndex(max(idx, 0))
            elif isinstance(editor, QSpinBox):
                editor.setValue(int(value))
            elif isinstance(editor, QLineEdit):
                editor.setText("" if value is None else str(value))
        self._clear_errors()

    def _read(self, key: str) -> Any:
        editor = self.editors[key]
        if isinstance(editor, QCheckBox):
            return editor.isChecked()
        if isinstance(editor, QComboBox):
            return editor.currentData()
        if isinstance(editor, QSpinBox):
            return editor.value()
        return editor.text()

    def pending_changes(self) -> dict[str, Any]:
        changes = {}
        for d in self.service.definitions():
            if d.readonly:
                continue
            value = self._read(d.key)
            if value != self.loaded.get(d.key):
                changes[d.key] = value
        return changes

    # ------------------------------------------------------------ ações
    def save(self) -> None:
        changes = self.pending_changes()
        if not changes:
            self._message("Nenhuma alteração para salvar.", "muted")
            return
        if not ensure_admin(self, self.access, "salvar configurações"):
            return
        # valida antes de pedir a pausa: um valor inválido não deve pausar o sistema
        clean, errors = self.service.validate(changes)
        if errors:
            self._save_failed(SettingsValidationError(errors))
            return
        current = self.service.get_all()
        if not self.ensure_safe_pause({k: v for k, v in clean.items() if current.get(k) != v}):
            return
        self._set_busy(True)
        run_async(lambda: self.service.update(changes, actor=current_actor()),
                  self._saved, self._save_failed)

    def sensitive_changes(self, changes: dict[str, Any]) -> list[str]:
        """Rótulos das alterações que reiniciam a recepção ou a impressão DICOM."""
        return [self.service.definition(k).label for k in changes if self.service.definition(k).restart_required]

    def ensure_safe_pause(self, changes: dict[str, Any], *, answer: bool | None = None) -> bool:
        """Configurações sensíveis exigem o sistema pausado (Prompt Mestre §19): a fila não inicia
        novos trabalhos e o reinício dos servidores espera as transferências em andamento.
        ``answer`` substitui a pergunta (testes)."""
        sensitive = self.sensitive_changes(changes)
        operation = getattr(self._ctx, "operation", None)
        if not sensitive or operation is None or operation.state().paused:
            return True
        if answer is None:
            box = QMessageBox(QMessageBox.Warning, "Pausa segura",
                              "Estas alterações reiniciam os servidores DICOM:\n\n• " + "\n• ".join(sensitive) +
                              "\n\nPara não interromper impressões, o sistema será pausado antes de salvar: a "
                              "fila conclui o trabalho em andamento e não inicia outro, e o reinício espera as "
                              "transferências em curso terminarem.\n\nDepois de conferir, use "
                              "\u201cRetomar sistema\u201d no topo da janela.", parent=self)
            go = box.addButton("Pausar e salvar", QMessageBox.AcceptRole)
            box.addButton("Cancelar", QMessageBox.RejectRole)
            box.exec()
            answer = box.clickedButton() is go
        if not answer:
            return False
        operation.pause(actor=current_actor(), reason="Alteração de configuração sensível: " +
                        ", ".join(sensitive)[:150])
        return True

    def restore_defaults(self) -> None:
        if not ensure_admin(self, self.access, "restaurar padrões"):
            return
        if QMessageBox.question(self, "Restaurar padrões",
                                "Restaurar todas as configurações para os valores padrão?"
                                ) != QMessageBox.Yes:
            return
        self._set_busy(True)
        run_async(lambda: self.service.reset_to_defaults(actor=current_actor()),
                  self._saved, self._save_failed)

    def export(self) -> None:
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar configurações", str(self.exports_dir / "vyonix-configuracoes.json"),
            "JSON (*.json)")
        if not path:
            return
        run_async(lambda: self.service.export_json(Path(path)),
                  lambda p: self._message(f"Configurações exportadas para {p}.", "ok"),
                  self._show_failure)

    def import_(self) -> None:
        if not ensure_admin(self, self.access, "importar configurações"):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Importar configurações",
                                              str(self.exports_dir), "JSON (*.json)")
        if not path:
            return
        self._set_busy(True)
        run_async(lambda: self.service.import_json(Path(path), actor=current_actor()),
                  self._saved, self._save_failed)

    # ------------------------------------------------------------ retorno
    def _saved(self, result: UpdateResult) -> None:
        self._set_busy(False)
        self._clear_errors()
        if not result.changed:
            self._message("Nenhuma alteração efetiva.", "muted")
        else:
            parts = [f"{len(result.changed)} configuração(ões) salva(s)."]
            if result.restart_required:
                parts.append("O servidor DICOM foi reiniciado com a nova configuração.")
            parts += result.warnings
            self._message(" ".join(parts), "warn" if result.warnings else "ok")
            self.settings_saved.emit({k: new for k, (_, new) in result.changed.items()})
        self.reload()

    def _save_failed(self, exc: BaseException) -> None:
        self._set_busy(False)
        self._clear_errors()
        if isinstance(exc, SettingsValidationError):
            general = []
            for key, msg in exc.errors.items():
                if key in self.errors:
                    self.errors[key].setText(msg)
                    self.errors[key].show()
                    self.editors[key].setProperty("invalid", True)
                    self.editors[key].style().polish(self.editors[key])
                else:
                    general.append(msg)
            self._message("Corrija os campos indicados. " + " ".join(general), "err")
        else:
            self._show_failure(exc)

    def _show_failure(self, exc: BaseException) -> None:
        self._set_busy(False)
        self._message(f"Falha: {exc}", "err")

    def _clear_errors(self) -> None:
        for key, lbl in self.errors.items():
            lbl.hide()
            self.editors[key].setProperty("invalid", False)
            self.editors[key].style().polish(self.editors[key])

    def _message(self, text: str, style: str) -> None:
        self.status.setText(text)
        self.status.setProperty("state", style)
        self.status.style().polish(self.status)
        self.status.show()

    def _set_busy(self, busy: bool) -> None:
        for b in (self.btn_save, self.btn_discard, self.btn_defaults, self.btn_import):
            b.setEnabled(not busy)
