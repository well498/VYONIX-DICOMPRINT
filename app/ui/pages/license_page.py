"""Licença (formato 2): situação, tela inicial de ativação, solicitação, DEMO, diagnóstico e revalidação.

Nenhuma ação desta página emite licenças: elas são emitidas somente pelo VYONIX License Manager.
"""

from __future__ import annotations

import json
from pathlib import Path

from vyonix_protocol import formats as F

from app.core.errors import VyonixError
from app.ui.admin import current_actor, ensure_admin
from app.ui.pages.base import Page, banner, card
from app.ui.qt import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                       QLabel, QMessageBox, QPushButton, Qt, QVBoxLayout, QWidget)
from app.ui.widgets import button, button_row, fill_table, local_time, make_table
from app.ui.workers import run_async

REQUEST_REASONS = [("new", "Primeira ativação / nova licença"), ("reinstall", F.REACTIVATION_REASONS["reinstall"]),
                   ("disk", F.REACTIVATION_REASONS["disk"]), ("board", F.REACTIVATION_REASONS["board"]),
                   ("computer", F.REACTIVATION_REASONS["computer"]), ("windows", F.REACTIVATION_REASONS["windows"]),
                   ("storage_failure", F.REACTIVATION_REASONS["storage_failure"]),
                   ("system_recovery", F.REACTIVATION_REASONS["system_recovery"]),
                   ("other", F.REACTIVATION_REASONS["other"])]
STATE_STYLE = {"valid": "ok", "demo": "ok"}


# ---------------------------------------------------------------------------- ações compartilhadas
def export_request(parent, ctx) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Exportar solicitação de ativação")
    lay = QVBoxLayout(dlg)
    info = QLabel("A solicitação contém o VYONIX Hardware ID (resumos criptográficos dos componentes, sem números de "
                  "série legíveis), o VYONIX Installation ID, a versão e o nome da unidade. Nenhum dado de paciente. "
                  "Envie o arquivo ao administrador do VYONIX License Manager.")
    info.setWordWrap(True)
    lay.addWidget(info)
    form = QFormLayout()
    reason = QComboBox()
    for k, label in REQUEST_REASONS:
        reason.addItem(label, k)
    form.addRow("Motivo", reason)
    lay.addLayout(form)
    bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    copy_btn = bb.addButton("Copiar código", QDialogButtonBox.ActionRole)
    lay.addWidget(bb)
    bb.rejected.connect(dlg.reject)

    def make() -> str:
        return ctx.license.request_file(reason=reason.currentData())

    def copy() -> None:
        QApplication.clipboard().setText(json.loads(make())["code"])
        QMessageBox.information(dlg, "Solicitação", "Código copiado. Cole-o no e-mail ou mensagem ao administrador.")
    copy_btn.clicked.connect(lambda _=False: copy())

    def save() -> None:
        default = ctx.paths.exports_dir / f"VYONIX-solicitacao-{ctx.license.installation_id()[5:13]}.vyreq"
        path, _ = QFileDialog.getSaveFileName(dlg, "Salvar solicitação", str(default), "Solicitação VYONIX (*.vyreq)")
        if not path:
            return
        try:
            Path(path).write_text(make(), encoding="utf-8")
        except (OSError, VyonixError) as exc:
            QMessageBox.warning(dlg, "Solicitação", str(exc))
            return
        QMessageBox.information(dlg, "Solicitação", f"Solicitação salva em:\n{path}")
        dlg.accept()
    bb.accepted.connect(save)
    dlg.exec()


def install_license(parent, ctx) -> bool:
    if not ensure_admin(parent, ctx.access, "ativar licença"):
        return False
    path, _ = QFileDialog.getOpenFileName(parent, "Ativar licença comercial", str(ctx.paths.exports_dir),
                                          "Licença VYONIX (*.vylic);;Todos os arquivos (*)")
    if not path:
        return False
    try:
        st = ctx.license.install(Path(path).read_text(encoding="utf-8"), actor=current_actor())
    except (VyonixError, OSError, UnicodeDecodeError) as exc:
        QMessageBox.warning(parent, "Licença recusada", str(exc))
        return False
    QMessageBox.information(parent, "Licença ativada", f"{st.state.label}. {st.message}")
    return True


