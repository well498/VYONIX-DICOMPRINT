"""Motor de regras automáticas (§10, Fase 6).

Uma regra = condições (todas precisam ser verdadeiras) + ações. As regras ativas são avaliadas em
ordem de **prioridade** (número menor primeiro). Para cada configuração, vale a regra de maior
prioridade que a definiu; regras seguintes só completam o que ainda não foi definido por regra.
A ação "parar" encerra a avaliação.

Precedência geral na resolução de um trabalho (da menor para a maior):

    padrão do sistema < perfil (impressora < modalidade < equipamento) < regra automática
    < pedido DICOM Print < escolha manual

A simulação explica, regra a regra, por que casou ou não — a mesma função usada na resolução,
portanto a simulação nunca diverge do comportamento real.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from app.core.errors import SettingsValidationError, ValidationError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.database.repositories.settings_repo import ChangeHistoryRepository
from app.printing.paper import PAPER_CHOICES, parse_layout
from app.utils.timeutil import utc_now_iso

EXPORT_FORMAT = "vyonix-rules"

# Campo → (rótulo, tipo). Tipos: text, int, choice, time, weekday.
FIELDS: dict[str, tuple[str, str]] = {
    "calling_ae": ("AE Title do equipamento", "text"),
    "device_id": ("Equipamento (cadastro)", "int"),
    "modality": ("Modalidade", "text"),
    "site": ("Unidade do equipamento", "text"),
    "department": ("Setor do equipamento", "text"),
    "source": ("Origem do trabalho", "choice"),
    "study_description": ("Descrição do estudo", "text"),
    "body_part": ("Parte do corpo", "text"),
    "image_count": ("Número de imagens", "int"),
    "film_size": ("Tamanho de filme pedido (DICOM Print)", "text"),
    "display_format": ("Formato pedido (DICOM Print)", "text"),
    "time": ("Horário (HH:MM)", "time"),
    "weekday": ("Dia da semana (1=seg … 7=dom)", "int"),
}
SOURCES = ("storage", "dicom_print", "manual", "reprint", "test_page")
OPS: dict[str, str] = {
    "eq": "é igual a", "ne": "é diferente de", "in": "é um de (separe por vírgula)",
    "contains": "contém", "startswith": "começa com", "gte": "maior ou igual a", "lte": "menor ou igual a",
    "between": "entre (início-fim)",
}
NUMERIC_OPS = {"eq", "ne", "in", "gte", "lte", "between"}

# Ação → (rótulo, tipo)
ACTIONS: dict[str, tuple[str, str]] = {
    "printer": ("Impressora", "text"),
    "paper": ("Papel", "paper"),
    "orientation": ("Orientação", "orientation"),
    "layout": ("Layout (linhas x colunas)", "layout"),
    "copies": ("Cópias", "int"),
    "dpi": ("Resolução de saída (dpi)", "int"),
    "margin_mm": ("Margens (mm)", "int"),
    "header_text": ("Texto do cabeçalho", "text"),
    "footer_text": ("Texto do rodapé", "text"),
    "border": ("Borda", "bool"),
    "exam_info": ("Informações do exame", "bool"),
    "page_numbers": ("Numerar páginas", "bool"),
    "spacing_mm": ("Espaçamento entre imagens (mm)", "device"),
    "brightness": ("Brilho (−5 a +5)", "device"),
    "contrast": ("Contraste (−5 a +5)", "device"),
    "gamma": ("Gama (−5 a +5)", "device"),
    "invert": ("Inverter escala de cinza", "bool"),
    "header_enabled": ("Cabeçalho BMP", "bool"),
    "footer_enabled": ("Rodapé BMP", "bool"),
    "auto_print": ("Impressão automática (não = manual)", "bool"),
    "dicom_policy": ("Prioridade do pedido DICOM Print", "device"),
    "calibration_profile_id": ("Perfil de calibração associado", "device"),
    "profile_id": ("Aplicar perfil", "int"),
    "hold": ("Reter para liberação manual", "bool"),
    "priority": ("Prioridade na fila (−100 a 100)", "int"),
    "stop": ("Parar de avaliar as regras seguintes", "bool"),
}
SETTING_ACTIONS = {"printer", "paper", "orientation", "layout", "copies", "dpi", "margin_mm", "header_text",
                   "footer_text", "border", "exam_info", "page_numbers", "spacing_mm", "brightness", "contrast",
                   "gamma", "invert", "header_enabled", "footer_enabled", "auto_print", "dicom_policy",
                   "calibration_profile_id"}


@dataclass
class Rule:
    id: int | None
    name: str
    conditions: list[dict[str, Any]]
    actions: dict[str, Any]
    priority: int = 100
    active: bool = True
    description: str | None = None
    updated_at: str | None = None
    device_id: int | None = None          # regra do equipamento (None = regra geral)

    @classmethod
    def from_row(cls, r) -> "Rule":
        return cls(id=r["id"], name=r["name"], description=r["description"],
                   conditions=json.loads(r["conditions_json"]), actions=json.loads(r["actions_json"]),
                   priority=r["priority"], active=bool(r["active"]), updated_at=r["updated_at"],
                   device_id=r["device_id"] if "device_id" in r.keys() else None)

    def to_export(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "priority": self.priority,
                "active": self.active, "conditions": self.conditions, "actions": self.actions,
                "device_id": self.device_id}


@dataclass
class Evaluation:
    """Resultado da avaliação: valores das ações, origem de cada um e explicação."""

    values: dict[str, Any] = field(default_factory=dict)
    origins: dict[str, str] = field(default_factory=dict)
    profile_id: int | None = None
    profile_rule: str | None = None
    hold: str | None = None              # nome da regra que reteve
    priority: int | None = None
    matched: list[str] = field(default_factory=list)
    matched_ids: list[int] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- avaliação
def _norm(v: Any) -> str:
    """Comparação sem diferenciar maiúsculas nem acentos ("Crânio" = "CRANIO")."""
    import unicodedata
    text = unicodedata.normalize("NFKD", str(v if v is not None else "").strip().upper())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _to_minutes(text: str) -> int:
    h, m = str(text).strip().split(":")
    h, m = int(h), int(m)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError
    return h * 60 + m


def check_condition(cond: dict[str, Any], facts: dict[str, Any]) -> tuple[bool, str]:
    """Retorna (casou, explicação)."""
    f, op, expected = cond.get("field"), cond.get("op"), cond.get("value")
    label = FIELDS.get(f, (f, ""))[0]
    actual = facts.get(f)
    kind = FIELDS.get(f, ("", "text"))[1]
    shown = "—" if actual in (None, "") else actual
    if actual in (None, ""):
        return False, f"{label}: sem valor neste trabalho"
    try:
        if kind == "time":
            a = _to_minutes(actual)
            if op == "between":
                lo, hi = (_to_minutes(x) for x in str(expected).split("-"))
                ok = lo <= a <= hi if lo <= hi else (a >= lo or a <= hi)   # faixa que cruza a meia-noite
            elif op == "gte":
                ok = a >= _to_minutes(expected)
            elif op == "lte":
                ok = a <= _to_minutes(expected)
            else:
                ok = a == _to_minutes(expected)
        elif kind == "int":
            a = int(actual)
            if op == "between":
                lo, hi = (int(x) for x in str(expected).split("-"))
                ok = lo <= a <= hi
            elif op == "in":
                ok = a in {int(x) for x in str(expected).split(",") if x.strip()}
            else:
                e = int(expected)
                ok = {"eq": a == e, "ne": a != e, "gte": a >= e, "lte": a <= e}[op]
        else:
            a = _norm(actual)
            if op == "in":
                ok = a in {_norm(x) for x in str(expected).split(",")}
            elif op == "contains":
                ok = _norm(expected) in a
            elif op == "startswith":
                ok = a.startswith(_norm(expected))
            elif op == "ne":
                ok = a != _norm(expected)
            else:
                ok = a == _norm(expected)
    except (ValueError, KeyError, TypeError):
        return False, f"{label}: condição inválida"
    verb = OPS.get(op, op)
    return ok, f"{label} {verb} {expected!s}: {'sim' if ok else 'não'} (valor: {shown})"


def evaluate(rules: list[Rule], facts: dict[str, Any]) -> Evaluation:
    """Regras do próprio equipamento primeiro (maior prioridade), depois as gerais; em cada grupo,
    número de prioridade menor primeiro. Regras de outros equipamentos nunca se aplicam."""
    ev = Evaluation()
    dev = facts.get("device_id")
    applicable = [r for r in rules if r.active and (r.device_id is None or r.device_id == dev)]
    for rule in sorted(applicable, key=lambda r: (0 if r.device_id is not None else 1, r.priority, r.id or 0)):
        results = [check_condition(c, facts) for c in rule.conditions]
        ok = all(r[0] for r in results)
        detail = "; ".join(r[1] for r in results) or "sem condições (vale para todos)"
        if not ok:
            ev.explanation.append(f"✗ Regra “{rule.name}” (prioridade {rule.priority}) não se aplica — {detail}")
            continue
        ev.matched.append(rule.name)
        scope = "do equipamento " if rule.device_id is not None else ""
        if rule.id is not None:
            ev.matched_ids.append(rule.id)
        src = f"Regra {scope}“{rule.name}”"
        applied, skipped = [], []
        for key, val in rule.actions.items():
            if key in ("stop",):
                continue
            if key == "hold":
                if val and ev.hold is None:
                    ev.hold = rule.name
                    applied.append("reter")
                continue
            if key == "priority":
                if ev.priority is None:
                    ev.priority = int(val)
                    applied.append(f"prioridade {val}")
                continue
            if key == "profile_id":
                if ev.profile_id is None:
                    ev.profile_id, ev.profile_rule = int(val), rule.name
                    applied.append(f"perfil #{val}")
                else:
                    skipped.append("perfil")
                continue
            if key in ev.values:
                skipped.append(ACTIONS.get(key, (key,))[0])
                continue
            ev.values[key], ev.origins[key] = val, src
            applied.append(f"{ACTIONS.get(key, (key,))[0]} = {val}")
        msg = f"✓ Regra “{rule.name}” (prioridade {rule.priority}) se aplica — {detail}."
        if applied:
            msg += " Aplica: " + ", ".join(applied) + "."
        if skipped:
            msg += " Já definido por regra de maior prioridade: " + ", ".join(skipped) + "."
        ev.explanation.append(msg)
        if rule.actions.get("stop"):
            ev.explanation.append(f"■ A regra “{rule.name}” encerra a avaliação.")
            break
    if not ev.matched:
        ev.explanation.append("Nenhuma regra se aplica: valem perfis e padrões do sistema.")
    return ev


def facts_for(*, source: str, calling_ae: str | None, device: Any | None, modality: str | None,
              image_count: int, now: datetime | None = None, first_file: str | None = None,
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Monta os fatos de um trabalho. Lê do arquivo apenas descrição do estudo e parte do corpo."""
    now = (now or datetime.now()).astimezone()
    facts: dict[str, Any] = {
        "source": source, "calling_ae": calling_ae, "modality": modality, "image_count": image_count,
        "time": now.strftime("%H:%M"), "weekday": now.isoweekday(),
        "device_id": getattr(device, "id", None), "site": getattr(device, "site", None),
        "department": getattr(device, "department", None),
    }
    if first_file:
        try:
            import pydicom
            ds = pydicom.dcmread(first_file, stop_before_pixels=True,
                                 specific_tags=["StudyDescription", "BodyPartExamined"])
            facts["study_description"] = str(ds.get("StudyDescription") or "") or None
            facts["body_part"] = str(ds.get("BodyPartExamined") or "") or None
        except Exception:  # noqa: BLE001 - fatos opcionais
            pass
    facts.update(extra or {})
    return facts


