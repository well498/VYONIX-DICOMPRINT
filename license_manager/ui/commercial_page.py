"""Gestão Comercial: assinaturas, vencimentos, pagamentos, carência, suspensão controlada e reativação."""

from __future__ import annotations

from datetime import datetime, time, timezone
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QSpinBox,
                               QTabWidget, QVBoxLayout)

from vyonix_protocol import formats as F
from vyonix_commercial.engine import ROLES, money
from vyonix_commercial.states import STATE_LABELS

from license_manager.commercial import LocalCommercial, RemoteCommercial, as_error
from license_manager.ui.common import Page, btn, confirm, error, fill, info, row, selected, table, when

ACTION_TITLES = {
    "payment": "Registrar pagamento confirmado", "claim": "Registrar comprovante / promessa (não quita)",
    "grace": "Conceder prorrogação de carência", "schedule-suspension": "Programar suspensão",
    "cancel-suspension": "Cancelar suspensão programada", "suspend": "Suspender conforme a política",
    "reactivate": "Reativar assinatura",
}
NEEDS_CONFIRM = {"suspend": "suspend", "schedule-suspension": "schedule_suspension", "reactivate": "reactivate",
                 "grace": "grace", "payment": "payment"}


def _date(days: int = 0) -> QDateEdit:
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setDisplayFormat("dd/MM/yyyy")
    d.setDate(QDate.currentDate().addDays(days))
    return d


def _iso_date(d: QDateEdit, end: bool = True) -> str:
    q = d.date()
    t = time(23, 59, 59) if end else time(0, 0)
    local = datetime(q.year(), q.month(), q.day(), t.hour, t.minute, t.second, tzinfo=F.BRT)
    return F.iso(local.astimezone(timezone.utc))


class ActionDialog(QDialog):
    """Formulário de uma ação comercial (com confirmação de administrador quando exigida)."""

    def __init__(self, page, sub: dict, name: str) -> None:
        super().__init__(page)
        self.page, self.sub, self.name = page, sub, name
        self.data: dict | None = None
        self.setWindowTitle(ACTION_TITLES[name])
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{sub['customer_name']}</b> — licença {sub['license_id']}<br>Situação: "
                      f"<b>{sub['state_label']}</b> · vencimento {when(sub['paid_until'])} · carência até "
                      f"{when(sub['grace_until'])}")
        head.setWordWrap(True)
        lay.addWidget(head)
        self.form = QFormLayout()
        lay.addLayout(self.form)
        self.w: dict = {}
        if name == "payment":
            self.w["reference"] = QLineEdit()
            self.w["reference"].setPlaceholderText("nº do documento bancário / código da cobrança / ID Pix")
            self.w["periods"] = QSpinBox()
            self.w["periods"].setRange(1, 36)
            self.w["amount"] = QLineEdit(f"{(sub.get('price_cents') or 0) / 100:.2f}".replace(".", ","))
            self.form.addRow("Referência do pagamento *", self.w["reference"])
            self.form.addRow("Períodos pagos", self.w["periods"])
            self.form.addRow("Valor recebido (R$)", self.w["amount"])
            if not sub.get("plan_months"):
                self.w["until"] = _date(30)
                self.form.addRow("Quita até", self.w["until"])
            note = QLabel("Registre somente pagamento <b>confirmado</b> (baixa bancária conferida). Boleto emitido, "
                          "comprovante enviado pelo cliente ou promessa não quitam.")
            note.setWordWrap(True)
            lay.addWidget(note)
        elif name == "claim":
            self.w["note"] = QPlainTextEdit()
            self.form.addRow("Descrição *", self.w["note"])
        elif name == "grace":
            self.w["days"] = QSpinBox()
            self.w["days"].setRange(1, 90)
            self.w["days"].setValue(7)
            self.form.addRow("Dias adicionais", self.w["days"])
        elif name in ("schedule-suspension", "suspend"):
            if name == "schedule-suspension":
                self.w["at"] = _date(3)
                self.form.addRow("Suspender em (fim do dia)", self.w["at"])
            self.w["ack"] = QCheckBox("Verifiquei a política contratual e os requisitos operacionais da clínica "
                                      "(trabalhos em andamento, plantões, comunicação ao responsável)")
            lay.addWidget(self.w["ack"])
            warn = QLabel("A suspensão restringe apenas novas operações licenciadas. Imagens, filas, calibrações, "
                          "histórico e a exportação de dados são preservados; trabalhos já aceitos são concluídos.")
            warn.setWordWrap(True)
            lay.addWidget(warn)
        elif name == "reactivate":
            self.w["extend"] = QCheckBox("Liberar até (prorrogação enquanto a regularização é concluída)")
            self.w["until"] = _date(15)
            self.form.addRow(self.w["extend"], self.w["until"])
        if name != "payment" and name != "claim":
            self.w["reason"] = QLineEdit()
            self.form.addRow("Motivo *", self.w["reason"])
        role = page.backend.user.role if isinstance(page.backend, LocalCommercial) else (page.backend.user or {}).get(
            "role")
        needed = [x.strip() for x in page.settings.get("confirm_actions", "").split(",")]
        if name in NEEDS_CONFIRM and NEEDS_CONFIRM[name] in needed and role != "admin":
            self.w["cu"] = QLineEdit()
            self.w["cp"] = QLineEdit()
            self.w["cp"].setEchoMode(QLineEdit.Password)
            self.form.addRow("Confirmação — administrador", self.w["cu"])
            self.form.addRow("Senha do administrador", self.w["cp"])
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self) -> None:
        w, d = self.w, {}
        if self.name == "payment":
            d["reference"] = w["reference"].text().strip()
            d["periods"] = w["periods"].value()
            try:
                d["amount_cents"] = int(round(float(w["amount"].text().replace(".", "").replace(",", ".") or 0) * 100))
            except ValueError:
                error(self, "Valor inválido.")
                return
            if "until" in w:
                d["new_paid_until"] = _iso_date(w["until"])
        elif self.name == "claim":
            d["note"] = w["note"].toPlainText().strip()
        elif self.name == "grace":
            d["days"] = w["days"].value()
        elif self.name in ("schedule-suspension", "suspend"):
            if "at" in w:
                d["at"] = _iso_date(w["at"])
            d["operational_ack"] = w["ack"].isChecked()
        elif self.name == "reactivate" and w["extend"].isChecked():
            d["extend_until"] = _iso_date(w["until"])
        if "reason" in w:
            d["reason"] = w["reason"].text().strip()
        if "cu" in w:
            d["confirmed_by"] = {"username": w["cu"].text().strip(), "password": w["cp"].text()}
        self.data = d
        self.accept()


