"""Regras DICOM: destino (AE Title + porta), impressão, restrições de origem opcionais e instruções ao técnico."""

from __future__ import annotations

from pathlib import Path

from app.core.errors import SettingsValidationError, VyonixError
from app.devices.service import MODALITIES, DeviceService
from app.security.access import AdminAccess
from app.ui.admin import current_actor, ensure_admin
from app.ui.pages.base import Page, banner
from app.ui.qt import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                       QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, Qt,
                       QVBoxLayout, QWidget)
from app.ui.widgets import (button, button_row, fill_table, local_time, make_table, selected_key,
                            status_text)
from app.ui.workers import run_async

ROUTE_FIELDS = [
    ("name", "Nome da regra *"), ("called_ae", "AE Title de destino (Called AE) *"), ("service", "Serviço DICOM"),
    ("listen_port", "Porta do servidor VYONIX"), ("modality", "Modalidade (informativa)"),
]
ADVANCED_FIELDS = [
    ("ae_title", "Calling AE Title do equipamento"), ("ip_address", "IP ou faixa de origem"),
    ("manufacturer", "Fabricante"), ("model", "Modelo"), ("port", "Porta do equipamento (C-ECHO de saída)"),
    ("site", "Unidade ou clínica"), ("department", "Setor"), ("print_profile_id", "Perfil de impressão"),
    ("notes", "Observações"),
]
PRINT_FIELDS = [("printer", "Impressora Windows"), ("paper", "Papel"), ("orientation", "Orientação"),
                ("layout", "Layout"), ("copies", "Cópias"), ("brightness", "Brilho"), ("contrast", "Contraste"),
                ("gamma", "Gama"), ("header_enabled", "Cabeçalho BMP"), ("footer_enabled", "Rodapé BMP"),
                ("auto_print", "Modo de impressão")]
FIELDS = ROUTE_FIELDS + ADVANCED_FIELDS


def _field_box(w: QWidget) -> tuple[QWidget, QLabel]:
    err = QLabel("")
    err.setObjectName("fieldError")
    err.hide()
    box = QWidget()
    bl = QVBoxLayout(box)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.addWidget(w)
    bl.addWidget(err)
    return box, err


