"""Equipamentos DICOM (§5): cadastro, autorização, teste de conectividade e histórico."""

from __future__ import annotations

from pathlib import Path

from app.core.errors import SettingsValidationError, VyonixError
from app.devices.service import MODALITIES, DeviceService
from app.security.access import AdminAccess
from app.ui.admin import current_actor, ensure_admin
from app.ui.pages.base import Page, banner
from app.ui.qt import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                       QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QSpinBox, QVBoxLayout,
                       QWidget)
from app.ui.widgets import (button, button_row, fill_table, local_time, make_table, selected_key,
                            status_text)
from app.ui.workers import run_async

FIELDS = [
    ("name", "Nome *"), ("ae_title", "AE Title *"), ("modality", "Modalidade"),
    ("manufacturer", "Fabricante"), ("model", "Modelo"), ("ip_address", "Endereço IP"),
    ("port", "Porta (para teste C-ECHO)"), ("site", "Unidade ou clínica"), ("department", "Setor"),
    ("printer_id", "Impressora associada"), ("print_profile_id", "Perfil de impressão"),
    ("notes", "Observações"),
]


class DeviceDialog(QDialog):
    def __init__(self, parent: QWidget, service: DeviceService, device=None, ctx=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.service = service
        self.device = device
        self.result_device = None
        self.setWindowTitle("Editar equipamento" if device else "Novo equipamento")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.editors: dict[str, QWidget] = {}
        self.errors: dict[str, QLabel] = {}
        for key, label in FIELDS:
            if key == "modality":
                w = QComboBox()
                w.addItem("—", None)
                for code, name in MODALITIES:
                    w.addItem(f"{code} — {name}", code)
            elif key in ("printer_id", "print_profile_id"):
                w = QComboBox()
                w.addItem("— nenhum —", None)
                try:
                    if key == "printer_id" and ctx is not None:
                        for pr in ctx.printers.list():
                            w.addItem(pr.name, pr.id)
                    elif ctx is not None:
                        for pf in ctx.profiles.list():
                            w.addItem(pf.name, pf.id)
                except Exception:  # noqa: BLE001
                    pass
            elif key == "port":
                w = QSpinBox()
                w.setRange(0, 65535)
                w.setSpecialValueText("—")
            elif key == "notes":
                w = QPlainTextEdit()
                w.setFixedHeight(70)
            else:
                w = QLineEdit()
            err = QLabel("")
            err.setObjectName("fieldError")
            err.hide()
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.addWidget(w)
            bl.addWidget(err)
            form.addRow(label, box)
            self.editors[key], self.errors[key] = w, err
        self.authorized = QCheckBox("Autorizado a enviar imagens")
        if device is None:
            form.addRow("", self.authorized)
        lay.addLayout(form)
        hint = QLabel("Com IP cadastrado, o VYONIX só aceita conexões desse equipamento vindas desse IP.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        if device:
            self._fill(device)

    def _fill(self, d) -> None:
        for key, w in self.editors.items():
            value = getattr(d, key)
            if isinstance(w, QComboBox):
                w.setCurrentIndex(max(w.findData(value), 0))
            elif isinstance(w, QSpinBox):
                w.setValue(int(value or 0))
            elif isinstance(w, QPlainTextEdit):
                w.setPlainText(value or "")
            else:
                w.setText(value or "")

    def values(self) -> dict:
        out = {}
        for key, w in self.editors.items():
            if isinstance(w, QComboBox):
                out[key] = w.currentData()
            elif isinstance(w, QSpinBox):
                out[key] = w.value() or None
            elif isinstance(w, QPlainTextEdit):
                out[key] = w.toPlainText()
            else:
                out[key] = w.text()
        return out

    def _save(self) -> None:
        for e in self.errors.values():
            e.hide()
        try:
            if self.device:
                self.result_device = self.service.update(self.device.id, self.values(), actor=current_actor())
            else:
                self.result_device = self.service.create(self.values(), actor=current_actor(),
                                                         authorized=self.authorized.isChecked())
        except SettingsValidationError as exc:
            for key, msg in exc.errors.items():
                if key in self.errors:
                    self.errors[key].setText(msg)
                    self.errors[key].show()
            return
        self.accept()


class DevicesPage(Page):
    def __init__(self, service: DeviceService, access: AdminAccess, exports_dir: Path,
                 parent: QWidget | None = None, ctx=None) -> None:
        super().__init__("Equipamentos DICOM",
                         "Somente equipamentos ativos e autorizados podem enviar imagens, salvo se a "
                         "opção \"aceitar equipamentos não cadastrados\" estiver ligada em Configurações.",
                         parent)
        self.service, self.access, self.exports_dir = service, access, exports_dir
        self.ctx = ctx
        self.status = banner("")
        self.status.hide()
        self.body.addWidget(self.status)
        self.show_inactive = QCheckBox("Mostrar desativados")
        self.show_inactive.toggled.connect(lambda _: self.refresh())
        self.body.addLayout(button_row(
            button("Adicionar", self.add, primary=True), button("Editar", self.edit),
            button("Autorizar / bloquear", self.toggle_auth), button("Testar conexão (C-ECHO)", self.echo),
            button("Histórico", self.history), button("Remover", self.remove),
            button("Importar…", self.import_), button("Exportar…", self.export), stretch_at=6))
        if ctx is not None:
            self.body.addLayout(button_row(
                button("Configurações de impressão…", self.print_settings, primary=True),
                button("Calibração de imagem…", self.calibration),
                button("Regras do equipamento…", self.device_rules), button("Comparar com…", self.compare)))
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar por nome, modalidade, AE Title, IP ou unidade")
        self.search.textChanged.connect(lambda _: self._render(list(self.devices_all)))
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.show_inactive)
        self.body.addLayout(search_row)
        self.table = make_table(["Nome", "AE Title", "Modalidade", "IP:porta", "Unidade / setor",
                                 "Autorizado", "Último contato", "Situação"])
        self.table.doubleClicked.connect(lambda _: self.edit())
        self.body.addWidget(self.table, 1)
        self.devices: dict[int, object] = {}
        self.devices_all: list = []

    def on_shown(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        include = self.show_inactive.isChecked()
        run_async(lambda: self.service.list(include_inactive=include), self._render, self._error)

    def _render(self, devices) -> None:
        self.devices_all = list(devices)
        q = self.search.text().strip().lower()
        if q:
            devices = [d for d in devices if any(q in (str(x or "")).lower() for x in
                                                 (d.name, d.modality, d.ae_title, d.ip_address, d.site,
                                                  d.department, d.manufacturer, d.model))]
        self.devices = {d.id: d for d in devices}
        rows = []
        for d in devices:
            addr = f"{d.ip_address or '—'}:{d.port}" if d.port else (d.ip_address or "—")
            rows.append((d.name, d.ae_title, d.modality or "—", addr,
                         " / ".join(x for x in (d.site, d.department) if x) or "—",
                         "Sim" if d.authorized else "Não", local_time(d.last_seen_at),
                         ("Desativado" if not d.active else d.comm_status or "—")))
        fill_table(self.table, rows, [d.id for d in devices])

    def _selected(self):
        key = selected_key(self.table)
        if key is None:
            self._msg("Selecione um equipamento na lista.", "warn")
        return self.devices.get(key) if key is not None else None

    def _msg(self, text: str, style: str) -> None:
        status_text(self.status, text, "banner")
        self.status.setProperty("state", style)
        self.status.style().polish(self.status)
        self.status.show()

    def _error(self, exc: BaseException) -> None:
        self._msg(f"Falha: {exc}", "err")

    # ---------------------------------------------------------------- ações
    def add(self) -> None:
        if not ensure_admin(self, self.access, "cadastrar equipamento"):
            return
        dlg = DeviceDialog(self, self.service, ctx=self.ctx)
        if dlg.exec():
            self._msg(f"Equipamento \"{dlg.result_device.name}\" cadastrado.", "ok")
            self.refresh()

    def edit(self) -> None:
        d = self._selected()
        if d is None or not ensure_admin(self, self.access, "editar equipamento"):
            return
        dlg = DeviceDialog(self, self.service, d, ctx=self.ctx)
        if dlg.exec():
            self._msg("Alterações salvas.", "ok")
            self.refresh()

    def print_settings(self) -> None:
        from app.ui.pages.device_settings_dialog import DeviceSettingsDialog
        d = self._selected()
        if d is not None:
            DeviceSettingsDialog(self, self.ctx, d).exec()

    def calibration(self) -> None:
        from app.ui.pages.device_calibration import DeviceCalibrationDialog
        d = self.devices.get(selected_key(self.table))
        DeviceCalibrationDialog(self, self.ctx, d.id if d else None).exec()

    def device_rules(self) -> None:
        from app.ui.pages.rules_page import DeviceRulesDialog
        d = self._selected()
        if d is not None:
            DeviceRulesDialog(self, self.ctx, d).exec()

    def compare(self) -> None:
        from app.ui.pages.device_settings_dialog import DeviceSettingsDialog
        d = self._selected()
        if d is not None:
            DeviceSettingsDialog(self, self.ctx, d).compare()

    def toggle_auth(self) -> None:
        d = self._selected()
        if d is None or not ensure_admin(self, self.access, "autorizar ou bloquear equipamento"):
            return
        run_async(lambda: self.service.set_authorized(d.id, not d.authorized, actor=current_actor()),
                  lambda nd: (self._msg(f"\"{nd.name}\" {'autorizado' if nd.authorized else 'bloqueado'}.",
                                        "ok"), self.refresh()), self._error)

    def remove(self) -> None:
        d = self._selected()
        if d is None or not ensure_admin(self, self.access, "remover equipamento"):
            return
        if QMessageBox.question(self, "Remover equipamento",
                                f"Remover \"{d.name}\"? Se ele já enviou imagens, será apenas desativado "
                                "para preservar o histórico.") != QMessageBox.Yes:
            return
        run_async(lambda: self.service.remove(d.id, actor=current_actor()),
                  lambda action: (self._msg("Equipamento excluído." if action == "deleted"
                                            else "Equipamento desativado (possui histórico).", "ok"),
                                  self.refresh()), self._error)

    def echo(self) -> None:
        d = self._selected()
        if d is None:
            return
        self._msg(f"Testando conexão com \"{d.name}\"…", "muted")

        def done(r: dict) -> None:
            self._msg(f"C-ECHO para \"{d.name}\": {r['detail']}.", "ok" if r["ok"] else "err")
            self.refresh()

        def fail(exc: BaseException) -> None:
            self._msg(str(exc) if isinstance(exc, VyonixError) else f"Falha: {exc}", "err")

        run_async(lambda: self.service.echo(d.id, actor=current_actor()), done, fail)

    def history(self) -> None:
        d = self._selected()
        if d is None:
            return

        def show(events) -> None:
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Histórico — {d.name}")
            dlg.resize(820, 460)
            lay = QVBoxLayout(dlg)
            t = make_table(["Data/hora", "Nível", "Ação", "Mensagem", "Usuário"])
            fill_table(t, [(local_time(e.ts), e.level, e.action, e.message, e.actor or "") for e in events])
            lay.addWidget(t)
            bb = QDialogButtonBox(QDialogButtonBox.Close)
            bb.rejected.connect(dlg.reject)
            lay.addWidget(bb)
            dlg.exec()

        run_async(lambda: self.service.history_events(d.id), show, self._error)

    def export(self) -> None:
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Exportar equipamentos",
                                              str(self.exports_dir / "vyonix-equipamentos.json"),
                                              "JSON (*.json)")
        if path:
            run_async(lambda: self.service.export_json(Path(path)),
                      lambda n: self._msg(f"{n} equipamento(s) exportado(s).", "ok"), self._error)

    def import_(self) -> None:
        if not ensure_admin(self, self.access, "importar equipamentos"):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Importar equipamentos", str(self.exports_dir),
                                              "JSON (*.json)")
        if not path:
            return

        def fail(exc: BaseException) -> None:
            if isinstance(exc, SettingsValidationError):
                self._msg("Importação recusada: " + "; ".join(f"{k}: {v}" for k, v in exc.errors.items()),
                          "err")
            else:
                self._error(exc)

        run_async(lambda: self.service.import_json(Path(path), actor=current_actor()),
                  lambda r: (self._msg(f"Importação concluída: {r['created']} novo(s), "
                                       f"{r['updated']} atualizado(s).", "ok"), self.refresh()), fail)
