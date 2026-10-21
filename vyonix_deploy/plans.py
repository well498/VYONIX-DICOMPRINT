"""Passos de cada tipo de execução, na ordem em que são aplicados."""

from __future__ import annotations

from vyonix_deploy.engine import Context, Step
from vyonix_deploy.steps import core, postgres as pg
from vyonix_deploy.steps.files import ADMINS, SYSTEM, AclGrantStep, AclStep, DirectoryStep, FilesPresentStep
from vyonix_deploy.steps.firewall import FirewallRuleStep
from vyonix_deploy.steps.network import StaticIpStep
from vyonix_deploy.steps.services import ServiceRunningStep, ServiceStep
from vyonix_deploy.steps.shortcuts import ShortcutsStep
from vyonix_deploy.steps.tls import TlsCertificateStep

CORE_SVC = "VyonixCore"
WORKER_SVC = "VyonixWorker"
KINDS = {"install": "Nova instalação", "repair": "Reparo", "update": "Atualização", "uninstall": "Desinstalação",
         "reconfigure": "Reconfigurar servidor"}

REQUIRED_FILES = ["VyonixPlatform.exe", "vyonix-deploy.exe", "VERSION.txt", r"pgsql\bin\initdb.exe",
                  r"pgsql\bin\pg_ctl.exe", r"pgsql\bin\postgres.exe", r"pgsql\bin\pg_dump.exe", r"web\index.html"]


def platform_version() -> str:
    from vyonix import __version__
    return __version__


def install_steps(ctx: Context) -> list[Step]:
    p, cfg = ctx.paths, ctx.cfg
    vsvc = lambda n: f"NT SERVICE\\{n}"  # noqa: E731
    steps: list[Step] = [
        FilesPresentStep(p.install_dir, REQUIRED_FILES, platform_version()),
        DirectoryStep("data", p.data_dir, "de dados do VYONIX"),
        DirectoryStep("pgroot", p.pg_data.parent, "do PostgreSQL do VYONIX"),
        DirectoryStep("backups", p.backups, "de backups"),
        DirectoryStep("reports", p.reports, "de relatórios técnicos"),
        DirectoryStep("licensing", p.licensing, "de licenciamento"),
        TlsCertificateStep(p.data_dir, cfg.tls_pfx),
        pg.PgClusterStep(p.pg_bin, p.pg_data),
        ServiceStep(pg.SERVICE, "VYONIX PostgreSQL", "Banco de dados do VYONIX (somente conexões locais).",
                    pg.pg_service_binpath(p.pg_bin, p.pg_data), delayed=False),
        ServiceStep(CORE_SVC, "VYONIX Core", "API e interface web do VYONIX (HTTPS).",
                    core.service_binpath(p.install_dir, "core", p.data_dir), depends=[pg.SERVICE]),
        ServiceStep(WORKER_SVC, "VYONIX Worker", "Processador de eventos do VYONIX.",
                    core.service_binpath(p.install_dir, "worker", p.data_dir), depends=[pg.SERVICE]),
        AclStep("pgdata", p.pg_data, "dados do PostgreSQL", [(SYSTEM, "F"), (ADMINS, "F"), (vsvc(pg.SERVICE), "F")]),
        AclStep("data", p.data_dir, "dados do VYONIX", [(SYSTEM, "F"), (ADMINS, "F"), (vsvc(CORE_SVC), "M"),
                                                        (vsvc(WORKER_SVC), "M")]),
        AclStep("deploy", p.deploy_dir, "DEPLOY e relatórios", [(SYSTEM, "F"), (ADMINS, "F")]),
        AclStep("backups", p.backups, "backups", [(SYSTEM, "F"), (ADMINS, "F")]),
        AclGrantStep("licensing.core", p.licensing, "licenciamento", vsvc(CORE_SVC), "M"),
        AclGrantStep("licensing.worker", p.licensing, "licenciamento", vsvc(WORKER_SVC), "M"),
        ServiceRunningStep(pg.SERVICE, "VYONIX PostgreSQL", probe=pg.can_connect),
        core.CoreDatabaseStep(),
        FirewallRuleStep("core-https", "Core HTTPS", cfg.https_port, str(p.core_exe), cfg.firewall_sources),
        ServiceRunningStep(CORE_SVC, "VYONIX Core", probe=core.health, timeout=120),
        ServiceRunningStep(WORKER_SVC, "VYONIX Worker"),
    ]
    if cfg.shortcuts:
        steps.append(ShortcutsStep(cfg.https_port, p.install_dir / "vyonix-deploy.exe", p.reports))
    if cfg.network.mode == "static":
        steps.append(StaticIpStep(cfg.network))
    return steps


def build(ctx: Context, kind: str) -> list[Step]:
    if kind in ("install", "repair", "reconfigure"):
        return install_steps(ctx)
    if kind == "update":
        from vyonix_deploy.steps.update import update_steps
        return update_steps(ctx, install_steps(ctx))
    if kind == "uninstall":
        from vyonix_deploy.steps.update import uninstall_steps
        return uninstall_steps(ctx)
    raise ValueError(f"Tipo de execução desconhecido: {kind}")