class DeviceDialog(QDialog):
    """Adicionar/editar Regra DICOM: destino (AE + porta), impressão e restrições de origem opcionais."""

    def __init__(self, parent: QWidget, service: DeviceService, device=None, ctx=None) -> None:
        from app.printing.paper import LAYOUTS, PAPER_LABELS
        from app.ui.qt import QDoubleSpinBox, QGroupBox, QScrollArea
        super().__init__(parent)
        self.ctx = ctx
        self.service = service
        self.device = device
        self.result_device = None
        self.setWindowTitle("Editar Regra DICOM" if device else "Adicionar Regra DICOM")
        self.setMinimumWidth(640)
        self.resize(680, 760)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        self.editors: dict[str, QWidget] = {}
        self.errors: dict[str, QLabel] = {}

        def add(form, key, label, w):
            box, err = _field_box(w)
            form.addRow(label, box)
            self.editors[key], self.errors[key] = w, err

        g1 = QGroupBox("Destino DICOM — o equipamento envia para o IP deste computador, este AE Title e esta porta")
        f1 = QFormLayout(g1)
        add(f1, "name", "Nome da regra *", QLineEdit())
        add(f1, "called_ae", "AE Title de destino *", QLineEdit())
        svc = QComboBox()
        svc.addItem("Recepção de imagens (C-STORE)", "store")
        svc.addItem("Impressão DICOM (Print SCP)", "print")
        add(f1, "service", "Serviço DICOM", svc)
        lp = QSpinBox()
        lp.setRange(0, 65535)
        lp.setSpecialValueText("padrão do serviço")
        lp.setToolTip(f"Padrão do serviço: {service.default_port('store')} (recepção) / "
                      f"{service.default_port('print')} (impressão)")
        add(f1, "listen_port", "Porta do VYONIX", lp)
        mod = QComboBox()
        mod.addItem("—", None)
        for code, name in MODALITIES:
            mod.addItem(f"{code} — {name}", code)
        add(f1, "modality", "Modalidade (informativa)", mod)
        lay.addWidget(g1)

        self.print_editors: dict[str, QWidget] = {}
        if ctx is not None:
            g2 = QGroupBox("Impressão desta regra")
            f2 = QFormLayout(g2)

            def addp(key, label, w):
                box, err = _field_box(w)
                f2.addRow(label, box)
                self.print_editors[key], self.errors[key] = w, err
            pr = QComboBox()
            pr.addItem("— padrão do VYONIX —", None)
            try:
                for p in ctx.printers.list():
                    pr.addItem(p.name, p.name)
            except Exception:  # noqa: BLE001
                pass
            addp("printer", "Impressora Windows", pr)
            pa = QComboBox()
            for k, v in PAPER_LABELS.items():
                pa.addItem(v, k)
            addp("paper", "Papel", pa)
            ori = QComboBox()
            for k, v in (("auto", "Automática"), ("portrait", "Retrato"), ("landscape", "Paisagem")):
                ori.addItem(v, k)
            addp("orientation", "Orientação", ori)
            lo = QComboBox()
            lo.setEditable(True)
            for x in LAYOUTS:
                lo.addItem(x.replace("x", " × "), x)
            addp("layout", "Layout", lo)
            cp = QSpinBox()
            cp.setRange(1, 99)
            addp("copies", "Cópias", cp)
            for key, label in (("brightness", "Brilho"), ("contrast", "Contraste"), ("gamma", "Gama")):
                t = QDoubleSpinBox()
                t.setRange(-5.0, 5.0)
                t.setSingleStep(0.5)
                t.setDecimals(1)
                addp(key, f"{label} (−5 a +5; 0 = neutro)", t)
            for key, label in (("header_enabled", "Imprimir cabeçalho BMP"), ("footer_enabled", "Imprimir rodapé BMP")):
                addp(key, "", QCheckBox(label))
            mode = QComboBox()
            mode.addItem("Automática (imprime ao concluir o recebimento)", True)
            mode.addItem("Sob demanda (aguarda a recepção)", False)
            addp("auto_print", "Modo de impressão", mode)
            hint = QLabel("Margens, espaçamento, calibração 3 × 3 e demais ajustes: botões “Configurações de "
                          "impressão…” e “Calibração de imagem…” da lista de regras.")
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            f2.addRow(hint)
            lay.addWidget(g2)

        g3 = QGroupBox("Restrições de origem — opcional (avançado)")
        g3.setCheckable(True)
        f3 = QFormLayout(g3)
        add(f3, "ae_title", "Calling AE Title", QLineEdit())
        self.editors["ae_title"].setPlaceholderText("vazio = qualquer equipamento")
        add(f3, "ip_address", "IP ou faixa", QLineEdit())
        self.editors["ip_address"].setPlaceholderText("vazio = qualquer IP da rede (ex.: 192.168.1.20 ou 192.168.1.0/24)")
        add(f3, "manufacturer", "Fabricante", QLineEdit())
        add(f3, "model", "Modelo", QLineEdit())
        ep = QSpinBox()
        ep.setRange(0, 65535)
        ep.setSpecialValueText("—")
        add(f3, "port", "Porta do equipamento (teste C-ECHO de saída)", ep)
        add(f3, "site", "Unidade ou clínica", QLineEdit())
        add(f3, "department", "Setor", QLineEdit())
        pf = QComboBox()
        pf.addItem("— nenhum —", None)
        try:
            for p in (ctx.profiles.list() if ctx is not None else []):
                pf.addItem(p.name, p.id)
        except Exception:  # noqa: BLE001
            pass
        add(f3, "print_profile_id", "Perfil de impressão", pf)
        notes = QPlainTextEdit()
        notes.setFixedHeight(60)
        add(f3, "notes", "Observações", notes)
        warn = QLabel("AE Title e endereço IP não são autenticação criptográfica: use também a segmentação da rede e o "
                      "Firewall do Windows. Associações fora das restrições são recusadas e registradas no Histórico.")
        warn.setWordWrap(True)
        warn.setObjectName("muted")
        f3.addRow(warn)
        lay.addWidget(g3)
        self.advanced = g3
        self.authorized = QCheckBox("Regra habilitada")
        self.authorized.setChecked(True)
        if device is None:
            lay.addWidget(self.authorized)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        if device:
            self._fill(device)
        else:
            g3.setChecked(False)
            if ctx is not None:
                self._fill_print({"paper": ctx.settings.get("printing.paper"), "orientation": "auto",
                                  "layout": ctx.settings.get("printing.layout"), "copies": 1,
                                  "header_enabled": ctx.settings.get("print_identity.header_enabled"),
                                  "footer_enabled": ctx.settings.get("print_identity.footer_enabled"),
                                  "auto_print": True})

    @staticmethod
    def _set(w, value) -> None:
        from app.ui.qt import QDoubleSpinBox
        if isinstance(w, QComboBox):
            i = w.findData(value)
            if i < 0 and w.isEditable() and value:
                w.setEditText(str(value))
            else:
                w.setCurrentIndex(max(i, 0))
        elif isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        elif isinstance(w, QDoubleSpinBox):
            w.setValue(float(value or 0))
        elif isinstance(w, QSpinBox):
            w.setValue(int(value or 0))
        elif isinstance(w, QPlainTextEdit):
            w.setPlainText(value or "")
        else:
            w.setText("" if value in (None, "*") else str(value))

    @staticmethod
    def _get(w):
        from app.ui.qt import QDoubleSpinBox
        if isinstance(w, QComboBox):
            if w.isEditable():
                i = w.findText(w.currentText())
                return w.itemData(i) if i >= 0 else w.currentText().replace(" × ", "x").replace(" ", "")
            return w.currentData()
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QDoubleSpinBox):
            return round(w.value(), 1)
        if isinstance(w, QSpinBox):
            return w.value() or None
        if isinstance(w, QPlainTextEdit):
            return w.toPlainText()
        return w.text()

    def _fill(self, d) -> None:
        for key, w in self.editors.items():
            self._set(w, getattr(d, key))
        self.advanced.setChecked(bool(d.calling_restriction or d.ip_address or d.manufacturer or d.model or d.port))
        if self.ctx is not None:
            try:
                self._fill_print(self.ctx.device_settings.get(d.id))
            except Exception:  # noqa: BLE001
                pass

    def _fill_print(self, values: dict) -> None:
        for key, w in self.print_editors.items():
            if key in values and values[key] is not None:
                self._set(w, values[key])

    def values(self) -> dict:
        out = {key: self._get(w) for key, w in self.editors.items()}
        if not self.advanced.isChecked():
            for key in ("ae_title", "ip_address"):
                out[key] = None
        return out

    def print_values(self) -> dict:
        out = {key: self._get(w) for key, w in self.print_editors.items()}
        if not out.get("printer"):
            out.pop("printer", None)
        return out

    def _save(self) -> None:
        from app.core.errors import ValidationError
        for e in self.errors.values():
            e.hide()
        try:
            if self.ctx is not None:                       # valida a impressão antes de gravar a regra
                from app.devices.settings import validate_values
                validate_values(self.print_values())
            if self.device:
                self.result_device = self.service.update(self.device.id, self.values(), actor=current_actor())
            else:
                self.result_device = self.service.create(self.values(), actor=current_actor(),
                                                         authorized=self.authorized.isChecked())
            if self.ctx is not None:
                self.ctx.device_settings.save(self.result_device.id, self.print_values(), actor=current_actor(),
                                              reason="cadastro da regra", replace_all=False)
        except SettingsValidationError as exc:
            for key, msg in exc.errors.items():
                k = key.split(".")[-1]
                if k in self.errors:
                    self.errors[k].setText(msg)
                    self.errors[k].show()
                else:
                    QMessageBox.warning(self, "Regra DICOM", f"{key}: {msg}")
            return
        except ValidationError as exc:
            QMessageBox.warning(self, "Regra DICOM", str(exc))
            return
        self.accept()


