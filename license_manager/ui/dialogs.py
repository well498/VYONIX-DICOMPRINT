"""Diálogos do License Manager: acesso, cliente, emissão, renovação e REATIVAR / EMITIR NOVA LICENÇA."""

from __future__ import annotations

from datetime import datetime, time, timezone
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox,
                               QVBoxLayout)

from vyonix_protocol import formats as F

from license_manager.service import LMError
from license_manager.ui.common import error, fill, info, table, when

TPM_TEXT = {"verified": "assinada pelo TPM do computador (prova verificada)", "absent": "computador sem TPM disponível",
            "invalid": "ASSINATURA DO TPM INVÁLIDA — confirme a origem da solicitação",
            "error": "o TPM não assinou a solicitação"}


class SetupDialog(QDialog):
    """Primeira execução: cria o administrador."""

    def __init__(self, lm, parent=None) -> None:
        super().__init__(parent)
        self.lm = lm
        self.user = None
        self.setWindowTitle("VYONIX License Manager — configuração inicial")
        lay = QVBoxLayout(self)
        t = QLabel("<h2>Configuração inicial</h2>Crie o usuário administrador. A senha protege o acesso ao aplicativo; "
                   "a chave de emissão terá uma frase-senha própria.")
        t.setWordWrap(True)
        lay.addWidget(t)
        form = QFormLayout()
        self.username = QLineEdit("admin")
        self.name = QLineEdit()
        self.pw1 = QLineEdit()
        self.pw2 = QLineEdit()
        for w in (self.pw1, self.pw2):
            w.setEchoMode(QLineEdit.Password)
        form.addRow("Usuário", self.username)
        form.addRow("Nome", self.name)
        form.addRow("Senha (mín. 10, maiúsculas, minúsculas e números)", self.pw1)
        form.addRow("Repita a senha", self.pw2)
        lay.addLayout(form)
        lay.addWidget(QLabel(f"Dados: {lm.paths.root} ({'portátil' if lm.paths.mode == 'portable' else lm.paths.mode})"))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self) -> None:
        if self.pw1.text() != self.pw2.text():
            error(self, "As senhas não conferem.")
            return
        try:
            self.user = self.lm.initialize(self.username.text(), self.name.text(), self.pw1.text())
        except Exception as exc:  # noqa: BLE001
            error(self, exc)
            return
        self.accept()


class LoginDialog(QDialog):
    def __init__(self, lm, parent=None) -> None:
        super().__init__(parent)
        self.lm = lm
        self.user = None
        self.setWindowTitle("VYONIX License Manager — acesso")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<h2>VYONIX License Manager</h2>Acesso administrativo"))
        form = QFormLayout()
        self.username = QLineEdit()
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        form.addRow("Usuário", self.username)
        form.addRow("Senha", self.pw)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self) -> None:
        try:
            self.user = self.lm.login(self.username.text(), self.pw.text())
        except Exception as exc:  # noqa: BLE001
            error(self, exc)
            self.pw.clear()
            return
        self.accept()


