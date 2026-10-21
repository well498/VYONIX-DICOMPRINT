"""Diagnóstico — **somente leitura**. Compara o estado real com o último manifesto e com o que cada
passo espera, e aponta: serviços parados, regras de firewall ausentes ou alteradas, conflitos de
porta, certificados vencidos ou perto de vencer, permissões, pastas inacessíveis, banco (conexão,
integridade, espaço), relatórios alterados fora do VYONIX. O reparo é uma execução comum (plano +
aprovação + PDF)."""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from vyonix_deploy import report
from vyonix_deploy.engine import Context
from vyonix_deploy.inventory import free_port, port_owner
from vyonix_deploy.plans import install_steps


@dataclass
class Problem:
    id: str
    severity: str            # erro | alerta
    title: str
    detail: str
    repair: str              # o que o reparo fará
    steps: list[str] = field(default_factory=list)
    config_change: dict[str, Any] | None = None
    destructive: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def diagnose(ctx: Context) -> dict[str, Any]:
    problems: list[Problem] = []
    observed: dict[str, Any] = {}
    status: list[dict] = []
    manifest = report.latest_manifest(ctx.db)
    desired_prev = {it["id"]: it.get("desired") for it in (manifest or {}).get("items", [])}
    for st in install_steps(ctx):
        try:
            ok = st.check(ctx)
            obs = st.observe(ctx)
        except Exception as exc:  # noqa: BLE001
            ok, obs = False, {"erro": f"{type(exc).__name__}: {str(exc)[:200]}"}
        observed[st.id] = obs
        status.append({"id": st.id, "title": st.title, "category": st.category, "ok": ok})
        if not ok:
            problems.append(_explain(st, obs))
        prev = desired_prev.get(st.id)
        if ok and prev is not None and prev != st.desired(ctx):
            problems.append(Problem(f"drift.{st.id}", "alerta", f"{st.title}: configuração diferente do último "
                                    "manifesto", "O estado desejado mudou desde a última execução registrada.",
                                    "Registrar o estado atual num novo manifesto.", [st.id]))
    # porta HTTPS ocupada por outro processo
    own = port_owner(ctx.inventory, ctx.cfg.https_port)
    if own and (own.get("process") or "").lower() not in ("vyonixplatform", "system"):
        new = free_port(ctx.inventory, ctx.cfg.https_port + 1, avoid={ctx.cfg.pg_port})
        problems.append(Problem(f"port.{ctx.cfg.https_port}", "erro", f"Porta {ctx.cfg.https_port} ocupada",
                                f"Em uso por {own.get('process')} (PID {own.get('pid')}); o VYONIX Core não consegue "
                                "atender.", f"Mudar o HTTPS do VYONIX para a porta livre {new} (firewall, configuração "
                                "e atalhos acompanham).", ["firewall.core-https", "core.database",
                                                           "running.VyonixCore", "shortcuts"],
                                config_change={"https_port": new}))
    # certificado
    cert = observed.get("https.certificate") or {}
    if cert.get("not_after"):
        left = datetime.fromisoformat(cert["not_after"]) - datetime.now(timezone.utc)
        if 0 < left.days <= 60:
            problems.append(Problem("cert.expiring", "alerta", "Certificado HTTPS perto de vencer",
                                    f"Vence em {left.days} dia(s).", "Renovar o certificado.", ["https.certificate"]))
    # espaço em disco da pasta de dados
    try:
        free = shutil.disk_usage(ctx.paths.data_dir if ctx.paths.data_dir.exists() else ctx.paths.deploy_dir).free
        if free < 10 * 1024 ** 3:
            problems.append(Problem("disk.low", "erro" if free < 2 * 1024 ** 3 else "alerta", "Pouco espaço em disco",
                                    f"{free / 1024 ** 3:.1f} GB livres na pasta de dados.",
                                    "Liberar espaço ou mover a pasta de dados (intervenção manual).", []))
    except OSError:
        pass
    # banco: integridade básica e tamanho
    db_info = _database_health(ctx)
    if db_info.get("problem"):
        problems.append(Problem("database", "erro", "Banco de dados", db_info["problem"],
                                "Conferir o serviço VyonixPostgreSQL e reaplicar a configuração do banco.",
                                ["running.VyonixPostgreSQL", "core.database"]))
    # relatórios e manifestos
    for msg in report.verify_chain(ctx.db):
        problems.append(Problem("reports.integrity", "alerta", "Relatório alterado fora do VYONIX", msg,
                                "Os arquivos originais não são reescritos; o próximo relatório registra a ocorrência.",
                                []))
    return {"problems": [p.as_dict() for p in _dedupe(problems)], "status": status, "observed": observed,
            "database": db_info, "manifest_run": (manifest or {}).get("run_id"),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _dedupe(ps: list[Problem]) -> list[Problem]:
    seen, out = set(), []
    for p in ps:
        if p.id not in seen:
            seen.add(p.id)
            out.append(p)
    return out


def _explain(st, obs: dict) -> Problem:
    cat = st.category
    if st.id.startswith("running."):
        return Problem(st.id, "erro", f"{st.title.replace('Iniciar ', '')} parado ou sem resposta",
                       f"Estado: {obs.get('state')}.", "Iniciar o serviço e conferir o funcionamento.", [st.id])
    if st.id.startswith("service."):
        detail = "serviço ausente" if not obs.get("exists") else "configuração do serviço diferente da esperada"
        return Problem(st.id, "erro", st.title, detail, "Registrar o serviço novamente com a configuração do VYONIX.",
                       [st.id])
    if cat == "firewall":
        detail = "regra ausente" if not obs.get("exists") else "regra alterada (porta, perfil, programa ou origem)"
        return Problem(st.id, "erro", st.title, detail, "Recriar a regra do VYONIX (outras regras não são tocadas).",
                       [st.id])
    if st.id.startswith("acl.") or st.id.startswith("grant."):
        return Problem(st.id, "erro", st.title, "permissões diferentes das definidas pelo VYONIX",
                       "Reaplicar as permissões mínimas.", [st.id])
    if st.id.startswith("dir."):
        return Problem(st.id, "erro", st.title, "pasta ausente ou inacessível", "Criar a pasta.", [st.id])
    if cat == "https":
        return Problem(st.id, "erro", st.title, "certificado ausente, vencido ou a menos de 30 dias do vencimento",
                       "Gerar ou instalar o certificado.", [st.id, "running.VyonixCore"])
    if st.id == "app.files":
        return Problem(st.id, "erro", st.title, f"arquivos ausentes: {obs.get('missing')}",
                       "Executar novamente o VYONIX_Setup_x64.exe (intervenção manual).", [])
    return Problem(st.id, "erro", st.title, str(obs)[:300], "Reaplicar o item.", [st.id])


def _database_health(ctx: Context) -> dict[str, Any]:
    from vyonix_deploy.steps import postgres as pg
    ok, msg = pg.can_connect(ctx)
    if not ok:
        return {"connect": False, "problem": msg}
    import psycopg
    try:
        with psycopg.connect(pg.admin_url(ctx), connect_timeout=5) as c:
            size = c.execute("SELECT pg_database_size('vyonix')").fetchone()[0] if c.execute(
                "SELECT 1 FROM pg_database WHERE datname='vyonix'").fetchone() else None
            ver = c.execute("SHOW server_version").fetchone()[0]
            checksums = c.execute("SHOW data_checksums").fetchone()[0]
            fails = c.execute("SELECT coalesce(sum(checksum_failures),0) FROM pg_stat_database").fetchone()[0]
        out = {"connect": True, "version": ver, "size_bytes": size, "data_checksums": checksums,
               "checksum_failures": int(fails)}
        if int(fails):
            out["problem"] = f"{fails} falha(s) de checksum de página registradas: verifique o disco e os backups."
        return out
    except Exception as exc:  # noqa: BLE001
        return {"connect": True, "problem": f"{type(exc).__name__}: {str(exc)[:200]}"}