def start_demo(parent, ctx) -> bool:
    if QMessageBox.question(parent, "Demonstração de 5 dias", (
            "Iniciar a demonstração do VYONIX DICOM Print?\n\n• 5 dias corridos (120 horas) a partir de agora — "
            "fechar o programa ou desligar o computador NÃO pausa a contagem.\n• Uma demonstração por computador: "
            "reinstalar não concede outra.\n• Todas as funções liberadas; as páginas impressas identificam a "
            "demonstração.\n• As configurações são preservadas ao ativar a licença comercial.")) != QMessageBox.Yes:
        return False
    try:
        st = ctx.license.start_demo(actor=current_actor())
    except VyonixError as exc:
        QMessageBox.warning(parent, "Demonstração", str(exc))
        return False
    QMessageBox.information(parent, "Demonstração iniciada", st.message)
    return True


def show_hardware_id(parent, ctx) -> None:
    prof = ctx.license.profile(refresh=True)
    inst = ctx.license.installation_id()
    tpm = ctx.license.tpm.info() if ctx.license.tpm else {"available": False}
    dlg = QDialog(parent)
    dlg.setWindowTitle("VYONIX Hardware ID")
    dlg.resize(620, 420)
    lay = QVBoxLayout(dlg)
    big = QLabel(f"<span style='font-size:20px; font-family:Consolas,monospace'><b>{prof.hardware_id}</b></span>")
    big.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lay.addWidget(big)
    lay.addWidget(QLabel(f"VYONIX Installation ID: <b>{inst}</b>"))
    tbl = make_table(["Componente", "Situação"], min_height=180)
    rows = prof.summary()
    rows.append(("Prova de posse do TPM", "disponível" if tpm.get("available") else (tpm.get("reason") or "—")))
    fill_table(tbl, rows)
    lay.addWidget(tbl, 1)
    hint = QLabel("O Hardware ID combina os componentes acima por resumo criptográfico: os números de série originais "
                  "não são exibidos nem enviados. A troca de disco, placa-mãe ou do Windows exige reativação pelo "
                  "administrador.")
    hint.setWordWrap(True)
    hint.setObjectName("muted")
    lay.addWidget(hint)
    bb = QDialogButtonBox(QDialogButtonBox.Close)
    cp = bb.addButton("Copiar Hardware ID e Installation ID", QDialogButtonBox.ActionRole)
    cp.clicked.connect(lambda _=False: QApplication.clipboard().setText(
        f"VYONIX Hardware ID: {prof.hardware_id}\nVYONIX Installation ID: {inst}"))
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    dlg.exec()