class CustomerDialog(QDialog):
    LABELS = {"name": "Nome / razão social *", "document": "CNPJ / CPF", "contact": "Responsável", "email": "E-mail",
              "phone": "Telefone", "city": "Cidade", "state": "UF", "notes": "Observações"}

    def __init__(self, lm, user, cid=None, parent=None) -> None:
        super().__init__(parent)
        self.lm, self.user, self.cid = lm, user, cid
        self.setWindowTitle("Cliente")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        data = lm.customer(cid) if cid else {}
        self.edits = {}
        for k, label in self.LABELS.items():
            e = QLineEdit(str(data.get(k) or ""))
            self.edits[k] = e
            form.addRow(label, e)
        lay.addLayout(form)
        note = QLabel("LGPD: registre apenas os dados necessários ao contrato. Use “Anonimizar” para remover os dados "
                      "pessoais mantendo o histórico técnico das licenças.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self) -> None:
        try:
            self.cid = self.lm.save_customer(self.user, {k: e.text() for k, e in self.edits.items()}, self.cid)
        except Exception as exc:  # noqa: BLE001
            error(self, exc)
            return
        self.accept()


def _date_edit(d: datetime | None = None, *, optional: bool = False) -> QDateEdit:
    e = QDateEdit()
    e.setCalendarPopup(True)
    e.setDisplayFormat("dd/MM/yyyy")
    if d is None:
        e.setDate(QDate.currentDate())
    else:
        loc = d.astimezone(F.BRT)
        e.setDate(QDate(loc.year, loc.month, loc.day))
    return e


def _qdate_start(e: QDateEdit) -> datetime:
    q = e.date()
    return datetime.combine(datetime(q.year(), q.month(), q.day()).date(), time(0, 0), tzinfo=F.BRT).astimezone(
        timezone.utc)


def _qdate_end(e: QDateEdit) -> datetime:
    q = e.date()
    return datetime(q.year(), q.month(), q.day(), 23, 59, 59, tzinfo=F.BRT).astimezone(timezone.utc)


def save_document(parent, lm, user, lic: dict) -> None:
    default = lm.paths.exports_dir / f"{lic['license_id']}.vylic"
    path, _ = QFileDialog.getSaveFileName(parent, "Exportar licença assinada", str(default), "Licença VYONIX (*.vylic)")
    if path:
        lm.export_license(user, lic["license_id"], Path(path))
        info(parent, f"Licença {lic['license_id']} exportada:\n{path}\n\nEnvie o arquivo ao cliente: ele o importa em "
                     "Licença → Ativar licença comercial.")


class ValidityBox(QGroupBox):
    """Tipo, início, vencimento, edição, quantidades e recursos."""

    def __init__(self, lm, *, product: dict, defaults: dict | None = None, allow_type_change: bool = True) -> None:
        super().__init__("Direitos e validade")
        d = defaults or {}
        form = QFormLayout(self)
        self.type = QComboBox()
        for k, (label, _m, _h) in F.LICENSE_TYPES.items():
            self.type.addItem(label, k)
        self.type.setCurrentIndex(max(0, self.type.findData(d.get("type", "annual"))))
        self.type.setEnabled(allow_type_change)
        self.edition = QComboBox()
        self.edition.addItems(product["editions"])
        if d.get("edition"):
            self.edition.setCurrentText(d["edition"])
        self.start_auto = QCheckBox("Início na emissão")
        self.start_auto.setChecked(True)
        self.start = _date_edit()
        self.end = _date_edit()
        self.end.setDate(QDate.currentDate().addYears(1))
        self.preview = QLabel("")
        self.preview.setObjectName("muted")
        self.devices = QSpinBox()
        self.devices.setRange(0, 999)
        self.devices.setSpecialValueText("sem limite")
        self.devices.setValue(int(d.get("max_devices") if d.get("max_devices") is not None
                                  else product.get("default_max_devices") or 0))
        self.printers = QSpinBox()
        self.printers.setRange(0, 999)
        self.printers.setSpecialValueText("sem limite")
        self.printers.setValue(int(d.get("max_printers") if d.get("max_printers") is not None
                                   else product.get("default_max_printers") or 0))
        self.features = {}
        fl = QHBoxLayout()
        for f in F.FEATURES:
            cb = QCheckBox(F.FEATURE_LABELS[f])
            cb.setChecked(f in (d.get("features") or product["features"]))
            self.features[f] = cb
            fl.addWidget(cb)
        self.notes = QLineEdit(d.get("notes") or "")
        sr = QHBoxLayout()
        sr.addWidget(self.start_auto)
        sr.addWidget(self.start)
        form.addRow("Tipo de licença", self.type)
        form.addRow("Edição", self.edition)
        form.addRow("Data de início", sr)
        form.addRow("Vencimento (personalizada)", self.end)
        form.addRow("", self.preview)
        form.addRow("Equipamentos autorizados", self.devices)
        form.addRow("Impressoras autorizadas", self.printers)
        form.addRow("Recursos liberados", fl)
        form.addRow("Observações (internas)", self.notes)
        for sig in (self.type.currentIndexChanged, self.start_auto.toggled, self.start.dateChanged, self.end.dateChanged):
            sig.connect(lambda *_: self._update())
        self._update()

    def _update(self) -> None:
        t = self.type.currentData()
        self.start.setEnabled(not self.start_auto.isChecked())
        self.end.setEnabled(t == "custom")
        start = datetime.now(timezone.utc) if self.start_auto.isChecked() else _qdate_start(self.start)
        try:
            exp = F.compute_expiry(t, start, _qdate_end(self.end) if t == "custom" else None)
        except ValueError:
            exp = None
        if t == "demo":
            self.preview.setText("DEMO: 120 horas a partir da ativação no computador (ativar em até 30 dias). "
                                 "Bloqueada se o computador já recebeu DEMO, salvo justificativa.")
        elif t == "permanent":
            self.preview.setText("Sem vencimento comercial; continua vinculada ao hardware, à instalação e à assinatura.")
        else:
            self.preview.setText(f"Vencimento: {when(F.iso(exp)) if exp else '—'}")

    def values(self) -> dict:
        t = self.type.currentData()
        return {"ltype": t, "edition": self.edition.currentText(),
                "starts": None if self.start_auto.isChecked() else _qdate_start(self.start),
                "custom_end": _qdate_end(self.end) if t == "custom" else None,
                "max_devices": self.devices.value() or None, "max_printers": self.printers.value() or None,
                "features": [f for f, cb in self.features.items() if cb.isChecked()],
                "notes": self.notes.text().strip() or None}


def request_summary(info_obj) -> str:
    d = info_obj.data
    return (f"<b>Hardware ID:</b> {d['hardware_id']}<br><b>Installation ID:</b> {d['installation_id']}<br>"
            f"<b>Unidade:</b> {d.get('site') or '—'} · <b>versão:</b> {d.get('app_version') or '—'} · "
            f"<b>solicitada em:</b> {when(d.get('requested_at'))}<br>"
            f"<b>Motivo informado:</b> {F.REACTIVATION_REASONS.get(d.get('reason'), 'primeira ativação')}"
            + (f" · licença anterior: {d['previous_license_id']}" if d.get("previous_license_id") else "")
            + f"<br><b>TPM:</b> {TPM_TEXT.get(info_obj.tpm_status, info_obj.tpm_status)}"
            + ("<br><b>Este computador já usou a demonstração local.</b>" if d.get("demo_used") else ""))


class IssueDialog(QDialog):
    """Emitir licença a partir de uma solicitação importada."""

    def __init__(self, lm, user, req_info, parent=None) -> None:
        super().__init__(parent)
        self.lm, self.user, self.req = lm, user, req_info
        self.result_license = None
        self.setWindowTitle("Emitir licença")
        self.resize(860, 760)
        lay = QVBoxLayout(self)
        s = QLabel(request_summary(req_info))
        s.setWordWrap(True)
        s.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(s)
        if req_info.related:
            g = QGroupBox("Histórico deste computador (identifique a licença anterior para reativar)")
            gl = QVBoxLayout(g)
            t = table(["Licença", "Cliente", "Tipo", "Situação", "Installation ID", "Correspondência"])
            fill(t, [(r["license_id"], r["customer"], r["type"], r["status"], r["installation_id"], r["match"])
                     for r in req_info.related])
            t.setMaximumHeight(140)
            gl.addWidget(t)
            lay.addWidget(g)
        form = QFormLayout()
        self.customer = QComboBox()
        self._load_customers()
        new_c = QPushButton("Novo cliente…")
        new_c.clicked.connect(lambda _=False: self._new_customer())
        cr = QHBoxLayout()
        cr.addWidget(self.customer, 1)
        cr.addWidget(new_c)
        form.addRow("Cliente *", cr)
        lay.addLayout(form)
        self.validity = ValidityBox(lm, product=lm.product(F.PRODUCT_ID))
        lay.addWidget(self.validity)
        self.demo_reason = QLineEdit()
        self.demo_reason.setPlaceholderText("Somente para emitir outra DEMO a um computador que já recebeu uma")
        f2 = QFormLayout()
        f2.addRow("Justificativa de DEMO repetida", self.demo_reason)
        lay.addLayout(f2)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        ok = bb.addButton("Emitir e exportar licença assinada", QDialogButtonBox.AcceptRole)
        ok.setObjectName("primary")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _load_customers(self, select: int | None = None) -> None:
        self.customer.clear()
        self.customer.addItem("— selecione —", None)
        for c in self.lm.customers():
            self.customer.addItem(f"{c['name']}" + (f" ({c['document']})" if c["document"] else ""), c["id"])
        pre = select or (self.req.known_installation or {}).get("customer_id")
        if pre:
            self.customer.setCurrentIndex(max(0, self.customer.findData(pre)))

    def _new_customer(self) -> None:
        d = CustomerDialog(self.lm, self.user, parent=self)
        if d.exec():
            self._load_customers(d.cid)

    def _ok(self) -> None:
        cid = self.customer.currentData()
        if not cid:
            error(self, "Selecione o cliente.")
            return
        from license_manager.ui.main import ensure_unlocked
        if not ensure_unlocked(self, self.lm, self.user):
            return
        v = self.validity.values()
        try:
            self.result_license = self.lm.issue(self.user, self.req.request_id, cid, product_id=F.PRODUCT_ID,
                                                demo_override=self.demo_reason.text().strip() or None, **v)
        except LMError as exc:
            error(self, exc)
            return
        save_document(self, self.lm, self.user, self.result_license)
        self.accept()


class RenewDialog(QDialog):
    def __init__(self, lm, user, lic: dict, parent=None) -> None:
        super().__init__(parent)
        self.lm, self.user, self.lic = lm, user, lic
        self.setWindowTitle(f"Renovar {lic['license_id']}")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Cliente: <b>{lic['customer']}</b> · mesma instalação ({lic['installation_id']}) e "
                             f"computador ({lic['hardware_id']}).<br>Vencimento atual: {when(lic['expires_at'])}. "
                             "Na renovação antecipada, o novo período começa no fim do atual."))
        self.validity = ValidityBox(lm, product=lm.product(lic["product_id"]), defaults=lic)
        lay.addWidget(self.validity)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        bb.addButton("Renovar e exportar", QDialogButtonBox.AcceptRole).setObjectName("primary")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self) -> None:
        from license_manager.ui.main import ensure_unlocked
        if not ensure_unlocked(self, self.lm, self.user):
            return
        v = self.validity.values()
        try:
            new = self.lm.renew(self.user, self.lic["license_id"], ltype=v["ltype"], starts=v["starts"],
                                custom_end=v["custom_end"], edition=v["edition"], max_devices=v["max_devices"],
                                max_printers=v["max_printers"], features=v["features"], notes=v["notes"])
        except LMError as exc:
            error(self, exc)
            return
        save_document(self, self.lm, self.user, new)
        self.accept()