class DestinationDialog(QDialog):
    """Configurar destino no equipamento — dados para o técnico configurar a modalidade."""

    def __init__(self, parent: QWidget, ctx, rule) -> None:
        from app.ui.qt import QApplication, QGroupBox
        from app.utils.net import best_server_address
        super().__init__(parent)
        self.ctx, self.rule = ctx, rule
        self.setWindowTitle("Configurar destino no equipamento")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        svc = rule.service
        port = rule.effective_port(ctx.devices.default_port(svc))
        hint = rule.ip_address or self._last_ip()
        ip, ips = best_server_address(ctx.settings.get("dicom.storage.bind_address"), hint)
        self.ip, self.port = ip, port
        g = QGroupBox("Informe no equipamento (destino DICOM / nó de rede)")
        f = QFormLayout(g)
        for label, value in (("Nome da regra", rule.name), ("AE Title de destino", rule.called_ae),
                             ("IP do servidor VYONIX", ip or "não identificado"), ("Porta", str(port)),
                             ("Serviço", "Recepção de imagens (Storage / C-STORE)" if svc == "store"
                              else "Impressão DICOM (Basic Print)")):
            v = QLabel(f"<b>{value}</b>")
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            f.addRow(label, v)
        if rule.calling_restriction:
            f.addRow("AE Title do equipamento", QLabel(f"<b>{rule.calling_restriction}</b> (exigido pela regra)"))
        lay.addWidget(g)
        if len(ips) > 1:
            other = QLabel("Este computador tem mais de uma rede: " + ", ".join(ips) + ". Use o IP da rede em que o "
                           "equipamento está" + (f" (escolhido pela faixa {hint})." if hint else "."))
            other.setWordWrap(True)
            lay.addWidget(other)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        text = (f"Regra: {rule.name}\nAE Title de destino: {rule.called_ae}\nIP do servidor VYONIX: {ip}\n"
                f"Porta: {port}")
        for label, slot in (("Copiar configuração", lambda: (QApplication.clipboard().setText(text),
                                                             self.status.setText("Configuração copiada."))),
                            ("Testar conexão (C-ECHO)", self.echo), ("Verificar porta ativa", self.check_port),
                            ("Último equipamento conectado", self.last_seen),
                            ("Erros de associação", self.errors_log)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, fn=slot: fn())
            row.addWidget(b)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _last_ip(self) -> str | None:
        r = self.ctx.db.connection().execute("SELECT source_ip FROM instances WHERE device_id = ? "
                                             "ORDER BY id DESC LIMIT 1", (self.rule.id,)).fetchone()
        return r["source_ip"] if r and r["source_ip"] else None

    def _scp(self):
        return self.ctx.storage_scp if self.rule.service == "store" else self.ctx.print_scp

    def check_port(self) -> None:
        import socket
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=2):
                pass
            self.status.setText(f"Porta {self.port} ativa: o VYONIX está escutando.")
        except OSError as exc:
            self.status.setText(f"Porta {self.port} NÃO está ativa ({exc}). Verifique o Servidor DICOM e o serviço "
                                "Windows.")

    def echo(self) -> None:
        from app.dicom import scu
        from app.dicom.association_manager import SELFTEST_AE
        self.status.setText("Testando…")

        def work():
            return scu.echo("127.0.0.1", self.port, self.rule.called_ae, calling_ae=SELFTEST_AE)
        run_async(work, lambda r: self.status.setText(
            ("C-ECHO aceito: destino " if r.get("ok") else "C-ECHO falhou: ") + f"{self.rule.called_ae} na porta "
            f"{self.port} — {r.get('detail')}. Para o teste completo, use também o “Verify/Echo” do equipamento."),
                  lambda exc: self.status.setText(f"Falha: {exc}"))

    def last_seen(self) -> None:
        r = self.ctx.db.connection().execute(
            "SELECT source_ae, source_ip, received_at FROM instances WHERE device_id = ? ORDER BY id DESC LIMIT 1",
            (self.rule.id,)).fetchone()
        d = self.ctx.devices.get(self.rule.id)
        if r:
            self.status.setText(f"Último envio: {r['source_ae']} de {r['source_ip']} em {local_time(r['received_at'])}"
                                f" · último contato: {local_time(d.last_seen_at)} ({d.comm_status or '—'}).")
        else:
            self.status.setText(f"Nenhuma imagem recebida por esta regra. Último contato: {local_time(d.last_seen_at)}.")

    def errors_log(self) -> None:
        from app.database.repositories.events_repo import EventFilter
        evs = [e for e in self.ctx.events.query(EventFilter(limit=300))
               if e.action in ("assoc.reject", "print_assoc.reject") and
               ((e.device_id == self.rule.id) or (self.rule.called_ae or "") in e.message)][:15]
        if not evs:
            self.status.setText("Nenhum erro de associação registrado para esta regra.")
            return
        self.status.setText("<br>".join(f"{local_time(e.ts)} — {e.message}" for e in evs))