# --------------------------------------------------------------------------- cadastro
def validate_rule(rule: Rule, profile_exists: Callable[[int], bool] | None = None) -> None:
    errors: dict[str, str] = {}
    if not (rule.name or "").strip():
        errors["name"] = "Informe um nome para a regra."
    elif len(rule.name) > 80:
        errors["name"] = "Nome com no máximo 80 caracteres."
    if not -1000 <= int(rule.priority) <= 1000:
        errors["priority"] = "Prioridade deve estar entre −1000 e 1000."
    for i, c in enumerate(rule.conditions, start=1):
        f, op, val = c.get("field"), c.get("op"), c.get("value")
        if f not in FIELDS:
            errors[f"condition{i}"] = f"Condição {i}: campo inválido."
            continue
        if op not in OPS:
            errors[f"condition{i}"] = f"Condição {i}: operador inválido."
            continue
        kind = FIELDS[f][1]
        if kind in ("int", "time") and op not in NUMERIC_OPS:
            errors[f"condition{i}"] = f"Condição {i}: operador “{OPS[op]}” não se aplica a {FIELDS[f][0]}."
            continue
        if val in (None, ""):
            errors[f"condition{i}"] = f"Condição {i}: informe o valor."
            continue
        probe = {f: "00:00" if kind == "time" else (0 if kind == "int" else "X")}
        ok, why = check_condition(c, probe)
        if why.endswith("condição inválida"):
            errors[f"condition{i}"] = f"Condição {i}: valor inválido para {FIELDS[f][0]}."
        if f == "source" and op in ("eq", "ne") and val not in SOURCES:
            errors[f"condition{i}"] = f"Condição {i}: origem deve ser uma de {', '.join(SOURCES)}."
    if not rule.actions:
        errors["actions"] = "A regra precisa de pelo menos uma ação."
    for key, val in rule.actions.items():
        if key not in ACTIONS:
            errors["actions"] = f"Ação desconhecida: {key}."
            continue
        kind = ACTIONS[key][1]
        if kind == "device" or key in ("invert", "header_enabled", "footer_enabled", "auto_print"):
            from app.devices.settings import validate_values
            try:
                validate_values({key: val}, profile_exists)
            except SettingsValidationError as exc:
                errors[f"action:{key}"] = "; ".join(exc.errors.values())
            continue
        try:
            if kind == "paper" and val not in PAPER_CHOICES:
                raise ValueError("papel inválido")
            if kind == "orientation" and val not in ("auto", "portrait", "landscape"):
                raise ValueError("orientação inválida")
            if kind == "layout":
                parse_layout(val)
            if kind == "bool" and not isinstance(val, bool):
                raise ValueError("deve ser sim ou não")
            if kind == "int":
                n = int(val)
                limits = {"copies": (1, 99), "dpi": (150, 600), "margin_mm": (0, 40), "priority": (-100, 100)}
                lo, hi = limits.get(key, (-10**9, 10**9))
                if not lo <= n <= hi:
                    raise ValueError(f"deve estar entre {lo} e {hi}")
                if key == "profile_id" and profile_exists and not profile_exists(n):
                    raise ValueError("perfil inexistente ou desativado")
            if kind == "text" and len(str(val)) > 256:
                raise ValueError("texto longo demais")
        except (ValueError, ValidationError) as exc:
            errors[f"action:{key}"] = f"{ACTIONS[key][0]}: {exc}"
    if errors:
        raise SettingsValidationError(errors)


