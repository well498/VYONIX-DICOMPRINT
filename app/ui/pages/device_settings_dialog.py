"""Configurações gerais de impressão de um equipamento (somente dele), com a origem de cada valor final.

Campos em "— herdar —" usam o nível inferior da hierarquia (DICOM Print conforme a política, perfil da
modalidade, padrão do VYONIX). Inclui versões (restaurar), duplicar de outro equipamento, comparar e
pré-visualizar a página exatamente como será impressa.
"""

from __future__ import annotations

from app.core.errors import SettingsValidationError, VyonixError
from app.devices.settings import DICOM_POLICIES, FIELDS
from app.imaging import tone
from app.printing.paper import LAYOUTS, PAPER_LABELS
from app.ui.admin import current_actor, ensure_admin
from app.ui.images import to_pixmap
from app.ui.pages.jobs_page import SETTING_LABELS, _fmt
from app.ui.qt import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                       QMessageBox, QPushButton, QSpinBox, QTabWidget, Qt, QVBoxLayout, QWidget)
from app.ui.widgets import fill_table, local_time, make_table, selected_key
from app.ui.workers import run_async

INHERIT = "— herdar —"
EXTRA_LABELS = {**SETTING_LABELS, "brightness": "Brilho", "contrast": "Contraste", "gamma": "Gama",
                "invert": "Inverter", "header_enabled": "Cabeçalho BMP", "footer_enabled": "Rodapé BMP",
                "header_gap_mm": "Espaço cabeçalho→imagens", "footer_gap_mm": "Espaço imagens→rodapé",
                "extra_margin_mm": "Margem adicional", "auto_print": "Impressão automática",
                "dicom_policy": "Prioridade DICOM Print", "calibration_profile_id": "Perfil de calibração"}


def _combo(items, current=None) -> QComboBox:
    c = QComboBox()
    c.addItem(INHERIT, None)
    for value, label in items:
        c.addItem(label, value)
    c.setCurrentIndex(max(c.findData(current), 0) if current is not None else 0)
    return c


