"""Operações de alto nível do DEPLOY (usadas pela linha de comando e pelo assistente)."""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from vyonix_deploy import compat, inventory, report
from vyonix_deploy.config import DeployConfig
from vyonix_deploy.db import DeployDB, now
from vyonix_deploy.engine import Context, Engine
from vyonix_deploy.errors import Blocked, DeployError
from vyonix_deploy.paths import Paths, default_paths
from vyonix_deploy.plans import build
from vyonix_deploy.secrets import DeploySecrets


class Deploy:
    def __init__(self, paths: Paths | None = None, *, log: Callable[[str, str], None] | None = None,
                 build_fn=build) -> None:
        self.paths = paths or default_paths()
        self.paths.deploy_dir.mkdir(parents=True, exist_ok=True)
        self.db = DeployDB(self.paths.db_file)
        self.log = log or (lambda level, msg: None)
        self.build_fn = build_fn
        self.secrets = DeploySecrets(self.paths.deploy_dir)

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ configuração gravada
    def saved_config(self) -> DeployConfig | None:
        raw = self.db.meta("config")
        return DeployConfig.from_dict(json.loads(raw)) if raw else None

    def save_config(self, cfg: DeployConfig) -> None:
        d = cfg.to_dict()
        d["network"] = {**d["network"], "confirmed": False}       # confirmação vale só para aquela execução
        self.db.meta("config", json.dumps(d, ensure_ascii=False))

    def context(self, cfg: DeployConfig, *, inv: dict | None = None, extra: dict | None = None) -> Context:
        return Context(cfg=cfg, paths=self.paths, db=self.db, inventory=inv or {}, secrets=self.secrets,
                       log=self._log, extra=dict(extra or {}))

    def _log(self, level: str, msg: str) -> None:
        self.db.event(getattr(self, "_run", None), level, msg[:4000])
        self.log(level, msg)

    def secret_values(self, ctx: Context | None = None) -> list[str]:
        vals = []
        for store in (self.secrets, _core_store(self.paths)):
            try:
                for name in store._load():
                    v = store.get(name)
                    if v:
                        vals.append(v.decode("utf-8", "ignore"))
            except Exception:  # noqa: BLE001
                continue
        if ctx:
            vals += [str(v) for k, v in ctx.extra.items() if "password" in k and v]
        return vals

    # ------------------------------------------------------------------ inventário e plano
    def inventory(self) -> dict:
        return inventory.collect(self.paths)

    def plan(self, kind: str, cfg: DeployConfig, *, extra: dict | None = None) -> dict[str, Any]:
        cfg.validate()
        inv = self.inventory()
        mode = "diagnose" if kind == "diagnose" else ("install" if kind == "install" else "other")
        findings = compat.evaluate(inv, cfg, mode=mode)
        ctx = self.context(cfg, inv=inv, extra=extra)
        eng = Engine(ctx, self.build_fn)
        rid = eng.new_run(kind, compat=[f.as_dict() for f in findings])
        self._run = rid
        blk = compat.blockers(findings)
        if blk:
            self.db.set_run(rid, status="blocked", message="Impeditivos: " + "; ".join(f"{b.title}: {b.detail}"
                                                                                       for b in blk))
            rep = report.generate(self.db, self.paths, rid, findings=[f.as_dict() for f in findings],
                                  secrets=self.secret_values(ctx))
            raise Blocked(json.dumps({"run_id": rid, "blockers": [b.as_dict() for b in blk], "report": rep},
                                     ensure_ascii=False))
        items = eng.plan(kind)
        sha = eng.save_plan(rid, items)
        return {"run_id": rid, "kind": kind, "plan_sha": sha, "items": [i.as_dict() for i in items],
                "compatibility": [f.as_dict() for f in findings], "config": cfg.to_dict()}

    # ------------------------------------------------------------------ aprovação e execução
    def approve(self, run_id: str, cfg: DeployConfig, **kw) -> dict:
        return Engine(self.context(cfg), self.build_fn).approve(run_id, **kw)

    def execute(self, run_id: str, *, extra: dict | None = None) -> dict[str, Any]:
        run = self.db.run(run_id)
        if run is None:
            raise DeployError("Execução inexistente.")
        cfg = DeployConfig.from_dict(json.loads(run["config_json"]))
        inv = json.loads(run["inventory_json"] or "{}")
        ctx = self.context(cfg, inv=inv, extra=extra)
        self._run = run_id
        with self.lock():
            status = Engine(ctx, self.build_fn).execute(run_id)
        if status == "succeeded" and run["kind"] != "uninstall":
            self.save_config(cfg)
        observed, desired = {}, {}
        for st in self.build_fn(ctx, run["kind"]):
            try:
                observed[st.id] = st.observe(ctx)
                desired[st.id] = st.desired(ctx)
            except Exception as exc:  # noqa: BLE001
                observed[st.id] = {"erro": str(exc)[:200]}
        rep = report.generate(self.db, self.paths, run_id, observed=observed, desired=desired,
                              secrets=self.secret_values(ctx))
        return {"run_id": run_id, "status": status, "message": self.db.run(run_id)["message"], "report": rep}

    def resume_pending(self, *, extra: dict | None = None) -> dict | None:
        run = self.db.unfinished()
        if not run:
            return None
        return self.execute(run["id"], extra=extra)

    def report_only(self, run_id: str) -> dict:
        return report.generate(self.db, self.paths, run_id, secrets=self.secret_values())

    # ------------------------------------------------------------------ diagnóstico e reparo
    def diagnose(self, cfg: DeployConfig | None = None) -> dict:
        from vyonix_deploy.diagnose import diagnose
        cfg = cfg or self.saved_config()
        if cfg is None:
            raise DeployError("Nenhuma instalação registrada pelo DEPLOY neste servidor.")
        inv = self.inventory()
        ctx = self.context(cfg, inv=inv)
        eng = Engine(ctx, self.build_fn)
        rid = eng.new_run("diagnose", compat=[f.as_dict() for f in compat.evaluate(inv, cfg, mode="diagnose")])
        self._run = rid
        result = diagnose(ctx)
        items = eng.plan("install")
        eng.save_plan(rid, items)
        bad = {s for p in result["problems"] for s in p["steps"]}
        for row in self.db.steps(rid):
            ok = next((x["ok"] for x in result["status"] if x["id"] == row["step_id"]), True)
            self.db.set_step(rid, row["seq"], status="diag_problem" if (not ok or row["step_id"] in bad) else "diag_ok",
                             verify_msg="conforme" if ok else "divergente")
        self.db.set_run(rid, status="diagnosed", message=f"{len(result['problems'])} problema(s) encontrado(s).")
        rep = report.generate(self.db, self.paths, rid, observed=result["observed"],
                              extra_tests=[{"name": p["title"], "result": "Reprovado", "detail": p["detail"]}
                                           for p in result["problems"]], secrets=self.secret_values(ctx))
        return {**result, "run_id": rid, "report": rep}

    def repair_plan(self, diagnosis: dict, cfg: DeployConfig | None = None) -> tuple[dict, list[str], DeployConfig]:
        cfg = cfg or self.saved_config()
        changed = dict(cfg.to_dict())
        for p in diagnosis["problems"]:
            if p.get("config_change"):
                changed.update(p["config_change"])
        new_cfg = DeployConfig.from_dict(changed)
        plan = self.plan("repair", new_cfg)
        want = {s for p in diagnosis["problems"] for s in p["steps"]}
        ids = [i["id"] for i in plan["items"] if not i["already"] or i["id"] in want]
        return plan, ids, new_cfg

    @contextmanager
    def lock(self):
        f = open(self.paths.deploy_dir / "deploy.lock", "a+")
        try:
            if sys.platform == "win32":
                import msvcrt
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    raise DeployError("Outra execução do DEPLOY está em andamento.") from None
            else:
                import fcntl
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    raise DeployError("Outra execução do DEPLOY está em andamento.") from None
            yield
        finally:
            f.close()


def _core_store(paths: Paths):
    from vyonix.secrets import SecretStore
    return SecretStore(paths.data_dir)


def load_config(path: str | None, saved: DeployConfig | None) -> DeployConfig:
    if path:
        return DeployConfig.load(path)
    return saved or DeployConfig()


def dump_plan_file(path: str, plan: dict) -> None:
    Path(path).write_text(json.dumps({**plan, "format": "vyonix-deploy-plan/1", "generated_at": now()},
                                     ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def env_secrets() -> dict[str, str]:
    out = {}
    for env, key in (("VYONIX_ADMIN_PASSWORD", "admin_password"), ("VYONIX_PFX_PASSWORD", "pfx_password")):
        if os.environ.get(env):
            out[key] = os.environ[env]
    return out