class RuleService:
    def __init__(self, db: Database, events: EventRepository,
                 profile_exists: Callable[[int], bool] | None = None,
                 allowed: Callable[[], bool] | None = None) -> None:
        self.allowed = allowed or (lambda: True)
        self.db = db
        self.events = events
        self.history = ChangeHistoryRepository(db)
        self.profile_exists = profile_exists

    def list(self, include_inactive: bool = True, device_id: int | None | str = "all") -> list[Rule]:
        """``device_id``: "all" (todas), None (só gerais) ou o id do equipamento (só as dele)."""
        where, params = [], []
        if not include_inactive:
            where.append("active = 1")
        if device_id is None:
            where.append("device_id IS NULL")
        elif device_id != "all":
            where.append("device_id = ?")
            params.append(int(device_id))
        sql = "SELECT * FROM rules" + (" WHERE " + " AND ".join(where) if where else "") + \
            " ORDER BY device_id IS NOT NULL DESC, device_id, priority, id"
        return [Rule.from_row(r) for r in self.db.connection().execute(sql, params)]

    def get(self, rule_id: int) -> Rule:
        r = self.db.connection().execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
        if r is None:
            raise ValidationError(f"Regra {rule_id} não encontrada.")
        return Rule.from_row(r)

    def evaluate(self, facts: dict[str, Any]) -> Evaluation:
        if not self.allowed():
            return Evaluation(explanation=["Regras automáticas não incluídas na licença desta instalação: valem "
                                           "perfis e padrões do sistema."])
        return evaluate(self.list(include_inactive=False), facts)

    def save(self, rule: Rule, *, actor: str) -> Rule:
        rule.name = (rule.name or "").strip()
        validate_rule(rule, self.profile_exists)
        conn = self.db.connection()
        dup = conn.execute("SELECT id FROM rules WHERE name = ? AND id IS NOT ?", (rule.name, rule.id)).fetchone()
        if dup:
            raise SettingsValidationError({"name": "Já existe uma regra com este nome."})
        now = utc_now_iso()
        if rule.device_id is not None and conn.execute("SELECT 1 FROM devices WHERE id = ?",
                                                       (rule.device_id,)).fetchone() is None:
            raise SettingsValidationError({"device": "Equipamento da regra não encontrado."})
        values = (rule.name, rule.description, json.dumps(rule.conditions, ensure_ascii=False),
                  json.dumps(rule.actions, ensure_ascii=False), int(rule.priority), int(rule.active), rule.device_id)
        with self.db.transaction():
            if rule.id is None:
                cur = conn.execute("""INSERT INTO rules(name, description, conditions_json, actions_json, priority,
                                         active, device_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                   (*values, now, now))
                rid, old = int(cur.lastrowid), None
            else:
                old = self.get(rule.id)
                conn.execute("""UPDATE rules SET name=?, description=?, conditions_json=?, actions_json=?, priority=?,
                                active=?, device_id=?, updated_at=? WHERE id = ?""", (*values, now, rule.id))
                rid = rule.id
            self.history.record(entity_type="rule", entity_id=str(rid), field="rule",
                                old_value=old.to_export() if old else None, new_value=rule.to_export(), actor=actor)
            self.events.add(level="INFO", category=Category.RULES, action="rule.create" if old is None else "rule.update",
                            message=f"Regra “{rule.name}” {'criada' if old is None else 'alterada'}.",
                            actor=actor)
        return self.get(rid)

    def set_active(self, rule_id: int, active: bool, *, actor: str) -> None:
        rule = self.get(rule_id)
        rule.active = active
        self.save(rule, actor=actor)

    def delete(self, rule_id: int, *, actor: str) -> None:
        rule = self.get(rule_id)
        with self.db.transaction():
            self.db.connection().execute("UPDATE jobs SET rule_id = NULL WHERE rule_id = ?", (rule_id,))
            self.db.connection().execute("DELETE FROM rules WHERE id = ?", (rule_id,))
            self.history.record(entity_type="rule", entity_id=str(rule_id), field="rule",
                                old_value=rule.to_export(), new_value=None, actor=actor)
            self.events.add(level="WARNING", category=Category.RULES, action="rule.delete",
                            message=f"Regra “{rule.name}” excluída.", actor=actor)

    def duplicate(self, rule_id: int, *, actor: str, device_id: int | None | str = "same") -> Rule:
        """Cópia independente (inativa até ser revisada), opcionalmente para outro equipamento."""
        src = self.get(rule_id)
        base = f"{src.name} (cópia)"
        name, n = base, 2
        names = {r.name for r in self.list()}
        while name in names:
            name, n = f"{base} {n}", n + 1
        copy = Rule(id=None, name=name, description=src.description, conditions=json.loads(json.dumps(src.conditions)),
                    actions=json.loads(json.dumps(src.actions)), priority=src.priority, active=False,
                    device_id=src.device_id if device_id == "same" else device_id)
        return self.save(copy, actor=actor)

    def versions(self, rule_id: int) -> list[dict[str, Any]]:
        """Versões anteriores registradas no histórico de alterações."""
        out = []
        for h in self.history.list(entity_type="rule", entity_id=str(rule_id)):
            if h.old_value:
                try:
                    out.append({"id": h.id, "changed_at": h.changed_at, "changed_by": h.changed_by,
                                "rule": json.loads(h.old_value) if isinstance(h.old_value, str) else h.old_value})
                except ValueError:
                    continue
        return out

    def restore_version(self, rule_id: int, history_id: int, *, actor: str) -> Rule:
        v = next((x for x in self.versions(rule_id) if x["id"] == history_id), None)
        if v is None:
            raise ValidationError("Versão não encontrada no histórico desta regra.")
        old = v["rule"]
        rule = self.get(rule_id)
        restored = Rule(id=rule.id, name=old.get("name", rule.name), description=old.get("description"),
                        conditions=list(old.get("conditions") or []), actions=dict(old.get("actions") or {}),
                        priority=int(old.get("priority", rule.priority)), active=bool(old.get("active", True)),
                        device_id=old.get("device_id", rule.device_id))
        return self.save(restored, actor=actor)

    def move(self, rule_id: int, delta: int, *, actor: str) -> None:
        """Troca a prioridade com a regra vizinha do mesmo escopo (delta −1 = sobe, +1 = desce)."""
        me = self.get(rule_id)
        rules = self.list(device_id=me.device_id)
        idx = next(i for i, r in enumerate(rules) if r.id == rule_id)
        j = idx + delta
        if not 0 <= j < len(rules):
            return
        a, b = rules[idx], rules[j]
        if a.priority == b.priority:
            b.priority = a.priority + (1 if delta > 0 else -1)
        a.priority, b.priority = b.priority, a.priority
        with self.db.transaction():
            self.save(a, actor=actor)
            self.save(b, actor=actor)

    def export_json(self) -> str:
        return json.dumps({"format": EXPORT_FORMAT, "version": 1, "rules": [r.to_export() for r in self.list()]},
                          ensure_ascii=False, indent=2)

    def import_json(self, text: str, *, actor: str) -> int:
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ValidationError(f"Arquivo inválido: {exc}") from exc
        if data.get("format") != EXPORT_FORMAT:
            raise ValidationError("O arquivo não é uma exportação de regras do VYONIX.")
        items = data.get("rules") or []
        rules = [Rule(id=None, name=i.get("name", ""), description=i.get("description"),
                      conditions=list(i.get("conditions") or []), actions=dict(i.get("actions") or {}),
                      priority=int(i.get("priority", 100)), active=bool(i.get("active", True)),
                      device_id=i.get("device_id")) for i in items]
        known_devices = {r[0] for r in self.db.connection().execute("SELECT id FROM devices")}
        for r in rules:   # regra de equipamento inexistente nesta instalação vira regra geral inativa
            if r.device_id is not None and r.device_id not in known_devices:
                r.device_id, r.active = None, False
        for r in rules:   # valida tudo antes de gravar
            validate_rule(r, self.profile_exists)
        existing = {r.name: r.id for r in self.list()}
        with self.db.transaction():
            for r in rules:
                r.id = existing.get(r.name)
                self.save(r, actor=actor)
        return len(rules)