class DeviceSettingsDialog(QDialog):
    def __init__(self, parent: QWidget, ctx, device) -> None:
        super().__init__(parent)
        self.ctx, self.device = ctx, device
        self.setWindowTitle(f"Configurações de impressão — {device.name}")
        self.resize(1080, 760)
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{device.name}</b> · AE {device.ae_title} · {device.modality or 'modalidade não informada'}"
                      " — estas configurações valem só para este equipamento.")
        head.setWordWrap(True)
        lay.addWidget(head)
        tabs = QTabWidget()
        lay.addWidget(tabs, 1)

        # ---------------- aba: configurações
        form_w = QWidget()
        form = QFormLayout(form_w)
        self.editors: dict[str, QWidget] = {}
        cur = ctx.device_settings.get(device.id)
        printers = [(p.name, p.name) for p in ctx.printers.list()]
        profiles = [(p.id, p.name) for p in ctx.profiles.list()]
        for key, (label, kind) in FIELDS.items():
            if kind == "tone":
                continue        # ajustados na Calibração de Imagem (pré-visualização em tempo real)
            val = cur.get(key)
            if kind == "printer":
                w = _combo(printers, val)
            elif kind == "paper":
                w = _combo([(k, v) for k, v in PAPER_LABELS.items()], val)
            elif kind == "orientation":
                w = _combo((("auto", "Automática"), ("portrait", "Retrato"), ("landscape", "Paisagem")), val)
            elif kind == "layout":
                w = _combo([(x, x.replace("x", " × ")) for x in LAYOUTS], val)
                w.setEditable(True)
                w.setToolTip("Escolha ou digite um layout personalizado (ex.: 4x3), até 8 × 8.")
                if val and w.findData(val) < 0:
                    w.addItem(val.replace("x", " × "), val)
                    w.setCurrentIndex(w.count() - 1)
            elif kind == "bool":
                w = _combo(((True, "Sim"), (False, "Não")), val)
            elif kind == "policy":
                w = _combo(list(DICOM_POLICIES.items()), val)
            elif kind == "profile":
                w = _combo(profiles, val)
            elif kind == "int":
                w = QSpinBox()
                w.setRange(0, 99)
                w.setSpecialValueText(INHERIT)
                w.setValue(int(val) if val is not None else 0)
            else:   # float
                w = QDoubleSpinBox()
                w.setDecimals(1)
                w.setRange(-0.1, 40.0)
                w.setSingleStep(0.5)
                w.setSpecialValueText(INHERIT)
                w.setValue(float(val) if val is not None else -0.1)
            self.editors[key] = w
            form.addRow(label, w)
        t = ctx.device_settings.tone(device.id)
        self.tone_label = QLabel(f"Calibração de imagem: {t.label()}")
        form.addRow("", self.tone_label)
        tabs.addTab(form_w, "Configurações")

        # ---------------- aba: resultado final e origem
        res_w = QWidget()
        rl = QVBoxLayout(res_w)
        self.result = make_table(["Configuração", "Valor final", "Origem"], min_height=320)
        rl.addWidget(self.result)
        self.preview = QLabel("Clique em “Pré-visualizar página”.")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(260)
        rl.addWidget(self.preview, 1)
        self.warnings = QLabel("")
        self.warnings.setObjectName("fieldError")
        self.warnings.setWordWrap(True)
        rl.addWidget(self.warnings)
        tabs.addTab(res_w, "Resultado final e origem")

        # ---------------- aba: versões
        ver_w = QWidget()
        vl = QVBoxLayout(ver_w)
        self.versions = make_table(["Versão", "Data/hora", "Usuário", "Motivo", "Valores"], min_height=300)
        vl.addWidget(self.versions)
        rb = QPushButton("Restaurar versão selecionada")
        rb.clicked.connect(lambda _=False: self.restore_version())
        vl.addWidget(rb)
        tabs.addTab(ver_w, "Versões anteriores")

        self.error = QLabel("")
        self.error.setObjectName("fieldError")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        row = QHBoxLayout()
        for text, slot in (("Pré-visualizar página", self.preview_page), ("Duplicar de outro equipamento…", self.copy_from),
                           ("Comparar com…", self.compare)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=slot: f())
            row.addWidget(b)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        lay.addLayout(row)
        self._load_versions()
        self._refresh_result()

    # ------------------------------------------------------------------
    def values(self) -> dict:
        out = {}
        for key, w in self.editors.items():
            kind = FIELDS[key][1]
            if isinstance(w, QComboBox):
                v = w.currentData()
                if kind == "layout" and v is None and w.currentText() not in ("", INHERIT):
                    v = w.currentText().replace("×", "x").replace(" ", "")
                out[key] = v
            elif isinstance(w, QSpinBox):
                out[key] = w.value() or None
            else:
                out[key] = None if w.value() < 0 else w.value()
        cur = self.ctx.device_settings.get(self.device.id)
        for k in (*tone.LABELS, "invert"):
            if k in cur and k not in out:
                out[k] = cur[k]
        if "invert" in self.editors:
            out["invert"] = self.editors["invert"].currentData()
        return out

    def save(self) -> None:
        if not ensure_admin(self, self.ctx.access, "alterar configurações do equipamento"):
            return
        try:
            self.ctx.device_settings.save(self.device.id, self.values(), actor=current_actor(),
                                          reason="configurações de impressão")
        except SettingsValidationError as exc:
            self.error.setText("; ".join(exc.errors.values()))
            return
        self.error.setText("Configurações salvas.")
        self._load_versions()
        self._refresh_result()

    def _load_versions(self) -> None:
        vs = self.ctx.device_settings.versions(self.device.id)
        fill_table(self.versions, [(v["version"], local_time(v["created_at"]), v["actor"], v["reason"] or "",
                                    ", ".join(f"{EXTRA_LABELS.get(k, k)}={_fmt(x)}" for k, x in v["settings"].items()))
                                   for v in vs], [v["version"] for v in vs])

    def _refresh_result(self) -> None:
        did, modality = self.device.id, self.device.modality

        def work():
            ev = self.ctx.jobs.evaluate_rules(source_type="storage", source_ae=self.device.ae_title, device_id=did,
                                              modality=modality, items=[])
            return self.ctx.jobs.resolve_for(device_id=did, modality=modality, rules=ev)

        def show(res):
            rows = [(EXTRA_LABELS.get(k, k), tone.fmt(v) if k in tone.LABELS else _fmt(v), res.origins.get(k, "—"))
                    for k, v in res.values.items() if k in EXTRA_LABELS]
            fill_table(self.result, rows)
        run_async(work, show, lambda exc: self.error.setText(f"Falha: {exc}"))

    def preview_page(self) -> None:
        rows = self.ctx.imaging.recent_instances(limit=1, device_id=self.device.id)
        iid = rows[0]["id"] if rows else None
        self.preview.setText("Montando a página…")

        def show(data):
            pages, warnings, _res = data
            if pages:
                self.preview.setPixmap(to_pixmap(pages[0].pixels, 700, 420))
            self.warnings.setText("; ".join(warnings))
        run_async(lambda: self.ctx.worker.preview_device(self.device.id, iid), show,
                  lambda exc: self.preview.setText(f"Não foi possível pré-visualizar: {exc}"))

    def restore_version(self) -> None:
        v = selected_key(self.versions)
        if v is None or not ensure_admin(self, self.ctx.access, "restaurar versão"):
            return
        if QMessageBox.question(self, "Restaurar", f"Restaurar a versão {v}? A versão atual continua no histórico.") \
                != QMessageBox.Yes:
            return
        self.ctx.device_settings.restore(self.device.id, int(v), actor=current_actor())
        self.accept()

    def _pick_device(self, title: str):
        others = [d for d in self.ctx.devices.list(include_inactive=True) if d.id != self.device.id]
        if not others:
            QMessageBox.information(self, title, "Não há outro equipamento cadastrado.")
            return None
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        f = QFormLayout(dlg)
        c = QComboBox()
        for d in others:
            c.addItem(f"{d.name} ({d.ae_title})", d.id)
        f.addRow("Equipamento", c)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        return c.currentData() if dlg.exec() else None

    def copy_from(self) -> None:
        src = self._pick_device("Duplicar configurações de outro equipamento")
        if src is None or not ensure_admin(self, self.ctx.access, "duplicar configurações"):
            return
        if QMessageBox.question(self, "Duplicar", "Substituir as configurações (inclusive a calibração) deste "
                                "equipamento por uma cópia independente das do equipamento escolhido?") != QMessageBox.Yes:
            return
        try:
            self.ctx.device_settings.copy_from(src, self.device.id, actor=current_actor())
        except VyonixError as exc:
            self.error.setText(str(exc))
            return
        self.accept()

    def compare(self) -> None:
        other = self._pick_device("Comparar com outro equipamento")
        if other is None:
            return
        od = self.ctx.devices.get(other)
        rows = self.ctx.device_settings.compare(self.device.id, other)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Comparação: {self.device.name} × {od.name}")
        dlg.resize(820, 560)
        lay = QVBoxLayout(dlg)
        t = make_table(["Configuração", self.device.name, od.name, "Diferente"])
        fill_table(t, [(label, _fmt(a) if a is not None else INHERIT, _fmt(b) if b is not None else INHERIT,
                        "●" if diff else "") for label, a, b, diff in rows])
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.exec()
