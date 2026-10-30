"""PostgreSQL 17 do VYONIX: instância própria (serviço ``VyonixPostgreSQL``), só em 127.0.0.1, porta
escolhida no plano, autenticação scram-sha-256. A senha do superusuário é aleatória e guardada com
DPAPI de máquina na pasta do DEPLOY; nunca vai para relatório, manifesto ou banco do DEPLOY."""

from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path

from vyonix_deploy.engine import Context, Step
from vyonix_deploy.errors import DeployError
from vyonix_deploy.sysrun import run

SUPERUSER = "vyonix_admin"
SERVICE = "VyonixPostgreSQL"
HBA = ("# Gerado pelo VYONIX DEPLOY: somente conexões locais, com senha (scram-sha-256).\n"
       "host all all 127.0.0.1/32 scram-sha-256\n"
       "host all all ::1/128 scram-sha-256\n")
MARK = "# VYONIX DEPLOY"


def superuser_password(ctx: Context) -> str:
    return ctx.secrets.get_or_create_text("pg_superuser")


def admin_url(ctx: Context, db: str = "postgres") -> str:
    from urllib.parse import quote
    return f"postgresql://{SUPERUSER}:{quote(superuser_password(ctx), safe='')}@127.0.0.1:{ctx.cfg.pg_port}/{db}"


def can_connect(ctx: Context) -> tuple[bool, str]:
    try:
        import psycopg
        with psycopg.connect(admin_url(ctx), connect_timeout=5) as c:
            v = c.execute("SHOW server_version").fetchone()[0]
        return True, f"PostgreSQL {v} aceita conexões em 127.0.0.1:{ctx.cfg.pg_port}"
    except Exception as exc:  # noqa: BLE001
        return False, f"sem conexão: {type(exc).__name__}: {str(exc)[:200]}"


