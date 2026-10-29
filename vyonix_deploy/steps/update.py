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
    reversible = False

    def __init__(self, label: str = "antes-da-atualizacao", title: str = "antes da atualização") -> None:
        self.label = label
        self.id = "backup.before_update" if label == "antes-da-atualizacao" else f"backup.{label}"
        self.title = f"Backup do banco e da configuração {title}"

    def _target(self, ctx: Context) -> Path:
        return ctx.paths.backups / f"{self.label}-{ctx.run_id}"

    def desired(self, ctx: Context) -> dict:
        return {"folder": str(ctx.paths.backups), "database": DB_NAME, "format": "pg_dump custom"}

    def observe(self, ctx: Context) -> dict:
        t = self._target(ctx)
        man = t / "backup.json"
        return {"folder": str(t), "done": man.exists(),
                **(json.loads(man.read_text(encoding="utf-8")) if man.exists() else {})}

    def describe(self, ctx: Context) -> dict:
        return {"current": {"backups": sorted(p.name for p in ctx.paths.backups.glob(f"{self.label}-*"))
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
        from vyonix_deploy.steps.shortcuts import LEGACY
        for n in (*self.items, *LEGACY):
            (self.folder / n).unlink(missing_ok=True)
        try:
            self.folder.rmdir()
        except OSError:
            pass


def uninstall_steps(ctx: Context) -> list[Step]:
    from vyonix_deploy.plans import CORE_SVC, WORKER_SVC
    p = ctx.paths
    from vyonix_deploy.steps import pacs
    return [ServiceRemovedStep(pacs.SERVICE), ServiceRemovedStep(CORE_SVC), ServiceRemovedStep(WORKER_SVC),
            ServiceRemovedStep(pg.SERVICE),
            RuleRemovedStep("core-https", "Core HTTPS", ctx.cfg.https_port),
            RuleRemovedStep("pacs-dicom", "PACS DICOM", pacs.DICOM_PORT),
            RuleRemovedStep("pacs-qr", "PACS consulta DICOM", pacs.QR_PORT),
            RuleRemovedStep("core-lan", "Core HTTPS (rede local, perfil Público)", ctx.cfg.https_port),
            RuleRemovedStep("pacs-dicom-lan", "PACS DICOM (rede local, perfil Público)", pacs.DICOM_PORT),
            RuleRemovedStep("pacs-qr-lan", "PACS consulta DICOM (rede local, perfil Público)", pacs.QR_PORT),
            ShortcutsRemovedStep(ctx.cfg.https_port, p.install_dir / "vyonix-deploy.exe", p.reports)]


class ServiceStoppedStep(Step):
    category = "servico"

    def __init__(self, name: str) -> None:
        self.name = name
        self.id = f"stopped.{name}"
        self.title = f"Parar {name} durante a restauração"

    def observe(self, ctx: Context) -> dict:
        q = query_service(self.name) if IS_WINDOWS else None
        return {"name": self.name, "state": q["state"] if q else "Ausente"}

    def desired(self, ctx: Context) -> dict:
        return {"name": self.name, "state": "Stopped"}

    def check(self, ctx: Context) -> bool:
        return self.observe(ctx)["state"] in ("Stopped", "Ausente")

    def apply(self, ctx: Context) -> None:
        stop_service(self.name)

    def rollback(self, ctx: Context, before: dict) -> None:
        if before.get("state") == "Running":
            run([SC, "start", self.name])


def list_backups(paths) -> list[dict]:
    out = []
    if not paths.backups.exists():
        return out
    for d in sorted(paths.backups.iterdir(), reverse=True):
        m = d / "backup.json"
        if m.exists():
            out.append({"name": d.name, **json.loads(m.read_text(encoding="utf-8"))})
    return out


class RestoreBackupStep(Step):
    """Restaura o banco do VYONIX a partir de um backup do DEPLOY. **Destrutivo**: substitui os dados
    atuais. Exige a confirmação digitada com o nome do backup (segunda confirmação, além da aprovação
    do plano), e o plano sempre faz antes um backup do estado atual."""

    category = "banco"
    destructive = True
    reversible = False

    def __init__(self, backup: str) -> None:
        self.backup = backup
        self.id = "backup.restore"
        self.title = f"Restaurar o banco do backup {backup}"
        self.confirm = f"RESTAURAR {backup}"

    def _dir(self, ctx: Context) -> Path:
        d = (ctx.paths.backups / self.backup).resolve()
        if d.parent != ctx.paths.backups.resolve() or not (d / "backup.json").exists():
            raise DeployError(f"Backup inexistente: {self.backup}")
        return d

    def observe(self, ctx: Context) -> dict:
        marker = ctx.paths.deploy_dir / f"restaurado-{ctx.run_id}.json"
        return {"backup": self.backup, "restored_in_this_run": marker.exists()}

    def desired(self, ctx: Context) -> dict:
        return {"backup": self.backup}

    def describe(self, ctx: Context) -> dict:
        info = json.loads((self._dir(ctx) / "backup.json").read_text(encoding="utf-8"))
        return {"current": {"backup": self.backup, **info}, "proposed": self.desired(ctx),
                "impact": "SUBSTITUI os dados atuais do VYONIX pelos do backup. Um backup do estado atual é feito "
                          "antes, no mesmo plano.",
                "undo": "Restaurar o backup feito no início desta execução."}

    def check(self, ctx: Context) -> bool:
        return self.observe(ctx)["restored_in_this_run"]

    def apply(self, ctx: Context) -> None:
        d = self._dir(ctx)
        info = json.loads((d / "backup.json").read_text(encoding="utf-8"))
        dump = d / info["dump"]
        if hashlib.sha256(dump.read_bytes()).hexdigest() != info["sha256"]:
            raise DeployError("O arquivo de backup foi alterado (SHA-256 não confere). Nada foi restaurado.")
        exe = ctx.paths.pg_bin / ("pg_restore.exe" if IS_WINDOWS else "pg_restore")
        env = {**os.environ, "PGPASSWORD": pg.superuser_password(ctx)}
        r = run([str(exe), "-h", "127.0.0.1", "-p", str(ctx.cfg.pg_port), "-U", pg.SUPERUSER, "-d", DB_NAME,
                 "--clean", "--if-exists", "--single-transaction", "--no-owner", "--role=vyonix_owner", str(dump)],
                timeout=7200, env=env)
        if not r.ok:
            raise DeployError("pg_restore falhou (nada foi alterado: transação única): "
                              + (r.err or r.out).strip()[-600:])
        (ctx.paths.deploy_dir / f"restaurado-{ctx.run_id}.json").write_text(
            json.dumps({"backup": self.backup, "sha256": info["sha256"],
                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}), encoding="utf-8")

    def how_to_check(self) -> str:
        return "Conferir os dados no VYONIX após a restauração"


def restore_steps(ctx: Context, backup: str) -> list[Step]:
    from vyonix_deploy.plans import CORE_SVC, WORKER_SVC
    from vyonix_deploy.steps import core
    from vyonix_deploy.steps.services import ServiceRunningStep
    return [ServiceRunningStep(pg.SERVICE, "VYONIX PostgreSQL", probe=pg.can_connect),
            BackupStep("antes-da-restauracao", "antes da restauração"),
            ServiceStoppedStep(CORE_SVC), ServiceStoppedStep(WORKER_SVC), RestoreBackupStep(backup),
            ServiceRunningStep(CORE_SVC, "VYONIX Core", probe=core.health, timeout=120),
            ServiceRunningStep(WORKER_SVC, "VYONIX Worker")]