class PolicyDialog(QDialog):
    def __init__(self, page) -> None:
        super().__init__(page)
        self.page = page
        self.setWindowTitle("Políticas comerciais")
        self.resize(640, 520)
        s = page.settings
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Valores gravados (assinados) nas novas licenças e usados na avaliação das assinaturas. "
                             "Devem ser compatíveis com o contrato comercial."))
        f = QFormLayout()
        self.sp = {}
        for k, label, lo, hi in (("warn_days", "Avisos começam (dias antes do vencimento)", 0, 60),
                                 ("grace_days", "Carência após o vencimento (dias)", 0, 60),
                                 ("max_grace_extension_days", "Prorrogação máxima por concessão (dias)", 1, 90),
                                 ("auth_ttl_days", "Validade de cada autorização online (dias)", 1, 90),
                                 ("online_tolerance_days", "Tolerância sem contato com o servidor (dias)", 0, 90)):
            sb = QSpinBox()
            sb.setRange(lo, hi)
            sb.setValue(int(s.get(k) or 0))
            self.sp[k] = sb
            f.addRow(label, sb)
        self.auto = QCheckBox("Suspender automaticamente ao fim da carência (somente se o contrato prevê)")
        self.auto.setChecked(s.get("auto_suspend") == "1")
        f.addRow("", self.auto)
        self.grace_roles = {}
        gr = QHBoxLayout()
        for r in ("admin", "financial", "support"):
            cb = QCheckBox(ROLES[r])
            cb.setChecked(r in s.get("grace_roles", ""))
            self.grace_roles[r] = cb
            gr.addWidget(cb)
        f.addRow("Podem conceder prorrogação", gr)
        self.confirm = {}
        cr = QHBoxLayout()
        for k, label in (("schedule_suspension", "Programar suspensão"), ("suspend", "Suspender"),
                         ("reactivate", "Reativar"), ("grace", "Prorrogar"), ("payment", "Pagamento")):
            cb = QCheckBox(label)
            cb.setChecked(k in s.get("confirm_actions", ""))
            self.confirm[k] = cb
            cr.addWidget(cb)
        f.addRow("Exigem confirmação de administrador", cr)
        self.url = QLineEdit(s.get("server_url") or "")
        self.url.setPlaceholderText("https://licencas.suaempresa.com.br:8743")
        self.pin = QLineEdit(s.get("server_pin") or "")
        self.pin.setPlaceholderText("SHA-256 do certificado (VYONIX_License_Server.exe pin)")
        f.addRow("License Server (licenças online)", self.url)
        f.addRow("Impressão digital do certificado", self.pin)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self) -> None:
        vals = {k: sb.value() for k, sb in self.sp.items()}
        vals["auto_suspend"] = self.auto.isChecked()
        vals["grace_roles"] = [r for r, cb in self.grace_roles.items() if cb.isChecked()]
        vals["confirm_actions"] = [k for k, cb in self.confirm.items() if cb.isChecked()]
        vals["server_url"] = self.url.text().strip()
        vals["server_pin"] = self.pin.text().strip().replace(":", "").lower()
        try:
            self.page.settings = self.page.backend.set_settings(vals)
        except Exception as exc:  # noqa: BLE001
            error(self, as_error(exc))
            return
        self.accept()


