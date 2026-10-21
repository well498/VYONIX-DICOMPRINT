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
from app.printing.paper import PAPER_SIZES, parse_layout
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
    "profile_id": ("Aplicar perfil", "int"),
    "hold": ("Reter para liberação manual", "bool"),
    "priority": ("Prioridade na fila (−100 a 100)", "int"),
    "stop": ("Parar de avaliar as regras seguintes", "bool"),
}
SETTING_ACTIONS = {"printer", "paper", "orientation", "layout", "copies", "dpi", "margin_mm", "header_text",
                   "footer_text", "border", "exam_info", "page_numbers"}


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

    @classmethod
    def from_row(cls, r) -> "Rule":
        return cls(id=r["id"], name=r["name"], description=r["description"],
                   conditions=json.loads(r["conditions_json"]), actions=json.loads(r["actions_json"]),
                   priority=r["priority"], active=bool(r["active"]), updated_at=r["updated_at"])

    def to_export(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "priority": self.priority,
                "active": self.active, "conditions": self.conditions, "actions": self.actions}


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
    ev = Evaluation()
    for rule in sorted((r for r in rules if r.active), key=lambda r: (r.priority, r.id or 0)):
        results = [check_condition(c, facts) for c in rule.conditions]
        ok = all(r[0] for r in results)
        detail = "; ".join(r[1] for r in results) or "sem condições (vale para todos)"
        if not ok:
            ev.explanation.append(f"✗ Regra “{rule.name}” (prioridade {rule.priority}) não se aplica — {detail}")
            continue
        ev.matched.append(rule.name)
        if rule.id is not None:
            ev.matched_ids.append(rule.id)
        src = f"Regra “{rule.name}”"
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
        try:
            if kind == "paper" and val not in PAPER_SIZES:
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

    def list(self, include_inactive: bool = True) -> list[Rule]:
        sql = "SELECT * FROM rules" + ("" if include_inactive else " WHERE active = 1") + " ORDER BY priority, id"
        return [Rule.from_row(r) for r in self.db.connection().execute(sql)]

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
        values = (rule.name, rule.description, json.dumps(rule.conditions, ensure_ascii=False),
                  json.dumps(rule.actions, ensure_ascii=False), int(rule.priority), int(rule.active))
        with self.db.transaction():
            if rule.id is None:
                cur = conn.execute("""INSERT INTO rules(name, description, conditions_json, actions_json, priority,
                                         active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                   (*values, now, now))
                rid, old = int(cur.lastrowid), None
            else:
                old = self.get(rule.id)
                conn.execute("""UPDATE rules SET name=?, description=?, conditions_json=?, actions_json=?, priority=?,
                                active=?, updated_at=? WHERE id = ?""", (*values, now, rule.id))
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

    def move(self, rule_id: int, delta: int, *, actor: str) -> None:
        """Troca a prioridade com a regra vizinha (delta −1 = sobe, +1 = desce)."""
        rules = self.list()
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
                      priority=int(i.get("priority", 100)), active=bool(i.get("active", True))) for i in items]
        for r in rules:   # valida tudo antes de gravar
            validate_rule(r, self.profile_exists)
        existing = {r.name: r.id for r in self.list()}
        with self.db.transaction():
            for r in rules:
                r.id = existing.get(r.name)
                self.save(r, actor=actor)
        return len(rules)
