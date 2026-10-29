"""VYONIX Core: banco de dados (papéis com privilégio mínimo, migrações, organização e primeiro
administrador), configuração e verificação por HTTPS."""

from __future__ import annotations

import json
import socket
import ssl
import urllib.request
from pathlib import Path
from urllib.parse import quote

from vyonix_deploy.engine import Context, Step
from vyonix_deploy.errors import DeployError
from vyonix_deploy.steps import postgres as pg

DB_NAME = "vyonix"
PREFIX = "vyonix"
ROLES = ("owner", "app", "service")
MODULE_KEYS = ("pacs_",)


def _core_store(ctx: Context):
    from vyonix.secrets import SecretStore
    return SecretStore(ctx.paths.data_dir)


def role_urls(ctx: Context) -> dict[str, str]:
    store = _core_store(ctx)
    out = {}
    for r in ROLES:
        pw = store.get_or_create_text(f"db_{r}")
        out[r] = f"postgresql://{PREFIX}_{r}:{quote(pw, safe='')}@127.0.0.1:{ctx.cfg.pg_port}/{DB_NAME}"
    return out


def core_config(ctx: Context) -> dict:
    tmpl = {r: f"postgresql://{PREFIX}_{r}:{{secret:db_{r}}}@127.0.0.1:{ctx.cfg.pg_port}/{DB_NAME}" for r in ROLES}
    tls = ctx.paths.data_dir / "tls"
    keep: dict = {}
    try:                     # configurações de módulos (ex.: pacs_*) gravadas pela ativação são preservadas
        cur = json.loads((ctx.paths.data_dir / "config.json").read_text(encoding="utf-8"))
        keep = {k: v for k, v in cur.items() if k.startswith(MODULE_KEYS)}
    except (OSError, ValueError):
        pass
    return {**keep, "mode": "edge", "database_url": tmpl["app"], "service_database_url": tmpl["service"],
            "owner_database_url": tmpl["owner"], "role_prefix": PREFIX, "default_organization": ctx.cfg.organization,
            "bind": "0.0.0.0", "port": int(ctx.cfg.https_port), "tls_cert": str(tls / "server.crt"),
            "tls_key": str(tls / "server.key"), "licensing_dir": str(ctx.paths.licensing)}