class PgClusterStep(Step):
    category = "banco"
    id = "postgres.cluster"
    title = "Inicializar o PostgreSQL do VYONIX"

    def __init__(self, pg_bin: Path, data: Path) -> None:
        self.bin = Path(pg_bin)
        self.data = Path(data)

    def _conf(self, ctx: Context) -> str:
        return (f"{MARK}\nport = {int(ctx.cfg.pg_port)}\nlisten_addresses = '127.0.0.1'\n"
                "password_encryption = 'scram-sha-256'\n"
                # Sem o coletor de log (processo "syslogger"): no Windows ele sobrevivia ao processo principal do banco
                # encerrado à força e impedia o serviço de subir de novo (CI 40951093428, critério 2.10). Os registros
                # vão para o Log de Eventos do Windows (Aplicativo, origem "VYONIX PostgreSQL").
                "logging_collector = off\nlog_destination = 'eventlog'\nevent_source = 'VYONIX PostgreSQL'\n"
                "log_min_duration_statement = 2000\n")

    def desired(self, ctx: Context) -> dict:
        return {"data": str(self.data), "port": ctx.cfg.pg_port, "listen": "127.0.0.1", "auth": "scram-sha-256",
                "superuser": SUPERUSER, "version": 17}

    def observe(self, ctx: Context) -> dict:
        pv = self.data / "PG_VERSION"
        auto = self.data / "postgresql.auto.conf"
        port = None
        if auto.exists():
            for line in auto.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith("port"):
                    port = int(line.split("=", 1)[1].strip())
        conf_ok = auto.exists() and auto.read_text(encoding="utf-8", errors="ignore").endswith(self._conf(ctx))
        return {"data": str(self.data), "initialized": pv.exists(), "conf_current": conf_ok,
                "version": pv.read_text().strip() if pv.exists() else None, "port": port,
                "hba_vyonix": (self.data / "pg_hba.conf").exists()
                and (self.data / "pg_hba.conf").read_text(encoding="utf-8", errors="ignore") == HBA}

    def describe(self, ctx: Context) -> dict:
        return {"current": self.observe(ctx), "proposed": self.desired(ctx),
                "impact": "Cria o cluster de banco de dados do VYONIX (vazio). Outras instalações de PostgreSQL não "
                          "são alteradas.",
                "undo": "Remove o cluster somente se foi criado nesta execução."}

    def check(self, ctx: Context) -> bool:
        o = self.observe(ctx)
        return (o["initialized"] and o["version"] == "17" and o["port"] == int(ctx.cfg.pg_port) and o["hba_vyonix"]
                and o["conf_current"])          # configuração antiga (ex.: coletor de log ligado) é atualizada

    def apply(self, ctx: Context) -> None:
        initdb = self.bin / ("initdb.exe" if os.name == "nt" else "initdb")
        if not initdb.exists():
            raise DeployError(f"PostgreSQL não encontrado em {self.bin} (arquivos do programa incompletos).")
        if not (self.data / "PG_VERSION").exists():
            if self.data.exists() and any(self.data.iterdir()):
                raise DeployError(f"A pasta {self.data} não está vazia e não é um cluster PostgreSQL. Nada foi "
                                  "alterado; verifique o conteúdo manualmente.")
            pwfile = ctx.paths.deploy_dir / f".pw-{secrets.token_hex(6)}"
            pwfile.write_text(superuser_password(ctx), encoding="utf-8")
            try:
                r = run([str(initdb), "-D", str(self.data), "-U", SUPERUSER, "-A", "scram-sha-256",
                         f"--pwfile={pwfile}", "-E", "UTF8", "--locale=C", "--locale-provider=builtin",
                         "--builtin-locale=C.UTF-8", "--data-checksums"], timeout=600)
            finally:
                pwfile.unlink(missing_ok=True)
            if not r.ok:
                raise DeployError("initdb falhou: " + (r.err or r.out).strip()[-800:])
        (self.data / "postgresql.auto.conf").write_text(
            "# Do not edit this file manually!\n# It will be overwritten by the ALTER SYSTEM command.\n"
            + self._conf(ctx), encoding="utf-8")
        (self.data / "pg_hba.conf").write_text(HBA, encoding="utf-8")
        dll = self.bin.parent / "lib" / "pgevent.dll"           # mensagens legíveis no Log de Eventos (opcional)
        if os.name == "nt" and dll.exists():
            run(["regsvr32.exe", "/s", "/n", '/i:VYONIX PostgreSQL', str(dll)], timeout=60)

    def rollback(self, ctx: Context, before: dict) -> None:
        if before.get("initialized") is False and self.data.exists():   # só o cluster criado nesta execução
            shutil.rmtree(self.data)

    def how_to_check(self) -> str:
        return f"type \"{self.data}\\PG_VERSION\" · sc query {SERVICE}"


_ORPHANS = r"""
$bin = [IO.Path]::GetFullPath($A.bin).TrimEnd('\') + '\'
$out = @()
foreach ($p in Get-CimInstance Win32_Process -Filter "Name='postgres.exe'") {
  if ($p.ExecutablePath -and $p.ExecutablePath.StartsWith($bin, [StringComparison]::OrdinalIgnoreCase)) {
    $out += [pscustomobject]@{ pid=[int]$p.ProcessId; pai=[int]$p.ParentProcessId; cmd=[string]$p.CommandLine }
    if ($A.kill) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
  }
}
,$out
"""


def orphan_processes(pg_bin: Path, *, kill: bool = False) -> list[dict]:
    """Processos postgres.exe do VYONIX (só da pasta ``pg_bin``). Chamado SÓ com o serviço do banco parado: nesse
    estado, qualquer um deles é órfão de uma instância encerrada à força e impede o banco de subir de novo."""
    from vyonix_deploy.sysrun import IS_WINDOWS, as_list, powershell
    if not IS_WINDOWS:
        return []
    return as_list(powershell(_ORPHANS, {"bin": str(pg_bin), "kill": kill}))


def pg_service_binpath(pg_bin: Path, data: Path) -> str:
    # -t 300: depois de uma queda o PostgreSQL faz a recuperação do log (WAL) antes de aceitar conexões; com a espera
    # padrão (60 s) o pg_ctl desistia e o serviço ficava parado com o banco ainda subindo.
    return f'"{Path(pg_bin) / "pg_ctl.exe"}" runservice -N "{SERVICE}" -D "{data}" -w -t 300'
