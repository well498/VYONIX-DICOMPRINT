"""Motor de execução do DEPLOY: plano → aprovação → passos → verificação → reversão → retomada.

Cada passo implementa ``check`` (já está como deveria?), ``capture`` (estado anterior), ``apply``,
``verify`` (confere o estado real depois) e ``rollback``. Assim:

* **Idempotência** — passos cujo ``check`` já confere não são aplicados ("já estava assim").
* **Retomada** — o estado de cada passo é gravado (SQLite, ``synchronous=FULL``) antes e depois de
  aplicar. Uma execução interrompida é retomada: passos confirmados são conferidos de novo
  (``verify``); o passo que estava em aplicação é conferido (``check``) e reaplicado se necessário.
* **Reversão** — se um passo falha ou não se confirma no estado real, os passos já aplicados nesta
  execução que são reversíveis são desfeitos em ordem inversa, com o estado anterior gravado.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import socket
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from vyonix_deploy import __version__
from vyonix_deploy.config import DeployConfig
from vyonix_deploy.db import DeployDB, now
from vyonix_deploy.errors import DeployError, NotApproved
from vyonix_deploy.paths import Paths

CATEGORIES = {"rede": "Rede", "firewall": "Firewall", "servico": "Serviço", "dicom": "DICOM", "https": "HTTPS",
              "armazenamento": "Armazenamento", "banco": "Banco de dados", "atalho": "Atalho", "nuvem": "Nuvem",
              "aplicacao": "Aplicação", "modulo": "Módulo"}


@dataclass
class Context:
    cfg: DeployConfig
    paths: Paths
    db: DeployDB
    inventory: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None
    secrets: Any = None
    log: Callable[[str, str], None] = lambda level, msg: None
    extra: dict[str, Any] = field(default_factory=dict)


class Step:
    """Um item gerenciado. Subclasses implementam os métodos abaixo."""

    id: str = ""
    category: str = "aplicacao"
    title: str = ""
    reversible: bool = True
    destructive: bool = False
    reboot: bool = False
    confirm: str | None = None          # texto exigido na aprovação (mudanças críticas, ex.: IP fixo)

    def describe(self, ctx: Context) -> dict[str, Any]:
        return {"current": self.observe(ctx), "proposed": self.desired(ctx), "impact": "", "undo": ""}

    def check(self, ctx: Context) -> bool:
        raise NotImplementedError

    def capture(self, ctx: Context) -> dict[str, Any]:
        return self.observe(ctx)

    def apply(self, ctx: Context) -> None:
        raise NotImplementedError

    def verify(self, ctx: Context) -> tuple[bool, str]:
        ok = self.check(ctx)
        return ok, "conferido no sistema" if ok else "estado do sistema diferente do esperado"

    def rollback(self, ctx: Context, before: dict[str, Any]) -> None:
        raise DeployError(f"{self.title}: reversão não disponível.")

    def desired(self, ctx: Context) -> dict[str, Any]:
        return {}

    def observe(self, ctx: Context) -> dict[str, Any]:
        return {}

    def how_to_check(self) -> str:
        return ""


@dataclass
class PlanItem:
    seq: int
    id: str
    category: str
    title: str
    current: Any
    proposed: Any
    impact: str
    undo: str
    reboot: bool
    destructive: bool
    reversible: bool
    confirm: str | None
    already: bool
    how_to_check: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def plan_sha(items: list[dict]) -> str:
    core = [{"id": i["id"], "proposed": i["proposed"], "destructive": i["destructive"]} for i in items]
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class Engine:
    def __init__(self, ctx: Context, build: Callable[[Context, str], list[Step]]) -> None:
        self.ctx = ctx
        self.build = build

    # --------------------------------------------------------------- plano
    def new_run(self, kind: str, *, compat: list[dict] | None = None, installation_id: str | None = None) -> str:
        rid = f"{now()[:10].replace('-', '')}-{uuid.uuid4().hex[:8]}"
        self.ctx.db.x("INSERT INTO runs(id, kind, status, created_at, updated_at, installation_id, host, os_user, "
                      "config_json, inventory_json, compat_json, version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (rid, kind, "planned", now(), now(), installation_id, socket.gethostname(), _os_user(),
                       json.dumps(self.ctx.cfg.to_dict(), ensure_ascii=False),
                       json.dumps(self.ctx.inventory, ensure_ascii=False, default=str),
                       json.dumps(compat or [], ensure_ascii=False), __version__))
        self.ctx.run_id = rid
        return rid

    def plan(self, kind: str) -> list[PlanItem]:
        items = []
        for seq, st in enumerate(self.build(self.ctx, kind)):
            try:
                d = st.describe(self.ctx)
            except Exception as exc:  # noqa: BLE001 - item ainda não pode ser lido (ex.: conta de serviço a criar)
                d = {"current": {"não conferido": str(exc)[:200]}, "proposed": _safe(st.desired, self.ctx),
                     "impact": "", "undo": ""}
            try:
                already = bool(st.check(self.ctx))
            except Exception as exc:  # noqa: BLE001 - o plano mostra o que não pôde ser conferido
                already = False
                d["current"] = {"erro ao conferir": str(exc)[:200]}
            items.append(PlanItem(seq, st.id, st.category, st.title, d.get("current"), d.get("proposed"),
                                  d.get("impact", ""), d.get("undo", ""), st.reboot, st.destructive, st.reversible,
                                  st.confirm, already, st.how_to_check()))
        return items

    def save_plan(self, run_id: str, items: list[PlanItem]) -> str:
        data = [i.as_dict() for i in items]
        sha = plan_sha(data)
        self.ctx.db.set_run(run_id, plan_json=data, plan_sha=sha, status="planned")
        self.ctx.db.x("DELETE FROM steps WHERE run_id = ?", (run_id,))
        for i in items:
            self.ctx.db.x("INSERT INTO steps(run_id, seq, step_id, category, title, status) VALUES (?,?,?,?,?,?)",
                          (run_id, i.seq, i.id, i.category, i.title, "planned"))
        return sha

    # --------------------------------------------------------------- aprovação
    def approve(self, run_id: str, *, items: list[str] | None = None, confirmations: dict[str, str] | None = None,
                expected_sha: str | None = None, user: str | None = None, via: str = "assistente") -> dict:
        run = self.ctx.db.run(run_id)
        if not run or run["status"] != "planned":
            raise NotApproved("Execução inexistente ou já aprovada.")
        if expected_sha and expected_sha != run["plan_sha"]:
            raise NotApproved("O plano mudou desde que foi gerado (o servidor ou as opções mudaram). Gere e revise "
                              "o plano de novo.")
        plan = json.loads(run["plan_json"])
        ids = {p["id"] for p in plan}
        chosen = set(ids if items is None else items)
        unknown = chosen - ids
        if unknown:
            raise NotApproved(f"Itens fora do plano: {', '.join(sorted(unknown))}")
        confirmations = confirmations or {}
        for p in plan:
            if p["id"] in chosen and p.get("confirm") and not p["already"]:
                if (confirmations.get(p["id"]) or "").strip() != p["confirm"]:
                    raise NotApproved(f"{p['title']}: confirme digitando exatamente “{p['confirm']}”.")
        approval = {"user": user or _os_user(), "at": now(), "via": via, "plan_sha": run["plan_sha"],
                    "items": sorted(chosen), "all": items is None,
                    "summary": f"{len(chosen)} de {len(plan)} itens aprovados"}
        for p in plan:
            self.ctx.db.set_step(run_id, p["seq"], approved=int(p["id"] in chosen),
                                 status="pending" if p["id"] in chosen else "not_approved")
        self.ctx.db.set_run(run_id, approval_json=approval, status="approved")
        self.ctx.db.event(run_id, "INFO", f"Plano aprovado por {approval['user']} ({approval['summary']}).")
        return approval

    # --------------------------------------------------------------- execução
    def execute(self, run_id: str) -> str:
        """Executa (ou retoma) uma execução aprovada. Retorna o status final."""
        db, ctx = self.ctx.db, self.ctx
        run = db.run(run_id)
        if not run or run["status"] not in ("approved", "running"):
            raise DeployError("Execução não aprovada.")
        ctx.run_id = run_id
        resuming = run["status"] == "running"
        steps = self.build(ctx, run["kind"])
        rows = db.steps(run_id)
        if [s.id for s in steps] != [r["step_id"] for r in rows]:
            raise DeployError("Os passos desta versão do DEPLOY não correspondem ao plano gravado. Gere um novo plano.")
        db.set_run(run_id, status="running")
        if resuming:
            db.event(run_id, "WARN", "Execução interrompida anteriormente: retomando do último passo confirmado.")
            ctx.log("WARN", "Retomando execução interrompida.")
        applied: list[tuple[Step, dict, int]] = []
        for st, row in zip(steps, rows):
            seq = row["seq"]
            before: dict | None = None
            if row["status"] == "not_approved":
                continue
            if row["status"] in ("done", "already"):
                ok, msg = self._safe_verify(st)
                if not ok:
                    return self._fail(run_id, st, seq, f"Passo confirmado antes não confere mais: {msg}", applied)
                if row["status"] == "done" and row["before_json"]:
                    applied.append((st, json.loads(row["before_json"]), seq))
                continue
            try:
                if row["status"] == "applying" and row["before_json"]:
                    before = json.loads(row["before_json"])          # captura feita antes da interrupção
                else:
                    if st.check(ctx):
                        db.set_step(run_id, seq, status="already", finished_at=now(), verify_msg="já estava assim")
                        ctx.log("INFO", f"{st.title}: já estava assim.")
                        continue
                    before = st.capture(ctx)
                db.set_step(run_id, seq, status="applying", before_json=before, started_at=now(),
                            attempts=int(row.get("attempts") or 0) + 1)
                ctx.log("INFO", f"Aplicando: {st.title}")
                if not (row["status"] == "applying" and st.check(ctx)):
                    st.apply(ctx)
                ok, msg = st.verify(ctx)
            except Exception as exc:  # noqa: BLE001
                ctx.log("ERROR", traceback.format_exc())
                return self._fail(run_id, st, seq, f"{type(exc).__name__}: {exc}", applied, before=before)
            if not ok:
                return self._fail(run_id, st, seq, f"Não confirmado no sistema: {msg}", applied, before=before)
            db.set_step(run_id, seq, status="done", after_json=st.observe(ctx), verify_msg=msg, finished_at=now())
            applied.append((st, before, seq))
        db.set_run(run_id, status="succeeded", message="Concluída: todos os passos aprovados conferidos.")
        db.event(run_id, "INFO", "Execução concluída.")
        return "succeeded"

    def _safe_verify(self, st: Step) -> tuple[bool, str]:
        try:
            return st.verify(self.ctx)
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"

    def _fail(self, run_id: str, st: Step, seq: int, error: str, applied: list, before: dict | None = None) -> str:
        db, ctx = self.ctx.db, self.ctx
        db.set_step(run_id, seq, status="failed", error=error[:4000], finished_at=now())
        db.event(run_id, "ERROR", f"{st.title}: {error[:500]}")
        ctx.log("ERROR", f"{st.title}: {error}")
        if before is not None and st.reversible:      # o passo que falhou pode ter aplicado parte
            applied = applied + [(st, before, seq)]
        failures = []
        for s, bf, sq in reversed(applied):
            if not s.reversible:
                db.set_step(run_id, sq, verify_msg="mantido (passo não reversível)")
                continue
            try:
                s.rollback(ctx, bf)
                db.set_step(run_id, sq, status="rolled_back" if sq != seq else "failed",
                            after_json=s.observe(ctx))
                ctx.log("INFO", f"Revertido: {s.title}")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{s.title}: {exc}")
                db.set_step(run_id, sq, status="rollback_failed", error=str(exc)[:2000])
        status = "rolled_back" if not failures else "failed"
        msg = f"Falha em “{st.title}”. " + ("Alterações revertidas." if not failures else
                                             "Reversão incompleta: " + "; ".join(failures))
        db.set_run(run_id, status=status, message=msg)
        db.event(run_id, "ERROR", msg)
        return status


def _safe(fn, ctx):
    try:
        return fn(ctx)
    except Exception as exc:  # noqa: BLE001
        return {"erro": str(exc)[:200]}


def _os_user() -> str:
    try:
        import os
        dom = os.environ.get("USERDOMAIN")
        return f"{dom}\\{getpass.getuser()}" if dom else getpass.getuser()
    except Exception:  # noqa: BLE001
        return "?"