class CoreDatabaseStep(Step):
    category = "banco"
    id = "core.database"
    title = "Banco de dados e configuração do VYONIX Core"

    def desired(self, ctx: Context) -> dict:
        return {"database": DB_NAME, "roles": [f"{PREFIX}_{r}" for r in ROLES], "migrations": "heads",
                "organization": ctx.cfg.organization, "admin_user": ctx.cfg.admin_user,
                "config": {k: v for k, v in core_config(ctx).items() if "url" not in k}}

    def _config_matches(self, ctx: Context) -> bool:
        f = ctx.paths.data_dir / "config.json"
        try:
            return json.loads(f.read_text(encoding="utf-8")) == core_config(ctx)
        except (OSError, ValueError):
            return False

    def observe(self, ctx: Context) -> dict:
        out: dict = {"config_file": (ctx.paths.data_dir / "config.json").exists(),
                     "config_current": self._config_matches(ctx)}
        ok, msg = pg.can_connect(ctx)
        if not ok:
            return {**out, "postgres": msg}
        import psycopg
        try:
            with psycopg.connect(pg.admin_url(ctx), connect_timeout=5) as c:
                out["database"] = bool(c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)).fetchone())
                out["roles"] = sorted(r[0] for r in c.execute("SELECT rolname FROM pg_roles WHERE rolname LIKE %s",
                                                              (f"{PREFIX}\\_%",)).fetchall())
        except Exception as exc:  # noqa: BLE001
            return {**out, "erro": str(exc)[:200]}
        if out["database"] and (ctx.paths.data_dir / "secrets.json").exists():
            try:
                from vyonix.db import migrate
                urls = role_urls(ctx)
                out["migrations"] = migrate.current(urls["owner"])
                out["heads"] = migrate.heads(PREFIX)
                out["up_to_date"] = migrate.up_to_date(out["migrations"], PREFIX)
                from vyonix.db.session import Database
                from vyonix.tenancy import service as tenancy
                d = Database(urls["app"], service_url=urls["service"])
                try:
                    out["organization"] = bool(tenancy.resolve(d, ctx.cfg.organization))
                finally:
                    d.dispose()
            except Exception as exc:  # noqa: BLE001
                out["erro"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return out

    def describe(self, ctx: Context) -> dict:
        return {"current": self.observe(ctx), "proposed": self.desired(ctx),
                "impact": "Cria o banco do VYONIX com três papéis de privilégio mínimo, aplica as migrações e cria a "
                          "organização e o primeiro administrador (se ainda não existirem).",
                "undo": "Em instalação nova, remove o banco e os papéis criados agora. Bancos existentes nunca são "
                        "apagados."}

    def check(self, ctx: Context) -> bool:
        from vyonix_deploy import faults
        if faults.active("migracao"):
            return False
        o = self.observe(ctx)
        return bool(o.get("config_current") and o.get("database") and o.get("organization")
                    and o.get("migrations") and o.get("up_to_date"))

    def capture(self, ctx: Context) -> dict:
        o = self.observe(ctx)
        # None = não foi possível saber (banco inacessível): a reversão NUNCA apaga um banco cuja ausência não foi
        # confirmada. Só um banco que comprovadamente não existia antes (instalação nova) é removido.
        return {"database": o.get("database") if "database" in o else None, "config_file": o.get("config_file")}

    def apply(self, ctx: Context) -> None:
        from vyonix.db import migrate, provision
        from vyonix.db.session import Database
        from vyonix.tenancy import service as tenancy
        from vyonix_deploy import faults
        if faults.active("migracao"):
            raise DeployError("Falha simulada na migração do banco (teste de homologação): nenhuma alteração feita.")
        store = _core_store(ctx)
        pw = {r: store.get_or_create_text(f"db_{r}") for r in ROLES}
        urls = provision.provision(pg.admin_url(ctx), DB_NAME, prefix=PREFIX, passwords=pw)
        migrate.upgrade(urls.owner, prefix=PREFIX)
        d = Database(urls.app, service_url=urls.service)
        try:
            if tenancy.resolve(d, ctx.cfg.organization) is None:
                admin_pw = ctx.extra.get("admin_password")
                if not admin_pw:
                    raise DeployError("Informe a senha do primeiro administrador do VYONIX.")
                tenancy.create_organization(d, code=ctx.cfg.organization, name=ctx.cfg.organization_name,
                                            admin_username=ctx.cfg.admin_user, admin_password=admin_pw,
                                            actor="VYONIX DEPLOY")
            else:
                for tid in tenancy.organizations_for_service(d):
                    tenancy.refresh(d, tid)
        finally:
            d.dispose()
        cfgf = ctx.paths.data_dir / "config.json"
        cfgf.write_text(json.dumps(core_config(ctx), indent=2, ensure_ascii=False), encoding="utf-8")

    def rollback(self, ctx: Context, before: dict) -> None:
        from vyonix.db import provision
        if before.get("database") is False:            # nunca um banco existente ou de estado desconhecido
            provision.drop(pg.admin_url(ctx), DB_NAME, roles=[f"{PREFIX}_{r}" for r in ROLES])
        if before.get("config_file") is False:
            (ctx.paths.data_dir / "config.json").unlink(missing_ok=True)

    def how_to_check(self) -> str:
        return "VyonixPlatform.exe status"


def health(ctx: Context) -> tuple[bool, str]:
    """``GET /api/v1/health`` por HTTPS, conferindo o certificado instalado."""
    cert = ctx.paths.data_dir / "tls" / "server.crt"
    try:
        from vyonix_deploy.steps.tls import cert_info
        info = cert_info(cert) or {}
        if info.get("self_signed"):
            sslctx = ssl.create_default_context(cafile=str(cert))
            host = "localhost"
        else:
            sslctx = ssl.create_default_context()
            host = socket.gethostname()
        url = f"https://{host}:{ctx.cfg.https_port}/api/v1/health"
        req = urllib.request.Request(url, headers={"User-Agent": "VYONIX-DEPLOY"})
        handler = urllib.request.HTTPSHandler(context=sslctx)
        opener = urllib.request.build_opener(handler, urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        if data.get("status") == "ok" and data.get("database"):
            return True, f"HTTPS {url}: status ok, banco ok, versão {data.get('version')}"
        return False, f"HTTPS respondeu, mas: {data}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:200]}"


def service_binpath(install_dir: Path, which: str, data_dir: Path) -> str:
    return f'"{Path(install_dir) / "VyonixPlatform.exe"}" service {which} --data "{data_dir}"'