class ActivationDialog(QDialog):
    """Tela inicial quando não há licença válida nem demonstração ativa."""

    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Ativação do VYONIX DICOM Print")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        st = ctx.license.status(refresh=True)
        title = QLabel(f"<h2>VYONIX DICOM Print</h2><b>{st.state.label}.</b> {st.message}")
        title.setWordWrap(True)
        lay.addWidget(title)
        note = QLabel("Até a ativação, a recepção DICOM, a impressão, o Print SCP e as regras ficam suspensos. "
                      "Cadastros e configurações podem ser preparados normalmente.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        lay.addWidget(note)
        demo_state = ctx.license.demo.state(ctx.license.time.check().effective).state
        self.buttons = {}
        for key, text, slot, enabled in (
                ("demo", "Iniciar demonstração de 5 dias", self._demo, demo_state == "available"),
                ("activate", "Ativar licença comercial", self._activate, True),
                ("request", "Exportar solicitação", lambda: export_request(self, ctx), True),
                ("hwid", "Visualizar Hardware ID", lambda: show_hardware_id(self, ctx), True)):
            b = QPushButton(text)
            b.setMinimumHeight(44)
            b.setEnabled(enabled)
            if key == "demo" and not enabled:
                b.setToolTip("A demonstração deste computador já foi utilizada.")
            b.clicked.connect(lambda _=False, f=slot: f())
            self.buttons[key] = b
            lay.addWidget(b)
        later = QPushButton("Continuar sem ativar (funções suspensas)")
        later.setFlat(True)
        later.clicked.connect(self.reject)
        lay.addWidget(later)

    def _demo(self) -> None:
        if start_demo(self, self.ctx):
            self.accept()

    def _activate(self) -> None:
        if install_license(self, self.ctx):
            self.accept()


def maybe_show_activation(window, ctx) -> None:
    """Chamado ao abrir a janela principal (versões comerciais)."""
    try:
        if ctx.license.enforced and not ctx.license.status(refresh=True).active:
            ActivationDialog(ctx, window).exec()
    except Exception:  # noqa: BLE001 - a tela inicial nunca impede a abertura do programa
        import logging
        logging.getLogger(__name__).exception("Tela de ativação")


# ---------------------------------------------------------------------------- página
class LicensePage(Page):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__("Licença", "Licenças, renovações, revalidações e listas de revogação são emitidas pelo "
                         "administrador (VYONIX License Manager). Licenças com validação online consultam o VYONIX "
                         "License Server; as demais funcionam sem internet.", parent)
        self.ctx = ctx
        self.state = banner("")
        self.body.addWidget(self.state)
        self.body.addLayout(button_row(
            button("Iniciar demonstração de 5 dias", self._demo),
            button("Ativar licença comercial…", self._install, primary=True),
            button("Exportar solicitação…", lambda: export_request(self, self.ctx)),
            button("Visualizar Hardware ID", lambda: show_hardware_id(self, self.ctx)), stretch_at=4))
        frame, lay = card("Licença instalada")
        self.details = QLabel("—")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.details)
        self.policy = QLabel("")
        self.policy.setObjectName("muted")
        self.policy.setWordWrap(True)
        lay.addWidget(self.policy)
        self.body.addWidget(frame)

        frame, lay = card("Assinatura e validação")
        self.sub = QLabel("—")
        self.sub.setWordWrap(True)
        self.sub.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.sub)
        lay.addLayout(button_row(
            button("Verificar agora no License Server", self._check_online),
            button("Importar autorização / renovação…", self._import_auth),
            button("Exportar exames armazenados…", self._export_exams), stretch_at=3))
        self.shist = make_table(["Data/hora", "Tipo", "De", "Para", "Origem", "Responsável"], min_height=110)
        lay.addWidget(self.shist)
        self.body.addWidget(frame)

        frame, lay = card("Identificação, integridade e recuperação")
        self.ids = QLabel("—")
        self.ids.setWordWrap(True)
        self.ids.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.ids)
        lay.addLayout(button_row(
            button("Exportar diagnóstico…", self._diagnostic), button("Importar revalidação…", self._revalidation),
            button("Importar lista de revogação…", self._revocation), button("Remover licença", self._remove),
            stretch_at=4))
        self.body.addWidget(frame)

        frame, lay = card("Impressoras autorizadas pela licença")
        self.printers = make_table(["Impressora", "Vaga ocupada em", "Por"], min_height=90)
        lay.addWidget(self.printers)
        lay.addLayout(button_row(button("Liberar vaga da impressora selecionada", self._release), stretch_at=1))
        self.body.addWidget(frame)

        frame, lay = card("Histórico de licenças desta instalação e de integridade temporal")
        self.hist = make_table(["Licença", "Tipo", "Edição", "Cliente", "Emitida", "Vence", "Situação"], min_height=110)
        lay.addWidget(self.hist)
        self.time = make_table(["Data/hora", "Evento", "Diferença", "Detalhe"], min_height=110)
        lay.addWidget(self.time)
        self.body.addWidget(frame)
        self.body.addStretch(1)

    def on_shown(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        def load():
            lic = self.ctx.license
            v = lic.verdict(refresh=True)
            ts = lic.time.check()
            tlog = [dict(r) for r in self.ctx.db.connection().execute(
                "SELECT at, kind, delta_s, detail FROM time_integrity_log ORDER BY id DESC LIMIT 50")]
            return (v, lic.policy_text(), lic.profile(), lic.installation_id(), lic.licensed_printers(),
                    lic.history(), ts, tlog, lic.tpm.info() if lic.tpm else {}, lic.state_history(100),
                    lic.authorizations.online(), lic.installed_license())
        run_async(load, self._render)

    def _render(self, data) -> None:
        v, policy, prof, inst, printers, history, ts, tlog, tpm, shist, online, installed = data
        st, lic = v.status, v.lic
        self._render_subscription(st, online, installed, shist)
        self.state.setText(f"<b>{st.state.label}.</b> {st.message}" + (f"<br><b>{st.warning}</b>" if st.warning else ""))
        self.state.setProperty("state", STATE_STYLE.get(st.state.value, "warn" if st.state.value == "not_activated"
                                                        else "err"))
        self.state.style().polish(self.state)
        if lic is not None:
            feats = ", ".join(F.FEATURE_LABELS.get(f, f) for f in lic.features) or "—"
            self.details.setText(
                f"<b>{lic.type_label}</b> — edição {lic.edition} — {lic.customer}<br>"
                f"License ID {lic.license_id} · emitida em {local_time(lic.issued_at)}"
                + (f" · vence em {F.parse_time(lic.expires_at).astimezone():%d/%m/%Y %H:%M}"
                   if lic.expires_at and lic.type != "demo" else "")
                + (" · sem vencimento comercial" if lic.type == "permanent" else "")
                + f"<br>Recursos: {feats}"
                + f"<br>Equipamentos autorizados: {lic.max_devices or 'sem limite'} · "
                  f"impressoras autorizadas: {lic.max_printers or 'sem limite'}"
                + (f"<br>Reemissão da licença {lic.reissue_of}" if lic.reissue_of else ""))
        elif st.kind == "demo_local":
            self.details.setText(f"<b>Demonstração local</b> — {st.message}")
        else:
            self.details.setText("Nenhuma licença válida instalada.")
        self.policy.setText(policy)
        comps = ", ".join(lbl for lbl, txt in prof.summary() if txt.startswith("considerado") or "placa" in txt)
        self.ids.setText(
            f"VYONIX Hardware ID: <b>{prof.hardware_id}</b><br>VYONIX Installation ID: <b>{inst}</b><br>"
            f"Componentes considerados: {comps or '—'}<br>"
            f"TPM 2.0: {'chave do VYONIX disponível (prova de posse)' if tpm.get('available') else tpm.get('reason', '—')}"
            f"<br>Time Integrity: horário confiável {ts.trusted.astimezone():%d/%m/%Y %H:%M}"
            + (f" — <b>{ts.message}</b>" if ts.issue else " — sem inconsistências"))
        fill_table(self.printers, [(p["printer"], local_time(p["added_at"]), p["added_by"]) for p in printers],
                   [p["printer"] for p in printers])
        fill_table(self.hist, [(h["license_id"], F.LICENSE_TYPES.get(h.get("license_type") or "", (h.get("license_type")
                                or "—",))[0], h["edition"], h["licensee"], (h["issued_at"] or "")[:10],
                                (h["expires_at"] or "—")[:10], {"active": "ativa", "superseded": "substituída",
                                                                "ended": "encerrada (desinstalação)", "revoked": "revogada",
                                                                "invalid": "inválida"}.get(h["status"], h["status"]))
                               for h in history])
        fill_table(self.time, [(local_time(t["at"]), t["kind"], f"{t['delta_s'] / 3600:+.2f} h" if t["delta_s"] else "",
                                t["detail"] or "") for t in tlog])

    def _render_subscription(self, st, online, installed, shist) -> None:
        from app.licensing.subscription import CONNECTIVITY_LABELS
        if installed is None or installed.type == "demo":
            self.sub.setText("Sem licença comercial instalada.")
        else:
            pol = F.license_policy({"policy": installed.extra.get("policy")}
                                   if installed.extra.get("policy") is not None else {})
            lines = [f"Validação: <b>{F.VALIDATION_MODES[pol['validation']]}</b>"
                     + (f" — {pol['server_url']}" if pol.get("server_url") else "")]
            if st.commercial:
                lines.append(f"Situação da assinatura: <b>{st.commercial_label}</b>")
            if self.ctx.access.is_unlocked():               # detalhes comerciais: só o administrador
                if st.admin_notice:
                    lines.append(st.admin_notice)
                lines.append(f"Aviso {pol['warn_days']} dia(s) antes do vencimento · carência de {pol['grace_days']} "
                             "dia(s)" + (f" · tolerância sem contato com o servidor: {pol['online_tolerance_days']} "
                                         "dia(s)" if pol["validation"] == "online" else ""))
            elif st.commercial and st.commercial not in ("active", "reactivated"):
                lines.append("Detalhes da assinatura: desbloqueie com a senha de administrador.")
            if pol["validation"] == "online":
                lines.append(f"Conectividade: <b>{CONNECTIVITY_LABELS.get(st.connectivity or 'pending', '—')}</b>"
                             + (f" · último contato {local_time(online['last_ok'])}" if online.get("last_ok") else "")
                             + (f" · última tentativa {local_time(online['last_attempt'])}"
                                if online.get("last_attempt") else ""))
            self.sub.setText("<br>".join(lines))
        kinds = {"license": "Licença", "commercial": "Assinatura", "connectivity": "Conectividade"}
        fill_table(self.shist, [(local_time(h["at"]), kinds.get(h["kind"], h["kind"]), h["from_state"] or "—",
                                 h["to_state"], h["source"], h["actor"]) for h in shist])

    def _check_online(self) -> None:
        def run():
            return self.ctx.license.check_online(actor=current_actor())

        def done(r) -> None:
            from app.licensing.subscription import CONNECTIVITY_LABELS
            QMessageBox.information(self, "License Server", f"{CONNECTIVITY_LABELS.get(r.result, r.result)}.\n"
                                    f"{r.message}")
            self.refresh()

        def fail(exc) -> None:
            QMessageBox.warning(self, "License Server", str(exc))
        run_async(run, done, fail)

    def _import_auth(self) -> None:
        def apply(text: str, actor: str) -> str:
            st = self.ctx.license.import_authorization(text, actor=actor)
            return f"Autorização aplicada. {st.state.label}" + (f" — assinatura {st.commercial_label}."
                                                                 if st.commercial_label else ".")
        self._import_doc("Importar autorização / renovação",
                         "Autorização VYONIX (*.vyauth);;Todos os arquivos (*)", apply)

    def _export_exams(self) -> None:
        if not ensure_admin(self, self.ctx.access, "exportar exames"):
            return
        folder = QFileDialog.getExistingDirectory(self, "Pasta de destino da exportação")
        if not folder:
            return

        def run():
            return self.ctx.exporter.export(Path(folder), actor=current_actor())

        def done(res) -> None:
            QMessageBox.information(self, "Exportação", f"{res.studies} exame(s), {res.files} arquivo(s) exportados "
                                    f"para\n{res.folder}" + (f"\n{len(res.missing)} arquivo(s) já removidos pela "
                                                            "retenção." if res.missing else ""))

        def fail(exc) -> None:
            QMessageBox.warning(self, "Exportação", str(exc))
        run_async(run, done, fail)

    def _demo(self) -> None:
        if start_demo(self, self.ctx):
            self.refresh()

    def _install(self) -> None:
        if install_license(self, self.ctx):
            self.refresh()

    def _diagnostic(self) -> None:
        default = self.ctx.paths.exports_dir / "VYONIX-diagnostico-licenca.json"
        path, _ = QFileDialog.getSaveFileName(self, "Exportar diagnóstico", str(default), "Diagnóstico (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(self.ctx.license.diagnostic(), ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        except (OSError, VyonixError) as exc:
            QMessageBox.warning(self, "Diagnóstico", str(exc))
            return
        QMessageBox.information(self, "Diagnóstico", f"Diagnóstico salvo em:\n{path}\n\nEnvie ao administrador para "
                                "revalidação. O arquivo não contém dados de pacientes nem números de série legíveis.")

    def _import_doc(self, title: str, pattern: str, fn) -> None:
        if not ensure_admin(self, self.ctx.access, title.lower()):
            return
        path, _ = QFileDialog.getOpenFileName(self, title, str(self.ctx.paths.exports_dir), pattern)
        if not path:
            return
        try:
            msg = fn(Path(path).read_text(encoding="utf-8"), actor=current_actor())
        except (VyonixError, OSError, UnicodeDecodeError) as exc:
            QMessageBox.warning(self, title, str(exc))
            return
        QMessageBox.information(self, title, msg)
        self.refresh()

    def _revalidation(self) -> None:
        self._import_doc("Importar revalidação", "Revalidação VYONIX (*.vyreval);;Todos os arquivos (*)",
                         self.ctx.license.apply_revalidation)

    def _revocation(self) -> None:
        self._import_doc("Importar lista de revogação", "Lista de revogação (*.vyrevoke);;Todos os arquivos (*)",
                         self.ctx.license.apply_revocation)

    def _remove(self) -> None:
        if not ensure_admin(self, self.ctx.access, "remover licença"):
            return
        if QMessageBox.question(self, "Remover licença", "Remover a licença desta instalação? As funções licenciadas "
                                "serão suspensas.") != QMessageBox.Yes:
            return
        self.ctx.license.remove(actor=current_actor())
        self.refresh()

    def _release(self) -> None:
        from app.ui.widgets import selected_key
        name = selected_key(self.printers)
        if not name:
            QMessageBox.information(self, "Impressoras", "Selecione uma impressora.")
            return
        if not ensure_admin(self, self.ctx.access, "liberar vaga de impressora"):
            return
        self.ctx.license.release_printer(name, actor=current_actor())
        self.refresh()
