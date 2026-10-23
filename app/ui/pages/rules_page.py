"""Regras automáticas (§10): cadastro, prioridade, simulação, importação e exportação."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core.errors import SettingsValidationError, VyonixError
from app.printing import resolver
from app.printing.paper import LAYOUTS, PAPER_LABELS
from app.rules.engine import ACTIONS, FIELDS, OPS, SOURCES, Rule, facts_for
from app.ui.admin import current_actor, ensure_admin
from app.ui.pages.base import FitScrollArea, Page, banner
from app.ui.responsive import compact_combo
from app.ui.pages.jobs_page import SETTING_LABELS, _fmt
from app.ui.qt import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                       QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
                       QWidget)
from app.ui.widgets import button, button_row, fill_table, local_time, make_table, selected_key, status_text
from app.ui.workers import run_async

SOURCE_LABELS = {"storage": "Recebimento (Storage)", "dicom_print": "DICOM Print", "manual": "Manual",
                 "reprint": "Reimpressão", "test_page": "Página de teste"}
ORIENT = (("auto", "Automática"), ("portrait", "Retrato"), ("landscape", "Paisagem"))


def describe_conditions(rule: Rule) -> str:
    if not rule.conditions:
        return "todos os trabalhos"
    return " e ".join(f"{FIELDS.get(c['field'], (c['field'],))[0]} {OPS.get(c['op'], c['op'])} {c['value']}"
                      for c in rule.conditions)


def describe_actions(rule: Rule) -> str:
    out = []
    for k, v in rule.actions.items():
        label = ACTIONS.get(k, (k,))[0]
        out.append(label if isinstance(v, bool) and v else f"{label}: {_fmt(v)}")
    return "; ".join(out)


class ConditionRow(QWidget):
    def __init__(self, parent, on_remove) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.field = QComboBox()
        for k, (label, _) in FIELDS.items():
            self.field.addItem(label, k)
        self.op = QComboBox()
        for k, label in OPS.items():
            self.op.addItem(label, k)
        self.value = QLineEdit()
        self.value.setPlaceholderText("valor")
        rm = QPushButton("Remover")
        rm.clicked.connect(lambda _=False: on_remove(self))
        lay.addWidget(self.field, 2)
        lay.addWidget(self.op, 2)
        lay.addWidget(self.value, 3)
        lay.addWidget(rm)
        self.field.currentIndexChanged.connect(lambda _: self._hint())
        self._hint()

    def _hint(self) -> None:
        f = self.field.currentData()
        hints = {"time": "ex.: 19:00-07:00", "weekday": "ex.: 6,7", "source": ", ".join(SOURCES),
                 "image_count": "ex.: 10", "device_id": "nº do equipamento", "modality": "ex.: CT, MR"}
        self.value.setPlaceholderText(hints.get(f, "valor"))

    def set(self, c: dict) -> None:
        self.field.setCurrentIndex(max(self.field.findData(c.get("field")), 0))
        self.op.setCurrentIndex(max(self.op.findData(c.get("op")), 0))
        self.value.setText(str(c.get("value", "")))

    def get(self) -> dict:
        return {"field": self.field.currentData(), "op": self.op.currentData(), "value": self.value.text().strip()}


class RuleDialog(QDialog):
    def __init__(self, parent: QWidget, ctx, rule: Rule | None, device_id: int | None = None) -> None:
        super().__init__(parent)
        self.ctx, self.rule, self.saved = ctx, rule, None
        self.setWindowTitle("Editar regra" if rule else "Nova regra")
        self.setMinimumWidth(760)
        outer = QVBoxLayout(self)
        # conteúdo rolável: em telas pequenas (ex.: 1366 × 768 a 125 %) o diálogo inteiro não cabe
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        scroll = FitScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        form = QFormLayout()
        self.name = QLineEdit()
        self.description = QLineEdit()
        self.priority = QSpinBox()
        self.priority.setRange(-1000, 1000)
        self.priority.setValue(100)
        self.active = QCheckBox("Regra ativa")
        self.active.setChecked(True)
        self.scope = QComboBox()
        self.scope.addItem("Regra geral (todos os equipamentos)", None)
        for d in ctx.devices.list(include_inactive=True):
            self.scope.addItem(f"Somente o equipamento {d.name} ({d.ae_title})", d.id)
        start = rule.device_id if rule else device_id
        self.scope.setCurrentIndex(max(self.scope.findData(start), 0) if start is not None else 0)
        form.addRow("Nome *", self.name)
        form.addRow("Aplica-se a", self.scope)
        form.addRow("Descrição", self.description)
        self.priority.setToolTip("Regras com número menor são avaliadas primeiro.")
        form.addRow("Prioridade (menor primeiro)", self.priority)
        form.addRow("", self.active)
        lay.addLayout(form)

        title = QLabel("Quando (todas as condições; sem condições = todos os trabalhos)")
        title.setObjectName("cardTitle")
        lay.addWidget(title)
        self.cond_box = QVBoxLayout()
        lay.addLayout(self.cond_box)
        add = QPushButton("Adicionar condição")
        add.clicked.connect(lambda _=False: self._add_condition())
        lay.addWidget(add)
        self.conditions: list[ConditionRow] = []

        title = QLabel("Então (marque o que a regra define)")
        title.setObjectName("cardTitle")
        lay.addWidget(title)
        grid = QGridLayout()
        self.actions: dict[str, tuple[QCheckBox, QWidget]] = {}
        # uma ação por linha: os rótulos longos (ex.: "Parar de avaliar as regras seguintes") eram cortados
        # em duas colunas na largura mínima do diálogo
        for i, (key, (label, kind)) in enumerate(ACTIONS.items()):
            chk = QCheckBox(label)
            w = self._editor(key, kind)
            grid.addWidget(chk, i, 0)
            grid.addWidget(w, i, 1)
            self.actions[key] = (chk, w)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        lay.addStretch(1)
        self.error = QLabel("")
        self.error.setObjectName("fieldError")
        self.error.setWordWrap(True)
        outer.addWidget(self.error)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)
        compact_combo(self.scope, 28)
        for combo in content.findChildren(QComboBox):          # editores das ações (textos longos)
            if combo is not self.scope:
                compact_combo(combo)
        self._content = content
        if rule:
            self._fill(rule)

    def showEvent(self, event) -> None:  # noqa: N802 - API Qt
        """Tamanho inicial pela tela em que o diálogo abre (calculado só agora, já com o estilo aplicado)."""
        if not getattr(self, "_sized", False) and self.screen() is not None:
            self._sized = True
            avail = self.screen().availableGeometry()
            self.resize(min(860, avail.width() - 40), min(self._content.sizeHint().height() + 120, avail.height() - 60))
        super().showEvent(event)

    def _editor(self, key: str, kind: str) -> QWidget:
        if kind == "paper":
            w = QComboBox()
            for v, label in PAPER_LABELS.items():
                w.addItem(label, v)
        elif kind == "orientation":
            w = QComboBox()
            for v, label in ORIENT:
                w.addItem(label, v)
        elif kind == "layout":
            w = QComboBox()
            for x in LAYOUTS:
                w.addItem(x.replace("x", " × "), x)
        elif kind == "bool":
            w = QComboBox()
            w.addItem("Sim", True)
            w.addItem("Não", False)
        elif key == "printer":
            w = QComboBox()
            for p in self.ctx.printers.list():
                w.addItem(p.name, p.name)
        elif key in ("brightness", "contrast", "gamma"):
            from app.ui.qt import QDoubleSpinBox
            w = QDoubleSpinBox()
            w.setRange(-5.0, 5.0)
            w.setDecimals(1)
            w.setSingleStep(0.5)
        elif key == "spacing_mm":
            from app.ui.qt import QDoubleSpinBox
            w = QDoubleSpinBox()
            w.setRange(0, 20)
            w.setDecimals(1)
        elif key == "dicom_policy":
            from app.devices.settings import DICOM_POLICIES
            w = QComboBox()
            for k_, label_ in DICOM_POLICIES.items():
                w.addItem(label_, k_)
        elif key in ("profile_id", "calibration_profile_id"):
            w = QComboBox()
            for p in self.ctx.profiles.list():
                w.addItem(p.name, p.id)
        elif kind == "int":
            w = QSpinBox()
            lo, hi = {"copies": (1, 99), "dpi": (150, 600), "margin_mm": (0, 40), "priority": (-100, 100)}.get(
                key, (0, 9999))
            w.setRange(lo, hi)
            if key == "dpi":
                w.setValue(300)
        else:
            w = QLineEdit()
        return w

    @staticmethod
    def _value(w: QWidget):
        if isinstance(w, QComboBox):
            return w.currentData()
        if isinstance(w, QSpinBox):
            return w.value()
        if hasattr(w, "decimals"):
            return round(float(w.value()), 1)
        return w.text().strip()

    @staticmethod
    def _set_value(w: QWidget, value) -> None:
        if isinstance(w, QComboBox):
            idx = w.findData(value)
            if idx < 0 and value is not None:
                w.addItem(f"{value} (indisponível)", value)
                idx = w.count() - 1
            w.setCurrentIndex(max(idx, 0))
        elif isinstance(w, QSpinBox):
            w.setValue(int(value))
        elif hasattr(w, "decimals"):
            w.setValue(float(value))
        else:
            w.setText(str(value))

    def _add_condition(self, c: dict | None = None) -> None:
        row = ConditionRow(self, self._remove_condition)
        if c:
            row.set(c)
        self.conditions.append(row)
        self.cond_box.addWidget(row)

    def _remove_condition(self, row: ConditionRow) -> None:
        self.conditions.remove(row)
        row.setParent(None)
        row.deleteLater()

    def _fill(self, r: Rule) -> None:
        self.name.setText(r.name)
        self.description.setText(r.description or "")
        self.priority.setValue(r.priority)
        self.active.setChecked(r.active)
        for c in r.conditions:
            self._add_condition(c)
        for key, val in r.actions.items():
            if key in self.actions:
                chk, w = self.actions[key]
                chk.setChecked(True)
                self._set_value(w, val)

    def collect(self) -> Rule:
        actions = {k: self._value(w) for k, (chk, w) in self.actions.items() if chk.isChecked()}
        return Rule(id=self.rule.id if self.rule else None, name=self.name.text(),
                    description=self.description.text() or None, conditions=[c.get() for c in self.conditions],
                    actions=actions, priority=self.priority.value(), active=self.active.isChecked(),
                    device_id=self.scope.currentData())

    def _save(self) -> None:
        try:
            self.saved = self.ctx.rules.save(self.collect(), actor=current_actor())
        except SettingsValidationError as exc:
            self.error.setText("; ".join(exc.errors.values()))
            return
        self.accept()


class SimulationDialog(QDialog):
    """Mostra quais regras se aplicariam a um trabalho hipotético e o resultado final."""

    def __init__(self, parent: QWidget, ctx) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Simular regras")
        self.resize(920, 640)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.source = QComboBox()
        for k in SOURCES:
            self.source.addItem(SOURCE_LABELS[k], k)
        self.device = QComboBox()
        self.device.addItem("— nenhum (não cadastrado) —", None)
        self.devices = {d.id: d for d in ctx.devices.list()}
        for d in self.devices.values():
            self.device.addItem(f"{d.name} ({d.ae_title})", d.id)
        self.device.currentIndexChanged.connect(lambda _: self._device_changed())
        self.ae = QLineEdit()
        self.modality = QLineEdit()
        self.study = QLineEdit()
        self.body_part = QLineEdit()
        self.count = QSpinBox()
        self.count.setRange(1, 999)
        now = datetime.now()
        self.time = QLineEdit(now.strftime("%H:%M"))
        self.weekday = QComboBox()
        for i, n in enumerate(("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"), start=1):
            self.weekday.addItem(n, i)
        self.weekday.setCurrentIndex(now.isoweekday() - 1)
        self.film = QLineEdit()
        self.film.setPlaceholderText("ex.: 14INX17IN (só DICOM Print)")
        for label, w in (("Origem", self.source), ("Equipamento", self.device), ("AE Title", self.ae),
                         ("Modalidade", self.modality), ("Descrição do estudo", self.study),
                         ("Parte do corpo", self.body_part), ("Número de imagens", self.count),
                         ("Horário (HH:MM)", self.time), ("Dia da semana", self.weekday), ("Filme pedido", self.film)):
            form.addRow(label, w)
        lay.addLayout(form)
        run = QPushButton("Simular")
        run.setObjectName("primary")
        run.clicked.connect(lambda _=False: self.simulate())
        lay.addWidget(run)
        self.explanation = QPlainTextEdit()
        self.explanation.setReadOnly(True)
        self.explanation.setFixedHeight(150)
        lay.addWidget(self.explanation)
        self.result = make_table(["Configuração", "Resultado", "Origem"], min_height=200)
        lay.addWidget(self.result, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _device_changed(self) -> None:
        d = self.devices.get(self.device.currentData())
        if d:
            self.ae.setText(d.ae_title)
            self.modality.setText(d.modality or "")

    def facts(self) -> dict:
        d = self.devices.get(self.device.currentData())
        f = facts_for(source=self.source.currentData(), calling_ae=self.ae.text().strip() or None, device=d,
                      modality=self.modality.text().strip().upper() or None, image_count=self.count.value(),
                      extra={"study_description": self.study.text().strip() or None,
                             "body_part": self.body_part.text().strip() or None,
                             "film_size": self.film.text().strip().upper() or None})
        f["time"], f["weekday"] = self.time.text().strip(), self.weekday.currentData()
        return f

    def simulate(self) -> None:
        facts = self.facts()
        d = self.devices.get(self.device.currentData())
        try:
            ev = self.ctx.rules.evaluate(facts)
            dev_printer = None
            if d and d.printer_id:
                dev_printer = next((p.name for p in self.ctx.printers.list() if p.id == d.printer_id), None)
            res = resolver.resolve(self.ctx.settings.get, self.ctx.profiles, device_id=d.id if d else None,
                                   device_profile_id=d.print_profile_id if d else None,
                                   modality=facts.get("modality"), rules=ev, device_printer=dev_printer)
        except VyonixError as exc:
            self.explanation.setPlainText(f"Falha: {exc}")
            return
        lines = list(ev.explanation)
        if ev.hold:
            lines.append(f"→ O trabalho seria RETIDO pela regra “{ev.hold}”.")
        if ev.priority is not None:
            lines.append(f"→ Prioridade na fila: {ev.priority}.")
        lines.append("Simulação: nada é impresso nem gravado.")
        self.explanation.setPlainText("\n".join(lines))
        fill_table(self.result, [(SETTING_LABELS.get(k, k), _fmt(v), res.origins.get(k, "—"))
                                 for k, v in res.values.items() if k in SETTING_LABELS])


class DeviceRulesDialog(QDialog):
    """Regras de um equipamento (Equipamentos → Regras do equipamento)."""

    def __init__(self, parent: QWidget, ctx, device) -> None:
        super().__init__(parent)
        self.ctx, self.device = ctx, device
        self.setWindowTitle(f"Regras do equipamento — {device.name}")
        self.resize(1000, 520)
        lay = QVBoxLayout(self)
        note = QLabel("Regras deste equipamento têm prioridade sobre as configurações gerais dele e sobre as regras "
                      "gerais. Elas nunca afetam outro equipamento.")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.table = make_table(["Prioridade", "Regra", "Ativa", "Quando", "Então"])
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, slot in (("Nova regra", self.add), ("Editar", self.edit), ("Duplicar", self.duplicate),
                           ("Ativar / desativar", self.toggle), ("Excluir", self.delete)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=slot: f())
            row.addWidget(b)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        lay.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        self.rules = {r.id: r for r in self.ctx.rules.list(device_id=self.device.id)}
        fill_table(self.table, [(r.priority, r.name, "Sim" if r.active else "Não", describe_conditions(r),
                                 describe_actions(r)) for r in self.rules.values()], list(self.rules))

    def _sel(self):
        return self.rules.get(selected_key(self.table))

    def add(self) -> None:
        if ensure_admin(self, self.ctx.access, "criar regra"):
            if RuleDialog(self, self.ctx, None, device_id=self.device.id).exec():
                self.refresh()

    def edit(self) -> None:
        r = self._sel()
        if r and ensure_admin(self, self.ctx.access, "editar regra") and RuleDialog(self, self.ctx, r).exec():
            self.refresh()

    def duplicate(self) -> None:
        r = self._sel()
        if r and ensure_admin(self, self.ctx.access, "duplicar regra"):
            self.ctx.rules.duplicate(r.id, actor=current_actor())
            self.refresh()

    def toggle(self) -> None:
        r = self._sel()
        if r and ensure_admin(self, self.ctx.access, "ativar ou desativar regra"):
            self.ctx.rules.set_active(r.id, not r.active, actor=current_actor())
            self.refresh()

    def delete(self) -> None:
        r = self._sel()
        if r and ensure_admin(self, self.ctx.access, "excluir regra") and QMessageBox.question(
                self, "Excluir regra", f"Excluir \u201c{r.name}\u201d?") == QMessageBox.Yes:
            self.ctx.rules.delete(r.id, actor=current_actor())
            self.refresh()


class RulesPage(Page):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__("Regras automáticas",
                         "Regras escolhem impressora, papel, layout, cópias e outras opções conforme o equipamento, "
                         "a modalidade, o horário e outros dados. Ordem: prioridade menor primeiro; a regra de maior "
                         "prioridade vence. Precedência geral: padrão < perfil < regra < pedido DICOM Print < "
                         "escolha manual.", parent)
        self.ctx = ctx
        self.status = banner("")
        self.status.hide()
        self.body.addWidget(self.status)
        self.body.addLayout(button_row(
            button("Nova regra", self.add, primary=True), button("Editar", self.edit),
            button("Ativar / desativar", self.toggle), button("Subir", lambda: self.move(-1)),
            button("Descer", lambda: self.move(1)), button("Duplicar", self.duplicate),
            button("Versões…", self.versions), button("Excluir", self.delete),
            button("Simular…", self.simulate), button("Importar…", self.import_), button("Exportar…", self.export),
            stretch_at=8))
        frow = QHBoxLayout()
        frow.addWidget(QLabel("Mostrar"))
        self.scope_filter = QComboBox()
        self.scope_filter.addItem("Todas as regras", "all")
        self.scope_filter.addItem("Somente regras gerais", None)
        self.scope_filter.currentIndexChanged.connect(lambda _: self.refresh())
        frow.addWidget(self.scope_filter, 1)
        self.body.addLayout(frow)
        self.table = make_table(["Prioridade", "Regra", "Aplica-se a", "Ativa", "Quando", "Então", "Alterada em"])
        self.table.doubleClicked.connect(lambda _: self.edit())
        self.body.addWidget(self.table, 1)
        self.rules: dict[int, Rule] = {}

    def refresh(self) -> None:
        scope = self.scope_filter.currentData() if self.scope_filter.currentIndex() >= 0 else "all"

        def load():
            devices = {d.id: d.name for d in self.ctx.devices.list(include_inactive=True)}
            return self.ctx.rules.list(device_id=scope), devices
        run_async(load, self._render, self._error)

    def on_shown(self) -> None:
        current = self.scope_filter.currentData()
        self.scope_filter.blockSignals(True)
        while self.scope_filter.count() > 2:
            self.scope_filter.removeItem(2)
        for d in self.ctx.devices.list(include_inactive=True):
            self.scope_filter.addItem(f"Regras do equipamento {d.name}", d.id)
        self.scope_filter.setCurrentIndex(max(self.scope_filter.findData(current), 0))
        self.scope_filter.blockSignals(False)
        self.refresh()

    def _render(self, data) -> None:
        rules, devices = data
        self.rules = {r.id: r for r in rules}
        fill_table(self.table, [(r.priority, r.name, devices.get(r.device_id, "?") if r.device_id else "Todos",
                                 "Sim" if r.active else "Não", describe_conditions(r), describe_actions(r),
                                 local_time(r.updated_at)) for r in rules], [r.id for r in rules])

    def _error(self, exc: BaseException) -> None:
        self._msg(f"Falha: {exc}", "err")

    def _msg(self, text: str, style: str) -> None:
        status_text(self.status, text, "banner")
        self.status.setProperty("state", style)
        self.status.style().polish(self.status)
        self.status.show()

    def _selected(self) -> Rule | None:
        r = self.rules.get(selected_key(self.table))
        if r is None:
            self._msg("Selecione uma regra na lista.", "warn")
        return r

    def add(self) -> None:
        if not ensure_admin(self, self.ctx.access, "criar regra"):
            return
        scope = self.scope_filter.currentData()
        dlg = RuleDialog(self, self.ctx, None, device_id=scope if isinstance(scope, int) else None)
        if dlg.exec():
            self._msg(f"Regra “{dlg.saved.name}” criada.", "ok")
            self.refresh()

    def edit(self) -> None:
        r = self._selected()
        if r is None or not ensure_admin(self, self.ctx.access, "editar regra"):
            return
        dlg = RuleDialog(self, self.ctx, r)
        if dlg.exec():
            self._msg("Regra salva.", "ok")
            self.refresh()

    def _act(self, action: str, fn, ok: str) -> None:
        r = self._selected()
        if r is None or not ensure_admin(self, self.ctx.access, action):
            return
        try:
            fn(r)
        except VyonixError as exc:
            self._msg(str(exc), "err")
            return
        self._msg(ok.format(name=r.name), "ok")
        self.refresh()

    def toggle(self) -> None:
        self._act("ativar ou desativar regra",
                  lambda r: self.ctx.rules.set_active(r.id, not r.active, actor=current_actor()),
                  "Regra “{name}” atualizada.")

    def move(self, delta: int) -> None:
        self._act("mudar a prioridade", lambda r: self.ctx.rules.move(r.id, delta, actor=current_actor()),
                  "Prioridade de “{name}” alterada.")

    def duplicate(self) -> None:
        self._act("duplicar regra", lambda r: self.ctx.rules.duplicate(r.id, actor=current_actor()),
                  "Cópia de \u201c{name}\u201d criada (inativa até ser revisada).")

    def versions(self) -> None:
        r = self._selected()
        if r is None:
            return
        vs = self.ctx.rules.versions(r.id)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Versões anteriores — {r.name}")
        dlg.resize(900, 420)
        lay = QVBoxLayout(dlg)
        t = make_table(["Alterada em", "Por", "Condições", "Ações"])
        fill_table(t, [(local_time(v["changed_at"]), v["changed_by"],
                        describe_conditions(Rule(id=None, name="", conditions=v["rule"].get("conditions") or [],
                                                 actions={})),
                        describe_actions(Rule(id=None, name="", conditions=[], actions=v["rule"].get("actions") or {})))
                       for v in vs], [v["id"] for v in vs])
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        restore = bb.addButton("Restaurar esta versão", QDialogButtonBox.ActionRole)
        bb.rejected.connect(dlg.reject)

        def do_restore():
            hid = selected_key(t)
            if hid is None or not ensure_admin(self, self.ctx.access, "restaurar versão da regra"):
                return
            try:
                self.ctx.rules.restore_version(r.id, int(hid), actor=current_actor())
            except VyonixError as exc:
                self._msg(str(exc), "err")
                return
            dlg.accept()
            self._msg(f"Versão restaurada para \u201c{r.name}\u201d.", "ok")
            self.refresh()
        restore.clicked.connect(lambda _=False: do_restore())
        lay.addWidget(bb)
        dlg.exec()

    def delete(self) -> None:
        self._act("excluir regra", lambda r: self.ctx.rules.delete(r.id, actor=current_actor()),
                  "Regra “{name}” excluída.")

    def simulate(self) -> None:
        SimulationDialog(self, self.ctx).exec()

    def export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar regras",
                                              str(self.ctx.paths.exports_dir / "vyonix-regras.json"), "JSON (*.json)")
        if path:
            Path(path).write_text(self.ctx.rules.export_json(), encoding="utf-8")
            self._msg(f"Regras exportadas para {path}.", "ok")

    def import_(self) -> None:
        if not ensure_admin(self, self.ctx.access, "importar regras"):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Importar regras", str(self.ctx.paths.exports_dir),
                                              "JSON (*.json)")
        if not path:
            return
        try:
            n = self.ctx.rules.import_json(Path(path).read_text(encoding="utf-8"), actor=current_actor())
        except SettingsValidationError as exc:
            self._msg("Arquivo recusado: " + "; ".join(exc.errors.values()), "err")
            return
        except VyonixError as exc:
            self._msg(str(exc), "err")
            return
        self._msg(f"{n} regra(s) importada(s) (regras com o mesmo nome foram substituídas).", "ok")
        self.refresh()
