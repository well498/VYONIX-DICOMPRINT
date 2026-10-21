"""Atualização (backup antes da migração) e desinstalação (dados preservados)."""

from __future__ import annotations

import hashlib
import os
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from vyonix_deploy.engine import Context, Step
from vyonix_deploy.errors import DeployError
from vyonix_deploy.steps import postgres as pg
from vyonix_deploy.steps.core import DB_NAME
from vyonix_deploy.steps.firewall import FirewallRuleStep
from vyonix_deploy.steps.services import SC, query_service, stop_service
from vyonix_deploy.steps.shortcuts import ShortcutsStep
from vyonix_deploy.sysrun import IS_WINDOWS, powershell, run


class BackupStep(Step):
    """Cópia do banco (pg_dump, formato custom) e da configuração antes de migrar. Não apaga nada."""

    category = "banco"
    id = "backup.before_update"
    title = "Backup do banco e da configuração antes da atualização"
    reversible = False

    def _target(self, ctx: Context) -> Path:
        return ctx.paths.backups / f"antes-da-atualizacao-{ctx.run_id}"

    def desired(self, ctx: Context) -> dict:
        return {"folder": str(ctx.paths.backups), "database": DB_NAME, "format": "pg_dump custom"}

    def observe(self, ctx: Context) -> dict:
        t = self._target(ctx)
        man = t / "backup.json"
        return {"folder": str(t), "done": man.exists(),
                **(json.loads(man.read_text(encoding="utf-8")) if man.exists() else {})}

    def describe(self, ctx: Context) -> dict:
        return {"current": {"backups": sorted(p.name for p in ctx.paths.backups.glob("antes-da-atualizacao-*"))
                            if ctx.paths.backups.exists() else []},
                "proposed": self.desired(ctx), "impact": "Somente leitura do banco; grava a cópia na pasta de backups.",
                "undo": "Não se aplica (a cópia é mantida)."}

    def check(self, ctx: Context) -> bool:
        return self.observe(ctx)["done"]

    def apply(self, ctx: Context) -> None:
        t = self._target(ctx)
        t.mkdir(parents=True, exist_ok=True)
        dump = t / f"{DB_NAME}.dump"
        exe = ctx.paths.pg_bin / ("pg_dump.exe" if IS_WINDOWS else "pg_dump")
        env = {**os.environ, "PGPASSWORD": pg.superuser_password(ctx)}
        r = run([str(exe), "-h", "127.0.0.1", "-p", str(ctx.cfg.pg_port), "-U", pg.SUPERUSER, "-Fc", "-f", str(dump),
                 DB_NAME], timeout=3600, env=env)
        if not r.ok:
            raise DeployError("pg_dump falhou: " + (r.err or r.out).strip()[-500:])
        for name in ("config.json", "secrets.json"):
            src = ctx.paths.data_dir / name
            if src.exists():
                shutil.copy2(src, t / name)
        h = hashlib.sha256(dump.read_bytes()).hexdigest()
        (t / "backup.json").write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                   "dump": dump.name, "bytes": dump.stat().st_size, "sha256": h},
                                                  indent=2), encoding="utf-8")

    def verify(self, ctx: Context) -> tuple[bool, str]:
        o = self.observe(ctx)
        if not o["done"]:
            return False, "backup ausente"
        dump = self._target(ctx) / o["dump"]
        if hashlib.sha256(dump.read_bytes()).hexdigest() != o["sha256"]:
            return False, "resumo do backup não confere"
        exe = ctx.paths.pg_bin / ("pg_restore.exe" if IS_WINDOWS else "pg_restore")
        if exe.exists():
            r = run([str(exe), "--list", str(dump)], timeout=600)
            if not r.ok:
                return False, "pg_restore não leu o backup"
        return True, f"backup gravado e legível ({o['bytes']} bytes, SHA-256 {o['sha256'][:12]}…)"

    def how_to_check(self) -> str:
        return "pg_restore --list <arquivo .dump>"


def update_steps(ctx: Context, install: list[Step]) -> list[Step]:
    out: list[Step] = []
    for st in install:
        out.append(st)
        if st.id == f"running.{pg.SERVICE}":
            out.append(BackupStep())
    return out


class ServiceRemovedStep(Step):
    category = "servico"
    reversible = False

    def __init__(self, name: str) -> None:
        self.name = name
        self.id = f"remove.service.{name}"
        self.title = f"Remover o serviço {name}"

    def observe(self, ctx: Context) -> dict:
        q = query_service(self.name) if IS_WINDOWS else None
        return {"name": self.name, "exists": bool(q), "state": q["state"] if q else None}

    def desired(self, ctx: Context) -> dict:
        return {"name": self.name, "exists": False}

    def describe(self, ctx: Context) -> dict:
        return {"current": self.observe(ctx), "proposed": self.desired(ctx),
                "impact": "Para e remove o serviço. Dados e configurações são mantidos.",
                "undo": "Reinstale o VYONIX para registrar o serviço de novo."}

    def check(self, ctx: Context) -> bool:
        return not self.observe(ctx)["exists"]

    def apply(self, ctx: Context) -> None:
        stop_service(self.name)
        run([SC, "delete", self.name], check=True)


class RuleRemovedStep(FirewallRuleStep):
    reversible = False

    def __init__(self, key: str, service: str, port: int) -> None:
        super().__init__(key, service, port, None)
        self.id = f"remove.firewall.{key}"
        self.title = f"Remover a regra de firewall {self.name}"

    def desired(self, ctx: Context) -> dict:
        return {"id": self.rule_id, "exists": False}

    def check(self, ctx: Context) -> bool:
        return not self.observe(ctx).get("exists")

    def apply(self, ctx: Context) -> None:
        powershell("Get-NetFirewallRule -Name $A.id -ErrorAction SilentlyContinue | Remove-NetFirewallRule",
                   {"id": self.rule_id}, as_json=False)


class ShortcutsRemovedStep(ShortcutsStep):
    id = "remove.shortcuts"
    title = "Remover os atalhos do VYONIX"
    reversible = False

    def check(self, ctx: Context) -> bool:
        return not self.observe(ctx)["present"]

    def apply(self, ctx: Context) -> None:
        for n in self.items:
            (self.folder / n).unlink(missing_ok=True)
        try:
            self.folder.rmdir()
        except OSError:
            pass


def uninstall_steps(ctx: Context) -> list[Step]:
    from vyonix_deploy.plans import CORE_SVC, WORKER_SVC
    p = ctx.paths
    return [ServiceRemovedStep(CORE_SVC), ServiceRemovedStep(WORKER_SVC), ServiceRemovedStep(pg.SERVICE),
            RuleRemovedStep("core-https", "Core HTTPS", ctx.cfg.https_port),
            ShortcutsRemovedStep(ctx.cfg.https_port, p.install_dir / "vyonix-deploy.exe", p.reports)]