class ConnectDialog(QDialog):
    def __init__(self, page) -> None:
        super().__init__(page)
        self.backend = None
        self.setWindowTitle("Conectar ao VYONIX License Server")
        lay = QVBoxLayout(self)
        f = QFormLayout()
        s = page.w.lm.commercial.settings()
        self.url = QLineEdit(s.get("server_url") or "https://")
        self.pin = QLineEdit(s.get("server_pin") or "")
        self.user = QLineEdit(page.w.user.username)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        f.addRow("Endereço", self.url)
        f.addRow("Impressão digital (opcional)", self.pin)
        f.addRow("Usuário do servidor", self.user)
        f.addRow("Senha", self.pw)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self) -> None:
        try:
            b = RemoteCommercial(self.url.text(), pin=self.pin.text() or None)
            b.login(self.user.text().strip(), self.pw.text())
        except Exception as exc:  # noqa: BLE001
            error(self, as_error(exc))
            return
        self.backend = b
        self.accept()


class CommercialPage(Page):
    def __init__(self, w) -> None:
        super().__init__("Gestão Comercial", "Assinaturas por cliente e instalação: vencimentos, pagamentos "
                         "confirmados, avisos, carência, suspensão controlada e reativação. Medidas comerciais nunca "
                         "apagam, cifram ou bloqueiam os exames da clínica.")
        self.w = w
        self.backend = LocalCommercial(w.lm, w.user)
        self.settings = self.backend.settings()
        self.rows: list[dict] = []
        top = QHBoxLayout()
        self.source = QLabel("")
        top.addWidget(self.source, 1)
        top.addWidget(btn("Conectar ao License Server…", self.connect_server))
        top.addWidget(btn("Usar este License Manager", self.use_local))
        top.addWidget(btn("Políticas comerciais…", self.policies))
        self.lay.addLayout(top)
        grid = QGridLayout()
        self.kpi = {}
        for i, st in enumerate(("active", "due_soon", "overdue", "suspension_scheduled", "suspended", "expired",
                                "reactivated")):
            f = QFrame()
            f.setObjectName("card")
            fl = QVBoxLayout(f)
            n = QLabel("0")
            n.setObjectName("kpi")
            fl.addWidget(n)
            fl.addWidget(QLabel(STATE_LABELS[st]))
            self.kpi[st] = n
            grid.addWidget(f, 0, i)
        self.lay.addLayout(grid)
        flt = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por cliente, CNPJ, licença, instalação ou Hardware ID")
        self.search.returnPressed.connect(self.refresh)
        self.state = QComboBox()
        self.state.addItem("Todas as situações", None)
        for k, label in STATE_LABELS.items():
            self.state.addItem(label, k)
        self.state.currentIndexChanged.connect(lambda _: self.refresh())
        flt.addWidget(self.search, 1)
        flt.addWidget(self.state)
        self.lay.addLayout(flt)
        self.lay.addLayout(row(
            btn("Registrar pagamento…", lambda: self.act("payment"), "primary"),
            btn("Comprovante (não quita)…", lambda: self.act("claim")),
            btn("Conceder carência…", lambda: self.act("grace")),
            btn("Programar suspensão…", lambda: self.act("schedule-suspension")),
            btn("Cancelar suspensão…", lambda: self.act("cancel-suspension")),
            btn("Suspender…", lambda: self.act("suspend"), "danger"),
            btn("Reativar…", lambda: self.act("reactivate"))))
        self.lay.addLayout(row(
            btn("Emitir licença", lambda: self.w.go(self.w.page_index("Solicitações e emissão"))),
            btn("Renovar…", self.renew), btn("Reemitir (.vylic)…", self.reissue),
            btn("Exportar autorização offline (.vyauth)…", self.export_auth),
            btn("Publicar licença no servidor…", self.publish),
            btn("Plano e valor…", self.edit_plan),
            btn("Auditoria", self.audit)))
        self.t = table(["Cliente", "CNPJ", "Instalação", "Plano", "Mensalidade", "Vencimento", "Último pagamento",
                        "Dias de atraso", "Situação", "Validação", "Licença", "Último contato"])
        self.t.itemSelectionChanged.connect(self.show_detail)
        self.lay.addWidget(self.t, 2)
        self.tabs = QTabWidget()
        self.tab_tables = {}
        for key, label, cols in (
                ("history", "Histórico", ["Data", "Ação", "De", "Para", "Responsável", "Origem", "Motivo"]),
                ("notifications", "Notificações", ["Data", "Tipo", "Referência", "Mensagem"]),
                ("suspensions", "Suspensões", ["Data", "Ação", "De", "Para", "Responsável", "Motivo"]),
                ("reactivations", "Reativações", ["Data", "De", "Para", "Responsável", "Origem", "Motivo"]),
                ("payments", "Pagamentos", ["Confirmado em", "Referência", "Origem", "Valor", "Períodos",
                                            "Quitado até", "Por"]),
                ("charges", "Cobranças", ["Emitida", "Banco", "Código", "Valor", "Vencimento", "Situação"]),
                ("authorizations", "Autorizações", ["Emitida", "Canal", "Situação", "Válida até", "Por",
                                                    "Autorização"])):
            t = table(cols)
            self.tab_tables[key] = t
            self.tabs.addTab(t, label)
        self.lay.addWidget(self.tabs, 1)

    # ------------------------------------------------------------------ fonte de dados
    def connect_server(self) -> None:
        d = ConnectDialog(self)
        if d.exec() and d.backend:
            self.backend = d.backend
            self.settings = self.backend.settings()
            self.refresh()

    def use_local(self) -> None:
        if isinstance(self.backend, RemoteCommercial):
            self.backend.logout()
        self.backend = LocalCommercial(self.w.lm, self.w.user)
        self.settings = self.backend.settings()
        self.refresh()

    def policies(self) -> None:
        if PolicyDialog(self).exec():
            info(self, "Políticas salvas. Elas valem para as próximas licenças emitidas e para a avaliação das "
                       "assinaturas desta origem.")

    # ------------------------------------------------------------------ lista e detalhes
    def refresh(self) -> None:
        self.source.setText(f"Origem dos dados: <b>{self.backend.label}</b>")
        try:
            self.backend.evaluate()
            self.rows = self.backend.subscriptions(self.search.text().strip(), self.state.currentData())
            summ = self.backend.summary()
        except Exception as exc:  # noqa: BLE001
            error(self, as_error(exc))
            return
        for k, lbl in self.kpi.items():
            lbl.setText(str(summ.get(k, 0)))
        fill(self.t, [(r["customer_name"], r.get("customer_document") or "—", r["installation_id"],
                       r.get("plan_name") or r["plan_code"], money(r.get("price_cents")),
                       "sem vencimento" if r["permanent"] else when(r["paid_until"]), when(r.get("last_payment_at")),
                       r["days_overdue"] or "", r["state_label"], F.VALIDATION_MODES.get(r["validation"], "")[:7],
                       r["license_id"], when(r.get("last_contact_at"))) for r in self.rows],
             [r["id"] for r in self.rows])

    def _sel(self) -> dict | None:
        sid = selected(self.t)
        if sid is None:
            info(self, "Selecione uma assinatura.")
            return None
        return next((r for r in self.rows if r["id"] == sid), None)

    def show_detail(self) -> None:
        sid = selected(self.t)
        if sid is None:
            return
        try:
            d = self.backend.detail(sid)
        except Exception as exc:  # noqa: BLE001
            error(self, as_error(exc))
            return
        lab = lambda s: STATE_LABELS.get(s or "", s or "—")  # noqa: E731
        fill(self.tab_tables["history"], [(when(h["at"]), h.get("action_label") or h["action"], lab(h["from_state"]),
                                           lab(h["to_state"]), h["actor"], h["source"], h["reason"] or "")
                                          for h in d["history"]])
        fill(self.tab_tables["notifications"], [(when(n["at"]), n["kind"], when(n["ref"]) if "T" in n["ref"] else
                                                 n["ref"], n["message"]) for n in d["notifications"]])
        fill(self.tab_tables["suspensions"], [(when(h["at"]), h.get("action_label") or h["action"], lab(h["from_state"]),
                                               lab(h["to_state"]), h["actor"], h["reason"] or "")
                                              for h in d["suspensions"]])
        fill(self.tab_tables["reactivations"], [(when(h["at"]), lab(h["from_state"]), lab(h["to_state"]), h["actor"],
                                                 h["source"], h["reason"] or "") for h in d["reactivations"]])
        fill(self.tab_tables["payments"], [(when(p["confirmed_at"]), p["reference"], p["source"],
                                            money(p["amount_cents"]), p["periods"], when(p["new_paid_until"]),
                                            p["confirmed_by"]) for p in d["payments"]])
        fill(self.tab_tables["charges"], [(when(c["issued_at"]), c["provider"], c["provider_ref"],
                                           money(c["amount_cents"]), c["due_date"], c["provider_status"] or c["status"])
                                          for c in d["charges"]])
        fill(self.tab_tables["authorizations"], [(when(a["issued_at"]), a["channel"], lab(a["state"]),
                                                  when(a["valid_until"]), a["actor"], a["authorization_id"])
                                                 for a in d["authorizations"]])

    # ------------------------------------------------------------------ ações
    def act(self, name: str) -> None:
        sub = self._sel()
        if not sub:
            return
        dlg = ActionDialog(self, sub, name)
        if not dlg.exec() or dlg.data is None:
            return
        try:
            r = self.backend.action(sub["id"], name, dlg.data)
        except Exception as exc:  # noqa: BLE001
            error(self, as_error(exc))
            return
        if name == "payment" and r.get("duplicate"):
            info(self, "Este pagamento (mesma referência) já estava registrado: nada foi alterado.")
        elif name == "payment" and r.get("reactivated"):
            info(self, "Pagamento confirmado: assinatura REATIVADA. Clientes online recebem a autorização na próxima "
                       "consulta; clientes offline precisam do arquivo de autorização (.vyauth).")
        self.refresh()

    def edit_plan(self) -> None:
        sub = self._sel()
        if not sub:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Plano e valor")
        f = QFormLayout(dlg)
        plan = QComboBox()
        for p in self.backend.plans():
            plan.addItem(p["name"], p["code"])
        plan.setCurrentIndex(max(0, plan.findData(sub["plan_code"])))
        price = QLineEdit(f"{(sub.get('price_cents') or 0) / 100:.2f}".replace(".", ","))
        doc = QLineEdit(sub.get("customer_document") or "")
        allows = QCheckBox("O contrato prevê suspensão por inadimplência")
        allows.setChecked(bool(sub.get("contract_allows_suspension")))
        auto = QCheckBox("Suspensão automática ao fim da carência")
        auto.setChecked(bool(sub.get("auto_suspend")))
        notes = QLineEdit(sub.get("operational_notes") or "")
        f.addRow("Plano", plan)
        f.addRow("Mensalidade (R$)", price)
        f.addRow("CNPJ", doc)
        f.addRow("", allows)
        f.addRow("", auto)
        f.addRow("Requisitos operacionais", notes)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if not dlg.exec():
            return
        try:
            cents = int(round(float(price.text().replace(".", "").replace(",", ".") or 0) * 100))
            self.backend.action(sub["id"], "edit", {"fields": {
                "plan_code": plan.currentData(), "price_cents": cents, "customer_document": doc.text().strip() or None,
                "contract_allows_suspension": allows.isChecked(), "auto_suspend": auto.isChecked(),
                "operational_notes": notes.text().strip() or None}})
        except Exception as exc:  # noqa: BLE001
            error(self, as_error(exc))
            return
        self.refresh()

    def _local_license(self, sub: dict) -> dict | None:
        try:
            return self.w.lm.license(sub["license_id"])
        except Exception:  # noqa: BLE001
            error(self, "A licença desta assinatura não está neste License Manager.")
            return None

    def renew(self) -> None:
        sub = self._sel()
        lic = self._local_license(sub) if sub else None
        if lic:
            from license_manager.ui.dialogs import RenewDialog
            if RenewDialog(self.w.lm, self.w.user, lic, self).exec():
                self.refresh()

    def reissue(self) -> None:
        sub = self._sel()
        lic = self._local_license(sub) if sub else None
        if lic:
            from license_manager.ui.dialogs import save_document
            save_document(self, self.w.lm, self.w.user, lic)

    def export_auth(self) -> None:
        sub = self._sel()
        if not sub:
            return
        if isinstance(self.backend, LocalCommercial):
            from license_manager.ui.main import ensure_unlocked
            if not ensure_unlocked(self, self.w.lm, self.w.user):
                return
        try:
            doc = self.backend.action(sub["id"], "offline-authorization", {})["document"]
        except Exception as exc:  # noqa: BLE001
            error(self, as_error(exc))
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salvar autorização offline",
                                              str(self.w.lm.paths.exports_dir / f"{sub['license_id']}.vyauth"),
                                              "Autorização VYONIX (*.vyauth)")
        if path:
            Path(path).write_text(doc, encoding="utf-8")
            info(self, f"Autorização salva em\n{path}\n\nNo VYONIX DICOM Print do cliente: Licença → Importar "
                       "autorização / renovação.")
        self.refresh()

    def publish(self) -> None:
        if not isinstance(self.backend, RemoteCommercial):
            info(self, "Conecte-se ao License Server para publicar licenças online.")
            return
        lid, ok = _ask_license(self, self.w.lm)
        if not ok:
            return
        try:
            lic = self.w.lm.license(lid)
            cust = self.w.lm.customer(lic["customer_id"])
            sub = self.w.lm.commercial.find(lid)
            r = self.backend.register_license(lic["document"], plan_code=lic["type"],
                                              price_cents=sub["price_cents"] if sub else None,
                                              customer_document=cust.get("document"))
        except Exception as exc:  # noqa: BLE001
            error(self, as_error(exc))
            return
        info(self, f"Licença {lid} registrada no License Server: assinatura {r['state_label']}."
             + (f"\n{r['warning']}" if r.get("warning") else ""))
        self.refresh()

    def audit(self) -> None:
        if isinstance(self.backend, RemoteCommercial):
            try:
                a = self.backend.audit()
            except Exception as exc:  # noqa: BLE001
                error(self, as_error(exc))
                return
            dlg = QDialog(self)
            dlg.setWindowTitle("Auditoria do License Server" + ("" if a.get("chain_ok") else " — CADEIA ALTERADA"))
            dlg.resize(960, 560)
            lay = QVBoxLayout(dlg)
            t = table(["Data", "Usuário", "Ação", "Alvo", "IP", "Detalhes"])
            fill(t, [(when(x["at"]), x["actor"], x["action"], x["target"] or "", x["ip"] or "", x["details"] or "")
                     for x in a["items"]])
            lay.addWidget(t)
            dlg.exec()
        else:
            self.w.go(self.w.page_index("Histórico e auditoria"))


def _ask_license(parent, lm) -> tuple[str, bool]:
    from PySide6.QtWidgets import QInputDialog
    items = [f"{x['license_id']} — {x['customer']} ({x['type_label']})" for x in lm.licenses(status="active")
             if x["type"] != "demo"]
    if not items:
        info(parent, "Nenhuma licença comercial ativa neste License Manager.")
        return "", False
    text, ok = QInputDialog.getItem(parent, "Publicar no License Server", "Licença:", items, 0, False)
    return text.split(" — ")[0], ok


__all__ = ["CommercialPage", "ActionDialog", "PolicyDialog", "confirm"]
