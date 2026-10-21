"""Janela principal do VYONIX License Manager."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
                               QPlainTextEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from vyonix_protocol import formats as F

from license_manager import APP_NAME, __version__
from license_manager.security import ROLES
from license_manager.service import LicenseManager, LMError
from license_manager.ui.common import (STYLE, Page, ask_secret, btn, confirm, error, fill, info, row, selected,
                                       table, when)
from license_manager.ui.commercial_page import CommercialPage
from license_manager.ui.dialogs import (CustomerDialog, IssueDialog, LoginDialog, ReactivateDialog, RenewDialog,
                                        SetupDialog, import_request_text, request_summary)

IDLE_MINUTES = 15
STATUS = {"active": "ativa", "superseded": "substituída (renovada)", "replaced": "substituída (reativação)",
          "revoked": "REVOGADA"}


def ensure_unlocked(parent, lm: LicenseManager, user) -> bool:
    if lm.key_unlocked():
        return True
    key = lm.active_key()
    if key is None:
        error(parent, "Nenhuma chave de emissão ativa. Gere ou importe uma em Segurança.")
        return False
    pw = ask_secret(parent, "Chave de emissão", f"Frase-senha da chave {key['key_id']} (fica desbloqueada por 15 min):")
    if not pw:
        return False
    try:
        lm.unlock_key(user, pw)
    except LMError as exc:
        error(parent, exc)
        return False
    return True


# ---------------------------------------------------------------------------- páginas
class DashboardPage(Page):
    def __init__(self, w) -> None:
        super().__init__("Painel", "Visão geral das licenças emitidas por este License Manager.")
        self.w = w
        self.grid = QGridLayout()
        self.kpis = {}
        for i, (k, label) in enumerate((("customers", "Clientes"), ("licenses_active", "Licenças comerciais ativas"),
                                        ("expiring_30", "Vencem em 30 dias"), ("expired", "Vencidas"),
                                        ("permanent", "Permanentes"), ("demos", "DEMO assinadas"),
                                        ("revoked", "Revogadas"), ("requests_pending", "Solicitações sem licença"))):
            f = QFrame()
            f.setObjectName("card")
            fl = QVBoxLayout(f)
            v = QLabel("—")
            v.setObjectName("kpi")
            fl.addWidget(v)
            fl.addWidget(QLabel(label))
            self.kpis[k] = v
            self.grid.addWidget(f, i // 4, i % 4)
        self.lay.addLayout(self.grid)
        self.key = QLabel("")
        self.key.setObjectName("banner")
        self.key.setWordWrap(True)
        self.lay.addWidget(self.key)
        self.lay.addWidget(QLabel("<b>Licenças que vencem nos próximos 30 dias</b>"))
        self.exp = table(["Licença", "Cliente", "Tipo", "Vencimento", "Hardware ID"])
        self.lay.addWidget(self.exp, 1)
        self.lay.addWidget(QLabel("<b>Atividade recente</b>"))
        self.recent = table(["Data/hora", "Usuário", "Ação", "Alvo"])
        self.lay.addWidget(self.recent, 1)

    def refresh(self) -> None:
        d = self.w.lm.dashboard()
        for k, lbl in self.kpis.items():
            lbl.setText(str(d[k]))
        k = d["key"]
        if k:
            from vyonix_protocol.crypto import fingerprint
            self.key.setText(f"Chave de emissão ativa: <b>{k['key_id']}</b> ({fingerprint(k['public_hex'])}) — "
                             + ("desbloqueada" if self.w.lm.key_unlocked() else "bloqueada (pede a frase-senha ao emitir)")
                             + (" · Auditoria íntegra" if d["audit_ok"] else " · <b>AUDITORIA COM REGISTROS ALTERADOS</b>"))
            self.key.setProperty("state", "ok" if d["audit_ok"] else "err")
        else:
            self.key.setText("Nenhuma chave de emissão ativa: gere ou importe uma em Segurança antes de emitir.")
            self.key.setProperty("state", "warn")
        self.key.style().polish(self.key)
        fill(self.exp, [(x["license_id"], x["customer"], x["type_label"], when(x["expires_at"]), x["hardware_id"])
                        for x in d["expiring"]])
        fill(self.recent, [(when(a["at"]), a["actor"], a["action"], a["target"] or "") for a in d["recent"]])


class CustomersPage(Page):
    def __init__(self, w) -> None:
        super().__init__("Clientes", "Cadastro de clientes e histórico de instalações, licenças e reativações.")
        self.w = w
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por nome, CNPJ/CPF, cidade ou e-mail")
        self.search.returnPressed.connect(self.refresh)
        self.lay.addWidget(self.search)
        self.lay.addLayout(row(btn("Novo cliente", self.new, "primary"), btn("Editar", self.edit),
                               btn("Histórico do cliente", self.history), btn("Anonimizar (LGPD)", self.anon, "danger")))
        self.t = table(["Nome", "CNPJ/CPF", "Cidade/UF", "E-mail", "Telefone", "Licenças ativas"])
        self.t.doubleClicked.connect(lambda _: self.history())
        self.lay.addWidget(self.t, 1)

    def refresh(self) -> None:
        cs = self.w.lm.customers(self.search.text().strip())
        fill(self.t, [(c["name"], c["document"], "/".join(x for x in (c["city"], c["state"]) if x), c["email"],
                       c["phone"], c["active_licenses"]) for c in cs], [c["id"] for c in cs])

    def new(self) -> None:
        if CustomerDialog(self.w.lm, self.w.user, parent=self).exec():
            self.refresh()

    def edit(self) -> None:
        cid = selected(self.t)
        if cid and CustomerDialog(self.w.lm, self.w.user, cid, parent=self).exec():
            self.refresh()

    def anon(self) -> None:
        cid = selected(self.t)
        if cid and confirm(self, "Remover definitivamente os dados pessoais deste cliente? O histórico técnico das "
                                 "licenças é mantido sem identificação."):
            try:
                self.w.lm.anonymize_customer(self.w.user, cid)
            except Exception as exc:  # noqa: BLE001
                error(self, exc)
            self.refresh()

    def history(self) -> None:
        cid = selected(self.t)
        if not cid:
            return
        h = self.w.lm.customer_history(cid)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Histórico — {self.w.lm.customer(cid)['name']}")
        dlg.resize(1100, 640)
        lay = QVBoxLayout(dlg)
        for title, rows, headers in (
                ("Licenças emitidas", [(x["license_id"], x["operation"], F.LICENSE_TYPES[x["type"]][0], x["edition"],
                                        STATUS.get(x["status"], x["status"]), when(x["issued_at"]),
                                        when(x["expires_at"]), x["reissue_of"] or "", x["hardware_id"],
                                        x["installation_id"]) for x in h["licenses"]],
                 ["Licença", "Operação", "Tipo", "Edição", "Situação", "Emitida", "Vence", "Reemissão de", "Hardware ID",
                  "Installation ID"]),
                ("Instalações conhecidas", [(x["hardware_id"], x["installation_id"], when(x["first_seen"]),
                                             x["last_license_id"]) for x in h["installations"]],
                 ["Hardware ID", "Installation ID", "Primeira emissão", "Última licença"]),
                ("Reativações", [(when(x["at"]), x["old_license_id"], x["new_license_id"],
                                  F.REACTIVATION_REASONS.get(x["reason_code"], x["reason_code"]), x["reason_text"],
                                  x["actor"]) for x in h["reactivations"]],
                 ["Data", "Licença anterior", "Nova licença", "Motivo", "Descrição", "Por"])):
            lay.addWidget(QLabel(f"<b>{title}</b>"))
            t = table(headers)
            fill(t, rows)
            lay.addWidget(t, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.exec()


class ProductsPage(Page):
    def __init__(self, w) -> None:
        super().__init__("Produtos", "Produtos, edições, recursos e limites padrão usados na emissão.")
        self.w = w
        self.t = table(["Produto", "Nome", "Edições", "Recursos", "Equipamentos (padrão)", "Impressoras (padrão)"])
        self.lay.addWidget(self.t, 1)
        self.lay.addLayout(row(btn("Editar produto", self.edit)))

    def refresh(self) -> None:
        ps = self.w.lm.products()
        fill(self.t, [(p["product_id"], p["name"], ", ".join(p["editions"]),
                       ", ".join(F.FEATURE_LABELS[f] for f in p["features"]), p["default_max_devices"] or "sem limite",
                       p["default_max_printers"] or "sem limite") for p in ps], [p["product_id"] for p in ps])

    def edit(self) -> None:
        pid = selected(self.t) or F.PRODUCT_ID
        p = self.w.lm.product(pid)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Produto {pid}")
        form = QFormLayout(dlg)
        name = QLineEdit(p["name"])
        eds = QLineEdit(", ".join(p["editions"]))
        feats = {f: QCheckBox(F.FEATURE_LABELS[f]) for f in F.FEATURES}
        for f, cb in feats.items():
            cb.setChecked(f in p["features"])
        from PySide6.QtWidgets import QSpinBox
        dev, prn = QSpinBox(), QSpinBox()
        for sb, v in ((dev, p["default_max_devices"]), (prn, p["default_max_printers"])):
            sb.setRange(0, 999)
            sb.setSpecialValueText("sem limite")
            sb.setValue(int(v or 0))
        form.addRow("Nome", name)
        form.addRow("Edições (separadas por vírgula)", eds)
        fl = QHBoxLayout()
        for cb in feats.values():
            fl.addWidget(cb)
        form.addRow("Recursos padrão", fl)
        form.addRow("Equipamentos (padrão)", dev)
        form.addRow("Impressoras (padrão)", prn)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec():
            try:
                self.w.lm.save_product(self.w.user, pid, name.text().strip(),
                                       [e.strip() for e in eds.text().split(",") if e.strip()],
                                       [f for f, cb in feats.items() if cb.isChecked()], dev.value() or None,
                                       prn.value() or None)
            except Exception as exc:  # noqa: BLE001
                error(self, exc)
            self.refresh()


class IssuePage(Page):
    def __init__(self, w) -> None:
        super().__init__("Solicitações e emissão",
                         "Fluxo offline: importe a solicitação exportada pelo VYONIX DICOM Print, selecione cliente, "
                         "validade e recursos, emita a licença assinada e envie o arquivo .vylic ao cliente.")
        self.w = w
        self.lay.addLayout(row(btn("Importar solicitação e emitir licença…", self.import_issue, "primary"),
                               btn("Emitir para a solicitação selecionada", self.issue_selected)))
        self.t = table(["Recebida", "Hardware ID", "Installation ID", "Unidade", "Motivo", "TPM", "Cliente", "Versão"])
        self.lay.addWidget(self.t, 1)

    def refresh(self) -> None:
        rs = self.w.lm.requests()
        fill(self.t, [(when(r["imported_at"]), r["hardware_id"], r["installation_id"], r["site"],
                       F.REACTIVATION_REASONS.get(r["reason"] or "", "primeira ativação"), r["tpm_status"],
                       r["customer"] or "—", r["app_version"]) for r in rs], [r["request_id"] for r in rs])

    def _issue(self, text: str) -> None:
        try:
            req = self.w.lm.import_request(self.w.user, text)
        except LMError as exc:
            error(self, exc)
            return
        if req.tpm_status == "invalid" and not confirm(self, "A assinatura do TPM desta solicitação é INVÁLIDA "
                                                             "(possível adulteração). Continuar mesmo assim?"):
            return
        if IssueDialog(self.w.lm, self.w.user, req, self).exec():
            self.w.refresh_all()
        else:
            self.refresh()

    def import_issue(self) -> None:
        text = import_request_text(self)
        if text:
            self._issue(text)

    def issue_selected(self) -> None:
        rid = selected(self.t)
        if rid:
            self._issue(F.encode_request(self.w.lm.request_data(rid)))


class LicensesPage(Page):
    def __init__(self, w) -> None:
        super().__init__("Licenças", "Renovação, reativação, revogação administrativa e exportação dos arquivos "
                         "assinados.")
        self.w = w
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por licença, cliente, Hardware ID ou Installation ID")
        self.search.returnPressed.connect(self.refresh)
        self.status = QComboBox()
        for k, label in ((None, "Todas"), ("active", "Ativas"), ("superseded", "Renovadas"), ("replaced", "Reativadas"),
                         ("revoked", "Revogadas")):
            self.status.addItem(label, k)
        self.status.currentIndexChanged.connect(lambda _: self.refresh())
        top.addWidget(self.search, 1)
        top.addWidget(self.status)
        self.lay.addLayout(top)
        self.lay.addLayout(row(btn("Detalhes", self.details), btn("Exportar .vylic…", self.export),
                               btn("Renovar…", self.renew), btn("REATIVAR / EMITIR NOVA LICENÇA…", self.reactivate,
                                                               "primary"),
                               btn("Revogar…", self.revoke, "danger"),
                               btn("Gerar lista de revogação…", self.revocation_list)))
        self.t = table(["Licença", "Cliente", "Tipo", "Edição", "Situação", "Emitida", "Início", "Vencimento",
                        "Equip.", "Impr.", "Hardware ID", "Installation ID", "Chave"])
        self.t.doubleClicked.connect(lambda _: self.details())
        self.lay.addWidget(self.t, 1)

    def refresh(self) -> None:
        ls = self.w.lm.licenses(status=self.status.currentData(), search=self.search.text().strip())
        fill(self.t, [(x["license_id"], x["customer"], x["type_label"], x["edition"],
                       ("VENCIDA" if x["expired"] and x["status"] == "active" else STATUS.get(x["status"], x["status"])),
                       when(x["issued_at"]), when(x["starts_at"]),
                       "120 h após ativar" if x["type"] == "demo" else (when(x["expires_at"]) if x["expires_at"]
                                                                       else "sem vencimento"),
                       x["max_devices"] or "∞", x["max_printers"] or "∞", x["hardware_id"], x["installation_id"],
                       x["key_id"]) for x in ls], [x["license_id"] for x in ls])

    def _sel(self) -> dict | None:
        lid = selected(self.t)
        if not lid:
            info(self, "Selecione uma licença.")
            return None
        return self.w.lm.license(lid)

    def details(self) -> None:
        x = self._sel()
        if not x:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(x["license_id"])
        dlg.resize(760, 560)
        lay = QVBoxLayout(dlg)
        txt = QLabel(
            f"<b>{x['license_id']}</b> — {x['customer']}<br>{x['type_label']} · edição {x['edition']} · "
            f"{STATUS.get(x['status'], x['status'])}<br>Emitida em {when(x['issued_at'])} por {x['created_by']} "
            f"(chave {x['key_id']}) · início {when(x['starts_at'])} · vencimento {when(x['expires_at'])}<br>"
            f"Hardware ID {x['hardware_id']}<br>Installation ID {x['installation_id']}<br>"
            f"Recursos: {', '.join(F.FEATURE_LABELS[f] for f in x['features'])}<br>"
            f"Equipamentos: {x['max_devices'] or 'sem limite'} · impressoras: {x['max_printers'] or 'sem limite'}<br>"
            f"Operação: {x['operation']}" + (f" · reemissão de {x['reissue_of']}" if x["reissue_of"] else "")
            + (f" · motivo: {F.REACTIVATION_REASONS.get(x['reason_code'] or '', x['reason_code'])} — {x['reason_text']}"
               if x["reason_code"] else "")
            + (f"<br>Revogada em {when(x['revoked_at'])}: {x['revoked_reason']}" if x["revoked_at"] else "")
            + (f"<br>Observações: {x['notes']}" if x["notes"] else ""))
        txt.setWordWrap(True)
        txt.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(txt)
        comps = table(["Componente autorizado", "Considerado"])
        fill(comps, [(F.HW_LABELS[c], "sim" if x["hw"].get(c) else "não") for c in (*F.HW_STRONG, "mac")])
        lay.addWidget(comps, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.exec()

    def export(self) -> None:
        x = self._sel()
        if x:
            from license_manager.ui.dialogs import save_document
            save_document(self, self.w.lm, self.w.user, x)

    def renew(self) -> None:
        x = self._sel()
        if x and RenewDialog(self.w.lm, self.w.user, x, self).exec():
            self.w.refresh_all()

    def reactivate(self) -> None:
        x = self._sel()
        if x and ReactivateDialog(self.w.lm, self.w.user, x, self).exec():
            self.w.refresh_all()

    def revoke(self) -> None:
        x = self._sel()
        if not x:
            return
        reason, ok = QInputDialog.getText(self, "Revogar licença", f"Motivo da revogação de {x['license_id']}:")
        if not ok or not reason.strip():
            return
        try:
            self.w.lm.revoke(self.w.user, x["license_id"], reason)
        except Exception as exc:  # noqa: BLE001
            error(self, exc)
            return
        info(self, "Licença revogada no cadastro. Para que o computador do cliente a recuse, gere a lista de "
                   "revogação e instale-a no VYONIX DICOM Print (Licença → Importar lista de revogação). Sem isso, "
                   "uma licença offline continua valendo até o vencimento.")
        self.refresh()

    def revocation_list(self) -> None:
        if not ensure_unlocked(self, self.w.lm, self.w.user):
            return
        try:
            rl = self.w.lm.revocation_list(self.w.user)
        except Exception as exc:  # noqa: BLE001
            error(self, exc)
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salvar lista de revogação",
                                              str(self.w.lm.paths.exports_dir / f"VYONIX-revogacao-{rl['seq']}.vyrevoke"),
                                              "Lista de revogação (*.vyrevoke)")
        if path:
            Path(path).write_text(rl["document"], encoding="utf-8")
            info(self, f"Lista nº {rl['seq']} com {rl['count']} licença(s) salva em\n{path}")


class RevalidationPage(Page):
    def __init__(self, w) -> None:
        super().__init__("Revalidação administrativa",
                         "Quando o VYONIX DICOM Print suspende as funções por data/hora inconsistente ou registros de "
                         "ativação alterados, o cliente exporta um diagnóstico. Analise-o e, se legítimo, emita a "
                         "revalidação assinada (redefine o horário confiável; não devolve tempo de licença ou DEMO).")
        self.w = w
        self.diag_text = None
        self.lay.addLayout(row(btn("Abrir diagnóstico…", self.open_diag, "primary")))
        self.summary = QLabel("Nenhum diagnóstico aberto.")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lay.addWidget(self.summary)
        self.hist = table(["Data/hora", "Evento", "Diferença", "Detalhe"])
        self.lay.addWidget(self.hist, 1)
        form = QFormLayout()
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Ex.: bateria da BIOS trocada; relógio voltou a 2010")
        self.act_time = QCheckBox("Redefinir o horário confiável")
        self.act_time.setChecked(True)
        self.act_int = QCheckBox("Aceitar o estado atual dos registros de ativação (integridade)")
        form.addRow("Motivo *", self.reason)
        form.addRow("", self.act_time)
        form.addRow("", self.act_int)
        self.lay.addLayout(form)
        self.lay.addLayout(row(btn("Emitir revalidação assinada…", self.emit, "primary")))

    def open_diag(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Diagnóstico", "", "Diagnóstico (*.json);;Todos (*)")
        if not path:
            return
        text = Path(path).read_text(encoding="utf-8")
        try:
            d = self.w.lm.read_diagnostic(text)
        except LMError as exc:
            error(self, exc)
            return
        self.diag_text = text
        t = d.get("time") or {}
        st = d.get("status") or {}
        self.summary.setText(
            f"<b>Hardware ID:</b> {d['hardware_id']} · <b>Installation ID:</b> {d['installation_id']}<br>"
            f"<b>Situação:</b> {st.get('state')} — {st.get('message')}<br>"
            f"<b>Relógio do computador:</b> {when(t.get('wall'))} · <b>horário confiável:</b> {when(t.get('trusted'))}"
            f" · <b>problema:</b> {t.get('issue') or 'nenhum'}<br><b>Integridade:</b> "
            f"{'; '.join(d.get('integrity') or []) or 'sem alterações detectadas'}<br>"
            f"Gerado em {when(d.get('generated_at'))} · versão {d.get('app_version')}")
        fill(self.hist, [(when(h.get("at")), h.get("kind"), f"{(h.get('delta_s') or 0) / 3600:+.2f} h",
                          h.get("detail") or "") for h in d.get("time_history") or []])
        self.act_int.setChecked(bool(d.get("integrity")))

    def emit(self) -> None:
        if not self.diag_text:
            error(self, "Abra o diagnóstico enviado pelo cliente.")
            return
        if not ensure_unlocked(self, self.w.lm, self.w.user):
            return
        actions = (["time"] if self.act_time.isChecked() else []) + (["integrity"] if self.act_int.isChecked() else [])
        try:
            rv = self.w.lm.revalidate(self.w.user, self.diag_text, reason=self.reason.text(), actions=actions)
        except LMError as exc:
            error(self, exc)
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salvar revalidação",
                                              str(self.w.lm.paths.exports_dir / f"VYONIX-revalidacao-{rv['request_id']}"
                                                                               ".vyreval"), "Revalidação (*.vyreval)")
        if path:
            Path(path).write_text(rv["document"], encoding="utf-8")
            info(self, f"Revalidação salva em\n{path}\n\nO cliente a importa em Licença → Importar revalidação.")


class AuditPage(Page):
    def __init__(self, w) -> None:
        super().__init__("Histórico e auditoria",
                         "Todas as operações (emissões, reativações, revogações, chaves, usuários, backups). Cada "
                         "registro contém o resumo do anterior: alterações fora do aplicativo são detectadas.")
        self.w = w
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar")
        self.search.returnPressed.connect(self.refresh)
        self.lay.addWidget(self.search)
        self.state = QLabel("")
        self.state.setObjectName("banner")
        self.lay.addWidget(self.state)
        self.t = table(["Data/hora", "Usuário", "Ação", "Alvo", "Detalhes"])
        self.lay.addWidget(self.t, 1)
        self.lay.addLayout(row(btn("Verificar integridade da auditoria", self.verify), btn("Exportar (JSON)…",
                                                                                         self.export)))

    def refresh(self) -> None:
        rows = self.w.lm.audit_log(1000, self.search.text().strip())
        fill(self.t, [(when(a["at"]), a["actor"], a["action"], a["target"] or "", a["details"]) for a in rows])
        self.verify(quiet=True)

    def verify(self, quiet: bool = False) -> None:
        bad = self.w.lm.verify_audit()
        self.state.setText("Cadeia de auditoria íntegra." if not bad else
                           f"ATENÇÃO: {len(bad)} registro(s) alterado(s) ou removido(s) fora do aplicativo (IDs "
                           f"{', '.join(map(str, bad[:20]))}).")
        self.state.setProperty("state", "ok" if not bad else "err")
        self.state.style().polish(self.state)

    def export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar auditoria", str(self.w.lm.paths.exports_dir /
                                                                           "auditoria.json"), "JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(self.w.lm.audit_log(100000), ensure_ascii=False, indent=2),
                                  encoding="utf-8")


class BackupPage(Page):
    def __init__(self, w) -> None:
        super().__init__("Backup e restauração",
                         "O backup protegido contém o banco inteiro (clientes, licenças, chaves cifradas, auditoria) "
                         "cifrado com AES-256-GCM e uma frase-senha. Guarde-o fora deste computador.")
        self.w = w
        self.lay.addLayout(row(btn("Fazer backup protegido…", self.backup, "primary"), btn("Restaurar backup…",
                                                                                           self.restore, "danger"),
                               btn("Abrir pasta de dados", self.open_folder)))
        self.state = QLabel("")
        self.state.setWordWrap(True)
        self.lay.addWidget(self.state)
        self.lay.addStretch(1)

    def refresh(self) -> None:
        autos = sorted((self.w.lm.paths.backups_dir / "automaticos").glob("*.db"))
        self.state.setText(f"Pasta de dados: {self.w.lm.paths.root} (modo {self.w.lm.paths.mode})<br>"
                           f"Cópias automáticas diárias (locais, não cifradas, mesma proteção do banco): {len(autos)}"
                           + (f" — última {autos[-1].name}" if autos else ""))

    def backup(self) -> None:
        pw = ask_secret(self, "Backup protegido", "Frase-senha do backup (mín. 10 caracteres):")
        if not pw:
            return
        if ask_secret(self, "Backup protegido", "Repita a frase-senha:") != pw:
            error(self, "As frases-senha não conferem.")
            return
        from datetime import datetime
        path, _ = QFileDialog.getSaveFileName(self, "Salvar backup", str(self.w.lm.paths.backups_dir /
                                                                       f"license_manager-{datetime.now():%Y%m%d-%H%M}.vylmbak"),
                                              "Backup do License Manager (*.vylmbak)")
        if not path:
            return
        try:
            self.w.lm.backup(self.w.user, Path(path), pw)
        except Exception as exc:  # noqa: BLE001
            error(self, exc)
            return
        info(self, f"Backup protegido criado:\n{path}")

    def restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Restaurar backup", str(self.w.lm.paths.backups_dir),
                                              "Backup do License Manager (*.vylmbak)")
        if not path:
            return
        pw = ask_secret(self, "Restaurar", "Frase-senha do backup:")
        if not pw or not confirm(self, "Substituir TODOS os dados atuais pelos do backup? O banco atual é guardado "
                                       "na pasta de backups antes da troca."):
            return
        try:
            h = self.w.lm.restore(self.w.user, Path(path), pw)
        except Exception as exc:  # noqa: BLE001
            error(self, exc)
            return
        info(self, f"Backup de {h.get('created_at')} restaurado. Entre novamente.")
        self.w.relogin()

    def open_folder(self) -> None:
        if hasattr(os, "startfile"):
            os.startfile(str(self.w.lm.paths.root))  # noqa: S606
        else:
            info(self, str(self.w.lm.paths.root))


class SecurityPage(Page):
    def __init__(self, w) -> None:
        super().__init__("Segurança", "Chaves de emissão (Ed25519, cifradas com frase-senha; nunca gravadas em claro), "
                         "rotação de chaves e usuários com papéis.")
        self.w = w
        self.lay.addWidget(QLabel("<b>Chaves de emissão</b>"))
        self.keys = table(["Chave", "Situação", "Impressão digital", "Origem", "Criada", "Licenças", "Observação"])
        self.lay.addWidget(self.keys, 1)
        self.lay.addLayout(row(btn("Gerar nova chave…", self.gen), btn("Importar chave (.pem cifrado)…", self.imp),
                               btn("Tornar ativa", lambda: self.status("active")), btn("Aposentar",
                                                                                       lambda: self.status("retired")),
                               btn("Exportar chave pública…", self.export_pub),
                               btn("Backup protegido da chave…", self.backup_key),
                               btn("Alterar frase-senha…", self.change_pass), btn("Bloquear agora", self.lock)))
        note = QLabel("Rotação: a chave nova só é aceita pelo VYONIX DICOM Print depois de ser incluída na lista de "
                      "chaves públicas do produto e distribuída em uma atualização oficial (use “Exportar chave "
                      "pública”). Mantenha a chave anterior ativa até lá; aposentá-la não invalida licenças já emitidas.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        self.lay.addWidget(note)
        self.lay.addWidget(QLabel("<b>Usuários</b>"))
        self.users = table(["Usuário", "Nome", "Papel", "Ativo", "Último acesso"])
        self.lay.addWidget(self.users, 1)
        self.lay.addLayout(row(btn("Novo usuário…", self.new_user), btn("Alterar papel…", self.role),
                               btn("Ativar/desativar", self.toggle), btn("Redefinir senha…", self.reset),
                               btn("Minha senha…", self.my_password)))

    def refresh(self) -> None:
        ks = self.w.lm.keys()
        fill(self.keys, [(k["key_id"], {"active": "ATIVA", "standby": "reserva", "retired": "aposentada"}[k["status"]],
                          k["fingerprint"], k["origin"], when(k["created_at"]), k["licenses"], k["note"] or "")
                         for k in ks], [k["key_id"] for k in ks])
        us = self.w.lm.users() if self.w.user.can("users") else []
        fill(self.users, [(u["username"], u["display_name"], ROLES[u["role"]], "sim" if u["active"] else "não",
                           when(u["last_login_at"])) for u in us], [u["id"] for u in us])

    def _try(self, fn) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            error(self, exc)
        self.refresh()

    def _passphrase(self, title: str) -> str | None:
        p1 = ask_secret(self, title, "Frase-senha da chave (mín. 10 caracteres; não pode ser recuperada):")
        if not p1:
            return None
        if ask_secret(self, title, "Repita a frase-senha:") != p1:
            error(self, "As frases-senha não conferem.")
            return None
        return p1

    def gen(self) -> None:
        kid, ok = QInputDialog.getText(self, "Nova chave", "Identificador da chave (ex.: vyx-2027-01):")
        if not ok or not kid.strip():
            return
        pw = self._passphrase("Nova chave")
        if pw:
            self._try(lambda: info(self, "Chave criada: {key_id} ({fingerprint}) — situação {status}.".format(
                **self.w.lm.generate_key(self.w.user, kid, pw))))

    def imp(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar chave", "", "Chave PEM cifrada (*.pem);;Todos (*)")
        if not path:
            return
        kid, ok = QInputDialog.getText(self, "Importar chave", "Identificador da chave (igual ao do VYONIX DICOM Print):",
                                       text=Path(path).stem.replace(".private", ""))
        if not ok:
            return
        pw = ask_secret(self, "Importar chave", "Frase-senha da chave:")
        if pw:
            self._try(lambda: info(self, "Chave importada: {key_id} ({fingerprint}) — situação {status}.".format(
                **self.w.lm.import_key(self.w.user, kid, Path(path).read_bytes(), pw))))

    def status(self, st: str) -> None:
        kid = selected(self.keys)
        if kid and confirm(self, f"{'Ativar' if st == 'active' else 'Aposentar'} a chave {kid}?"):
            self._try(lambda: self.w.lm.set_key_status(self.w.user, kid, st))

    def export_pub(self) -> None:
        kid = selected(self.keys)
        if not kid:
            return
        line = self.w.lm.export_public_line(kid)
        QApplication.clipboard().setText(line)
        path, _ = QFileDialog.getSaveFileName(self, "Exportar chave pública", str(self.w.lm.paths.exports_dir /
                                                                               f"{kid}.public.txt"), "Texto (*.txt)")
        if path:
            Path(path).write_text(line, encoding="utf-8")
        info(self, "Linha copiada (formato de app/licensing/keys.py do VYONIX DICOM Print):\n\n" + line)

    def backup_key(self) -> None:
        kid = selected(self.keys)
        if not kid:
            return
        pw = ask_secret(self, "Backup da chave", "Frase-senha da chave (conferência):")
        if not pw:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Backup protegido da chave", f"{kid}.private.pem",
                                              "Chave PEM cifrada (*.pem)")
        if path:
            self._try(lambda: info(self, f"Chave salva CIFRADA em\n{self.w.lm.export_key_backup(self.w.user, kid, pw, Path(path))}"
                                         "\n\nGuarde a frase-senha separada do arquivo. Nunca distribua ao cliente."))

    def change_pass(self) -> None:
        kid = selected(self.keys)
        if not kid:
            return
        old = ask_secret(self, "Frase-senha", "Frase-senha atual:")
        new = self._passphrase("Nova frase-senha") if old else None
        if new:
            self._try(lambda: self.w.lm.change_key_passphrase(self.w.user, kid, old, new))

    def lock(self) -> None:
        self.w.lm.lock_key()
        info(self, "Chave de emissão bloqueada.")

    def new_user(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Novo usuário")
        form = QFormLayout(dlg)
        un, nm, pw = QLineEdit(), QLineEdit(), QLineEdit()
        pw.setEchoMode(QLineEdit.Password)
        role = QComboBox()
        for k, v in ROLES.items():
            role.addItem(v, k)
        role.setCurrentIndex(1)
        for label, w in (("Usuário", un), ("Nome", nm), ("Papel", role), ("Senha provisória", pw)):
            form.addRow(label, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec():
            self._try(lambda: self.w.lm.create_user(self.w.user, un.text(), nm.text(), role.currentData(), pw.text()))

    def role(self) -> None:
        uid = selected(self.users)
        if not uid:
            return
        items = list(ROLES.values())
        v, ok = QInputDialog.getItem(self, "Papel", "Novo papel:", items, 1, False)
        if ok:
            self._try(lambda: self.w.lm.update_user(self.w.user, uid, role=list(ROLES)[items.index(v)]))

    def toggle(self) -> None:
        uid = selected(self.users)
        if uid:
            cur = [u for u in self.w.lm.users() if u["id"] == uid][0]
            self._try(lambda: self.w.lm.update_user(self.w.user, uid, active=not cur["active"]))

    def reset(self) -> None:
        uid = selected(self.users)
        pw = ask_secret(self, "Redefinir senha", "Senha provisória (o usuário troca no próximo acesso):") if uid else None
        if pw:
            self._try(lambda: self.w.lm.reset_password(self.w.user, uid, pw))

    def my_password(self) -> None:
        old = ask_secret(self, "Minha senha", "Senha atual:")
        new = ask_secret(self, "Minha senha", "Nova senha:") if old else None
        if new and ask_secret(self, "Minha senha", "Repita a nova senha:") == new:
            self._try(lambda: self.w.lm.change_password(self.w.user, old, new))


# ---------------------------------------------------------------------------- janela
class _Idle(QObject):
    def __init__(self, cb) -> None:
        super().__init__()
        self.cb = cb

    def eventFilter(self, obj, ev):  # noqa: N802 - API Qt
        if ev.type() in (QEvent.MouseButtonPress, QEvent.KeyPress):
            self.cb()
        return False


class MainWindow(QMainWindow):
    def __init__(self, lm: LicenseManager, user) -> None:
        super().__init__()
        self.lm, self.user = lm, user
        self.setWindowTitle(f"{APP_NAME} {__version__} — {user.display_name} ({ROLES[user.role]})")
        self.resize(1320, 840)
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(250)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 12)
        b = QLabel("VYONIX")
        b.setObjectName("brand")
        s = QLabel("License Manager · administrativo")
        s.setObjectName("sub")
        sl.addWidget(b)
        sl.addWidget(s)
        self.stack = QStackedWidget()
        self.pages = [("Painel", DashboardPage(self)), ("Clientes", CustomersPage(self)),
                      ("Produtos", ProductsPage(self)), ("Solicitações e emissão", IssuePage(self)),
                      ("Licenças", LicensesPage(self)), ("Gestão Comercial", CommercialPage(self)),
                      ("Revalidação", RevalidationPage(self)),
                      ("Histórico e auditoria", AuditPage(self)), ("Backup e restauração", BackupPage(self)),
                      ("Segurança", SecurityPage(self))]
        self.nav = []
        for i, (label, page) in enumerate(self.pages):
            nb = QPushButton(label)
            nb.setCheckable(True)
            nb.clicked.connect(lambda _=False, k=i: self.go(k))
            sl.addWidget(nb)
            self.nav.append(nb)
            self.stack.addWidget(page)
        sl.addStretch(1)
        mode = QLabel(f"{'Modo portátil' if lm.paths.mode == 'portable' else 'Instalado' if lm.paths.mode == 'installed' else 'Pasta personalizada'}"
                      f"<br>{lm.paths.root}")
        mode.setObjectName("sub")
        mode.setWordWrap(True)
        sl.addWidget(mode)
        sl.addWidget(btn("Sair", self.close))
        root.addWidget(side)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.go(0)
        self._idle = QTimer(self)
        self._idle.setInterval(IDLE_MINUTES * 60 * 1000)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self.relogin)
        self._idle.start()
        self._filter = _Idle(self._idle.start)
        QApplication.instance().installEventFilter(self._filter)

    def go(self, i: int) -> None:
        for k, nb in enumerate(self.nav):
            nb.setChecked(k == i)
        self.stack.setCurrentIndex(i)
        try:
            self.pages[i][1].refresh()
        except Exception as exc:  # noqa: BLE001
            error(self, exc)

    def page_index(self, label: str) -> int:
        return next(i for i, (lbl, _p) in enumerate(self.pages) if lbl == label)

    def refresh_all(self) -> None:
        self.go(self.stack.currentIndex())

    def relogin(self) -> None:
        self.lm.lock_key()
        self.hide()
        dlg = LoginDialog(self.lm)
        dlg.setWindowTitle("Sessão bloqueada — entre novamente")
        if dlg.exec() and dlg.user:
            self.user = dlg.user
            self.setWindowTitle(f"{APP_NAME} {__version__} — {self.user.display_name} ({ROLES[self.user.role]})")
            self.show()
            self.refresh_all()
            self._idle.start()
        else:
            self.close()

    def closeEvent(self, ev) -> None:  # noqa: N802
        self.lm.lock_key()
        super().closeEvent(ev)


def run_gui(lm: LicenseManager) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLE)
    try:
        from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
        tr = QTranslator(app)
        if tr.load(QLocale("pt_BR"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            app.installTranslator(tr)
    except Exception:  # noqa: BLE001
        pass
    if not lm.is_initialized():
        dlg = SetupDialog(lm)
        if not dlg.exec() or dlg.user is None:
            return 0
        user = dlg.user
        info(None, "Administrador criado. Próximo passo: em Segurança, gere a chave de emissão ou importe a chave "
                   "oficial do produto (arquivo .pem cifrado) — somente a chave cujo par público está no VYONIX DICOM "
                   "Print produz licenças aceitas.")
    else:
        dlg = LoginDialog(lm)
        if not dlg.exec() or dlg.user is None:
            return 0
        user = dlg.user
    try:
        lm.auto_backup()
    except Exception:  # noqa: BLE001
        pass
    w = MainWindow(lm, user)
    w.show()
    if user.must_change:
        info(w, "Sua senha é provisória: altere-a em Segurança → Minha senha.")
    return app.exec()