class DevicesPage(Page):
    def __init__(self, service: DeviceService, access: AdminAccess, exports_dir: Path,
                 parent: QWidget | None = None, ctx=None) -> None:
        super().__init__("Regras DICOM",
                         "Cada regra é um destino DICOM: o equipamento envia para o IP deste computador, com o AE "
                         "Title de destino e a porta da regra. O IP do equipamento não é necessário (restrição "
                         "opcional). A regra define impressora, papel, layout, calibração e o modo automático ou "
                         "sob demanda.", parent)
        self.service, self.access, self.exports_dir = service, access, exports_dir
        self.ctx = ctx
        self.status = banner("")
        self.status.hide()
        self.body.addWidget(self.status)
        self.show_inactive = QCheckBox("Mostrar desativados")
        self.show_inactive.toggled.connect(lambda _: self.refresh())
        self.body.addLayout(button_row(
            button("Adicionar Regra DICOM", self.add, primary=True), button("Editar", self.edit),
            button("Configurar destino no equipamento…", self.destination),
            button("Habilitar / desabilitar", self.toggle_auth), button("Duplicar", self.duplicate),
            button("Histórico", self.history), button("Remover", self.remove),
            button("Importar…", self.import_), button("Exportar…", self.export), stretch_at=9))
        if ctx is not None:
            self.body.addLayout(button_row(
                button("Configurações de impressão…", self.print_settings, primary=True),
                button("Calibração de imagem…", self.calibration),
                button("Regras avançadas da regra…", self.device_rules), button("Comparar com…", self.compare),
                button("C-ECHO para o equipamento", self.echo)))
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar por nome, AE Title de destino, Calling AE, modalidade, IP ou unidade")
        self.search.textChanged.connect(lambda _: self._render(list(self.devices_all)))
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.show_inactive)
        self.body.addLayout(search_row)
        self.table = make_table(["Nome", "AE Title de destino", "Serviço", "Porta", "Restrições de origem",
                                 "Modalidade", "Habilitada", "Último contato", "Situação"])
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
                                                 (d.name, d.modality, d.ae_title, d.called_ae, d.ip_address, d.site,
                                                  d.department, d.manufacturer, d.model))]
        self.devices = {d.id: d for d in devices}
        rows = []
        for d in devices:
            restr = " · ".join(x for x in (f"Calling {d.calling_restriction}" if d.calling_restriction else "",
                                            f"IP {d.ip_address}" if d.ip_address else "") if x) or "qualquer origem"
            port = d.effective_port(self.service.default_port(d.service))
            rows.append((d.name, d.called_ae or "—", "C-STORE" if d.service == "store" else "DICOM Print",
                         f"{port}" + ("" if d.listen_port else " (padrão)"), restr, d.modality or "—",
                         "Sim" if d.authorized else "Não", local_time(d.last_seen_at),
                         ("Desativada" if not d.active else d.comm_status or "—")))
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
        if not ensure_admin(self, self.access, "criar Regra DICOM"):
            return
        dlg = DeviceDialog(self, self.service, ctx=self.ctx)
        if dlg.exec():
            self._msg(f"Regra DICOM \"{dlg.result_device.name}\" criada.", "ok")
            self.refresh()
            if self.ctx is not None:
                DestinationDialog(self, self.ctx, dlg.result_device).exec()

    def destination(self) -> None:
        d = self._selected()
        if d is not None and self.ctx is not None:
            DestinationDialog(self, self.ctx, d).exec()

    def duplicate(self) -> None:
        """Cópia independente da regra (novo AE Title de destino) com as mesmas configurações de impressão."""
        from app.ui.qt import QInputDialog
        d = self._selected()
        if d is None or not ensure_admin(self, self.access, "duplicar Regra DICOM"):
            return
        ae, ok = QInputDialog.getText(self, "Duplicar regra", "AE Title de destino da nova regra:",
                                      text=(d.called_ae or "")[:13] + "_2")
        if not ok or not ae.strip():
            return
        from app.devices.repository import EDITABLE
        data = {k: getattr(d, k) for k in EDITABLE}
        data.update(name=f"{d.name} (cópia)", called_ae=ae.strip())
        try:
            new = self.service.create(data, actor=current_actor(), authorized=False)
            if self.ctx is not None:
                self.ctx.device_settings.save(new.id, self.ctx.device_settings.get(d.id), actor=current_actor(),
                                              reason=f"cópia da regra {d.name}")
        except SettingsValidationError as exc:
            QMessageBox.warning(self, "Duplicar regra", "\n".join(exc.errors.values()))
            return
        self._msg(f"Regra \"{new.name}\" criada desabilitada: revise e habilite.", "ok")
        self.refresh()

    def edit(self) -> None:
        d = self._selected()
        if d is None or not ensure_admin(self, self.access, "editar Regra DICOM"):
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