class ReactivateDialog(QDialog):
    """REATIVAR / EMITIR NOVA LICENÇA — troca de hardware, reinstalação, recuperação."""

    def __init__(self, lm, user, lic: dict, parent=None) -> None:
        super().__init__(parent)
        self.lm, self.user, self.lic = lm, user, lic
        self.req = None
        self.setWindowTitle("REATIVAR / EMITIR NOVA LICENÇA")
        self.resize(820, 640)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>Licença anterior:</b> {lic['license_id']} — {lic['customer']} — {lic['type_label']} "
                             f"— situação {lic['status']}<br>Hardware ID {lic['hardware_id']} · Installation ID "
                             f"{lic['installation_id']}"))
        hist = lm.customer_history(lic["customer_id"])
        g = QGroupBox("Histórico do cliente (instalações e reemissões)")
        gl = QVBoxLayout(g)
        t = table(["Licença", "Operação", "Tipo", "Situação", "Hardware ID", "Installation ID", "Motivo"])
        fill(t, [(x["license_id"], x["operation"], x["type"], x["status"], x["hardware_id"], x["installation_id"],
                  F.REACTIVATION_REASONS.get(x["reason_code"] or "", x["reason_code"] or ""))
                 for x in hist["licenses"]])
        t.setMaximumHeight(160)
        gl.addWidget(t)
        lay.addWidget(g)
        imp = QPushButton("Importar a nova solicitação (.vyreq ou código)…")
        imp.clicked.connect(lambda _=False: self._import())
        lay.addWidget(imp)
        self.req_label = QLabel("Nenhuma solicitação importada.")
        self.req_label.setWordWrap(True)
        lay.addWidget(self.req_label)
        form = QFormLayout()
        self.reason = QComboBox()
        for k, label in F.REACTIVATION_REASONS.items():
            if k != "time":
                self.reason.addItem(label, k)
        self.reason_text = QPlainTextEdit()
        self.reason_text.setPlaceholderText("Descreva o que aconteceu (fica registrado no histórico do cliente)")
        self.reason_text.setMaximumHeight(80)
        self.keep = QCheckBox("Manter o vencimento da licença anterior")
        self.keep.setChecked(True)
        form.addRow("Motivo *", self.reason)
        form.addRow("Descrição *", self.reason_text)
        form.addRow("", self.keep)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        bb.addButton("Emitir nova licença assinada", QDialogButtonBox.AcceptRole).setObjectName("primary")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _import(self) -> None:
        text = import_request_text(self)
        if not text:
            return
        try:
            self.req = self.lm.import_request(self.user, text)
        except LMError as exc:
            error(self, exc)
            return
        self.req_label.setText(request_summary(self.req))
        rc = self.req.data.get("reason")
        if rc and self.reason.findData(rc) >= 0:
            self.reason.setCurrentIndex(self.reason.findData(rc))

    def _ok(self) -> None:
        if self.req is None:
            error(self, "Importe a nova solicitação do computador do cliente.")
            return
        from license_manager.ui.main import ensure_unlocked
        if not ensure_unlocked(self, self.lm, self.user):
            return
        try:
            new = self.lm.reactivate(self.user, self.lic["license_id"], self.req.request_id, self.reason.currentData(),
                                     self.reason_text.toPlainText().strip(), keep_validity=self.keep.isChecked())
        except LMError as exc:
            error(self, exc)
            return
        save_document(self, self.lm, self.user, new)
        self.accept()


def import_request_text(parent) -> str | None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Importar solicitação de ativação")
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel("Cole o código VYXR2-… ou abra o arquivo .vyreq enviado pelo cliente."))
    edit = QPlainTextEdit()
    lay.addWidget(edit)
    openb = QPushButton("Abrir arquivo .vyreq…")

    def load() -> None:
        path, _ = QFileDialog.getOpenFileName(dlg, "Solicitação", "", "Solicitação VYONIX (*.vyreq *.txt);;Todos (*)")
        if path:
            edit.setPlainText(Path(path).read_text(encoding="utf-8"))
    openb.clicked.connect(lambda _=False: load())
    lay.addWidget(openb)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    if dlg.exec() and edit.toPlainText().strip():
        return edit.toPlainText().strip()
    return None
