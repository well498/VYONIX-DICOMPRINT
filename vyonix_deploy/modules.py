"""Ativação de módulo sem reinstalar (seção 9.5): direito assinado → dependências → preparo do que
falta → teste → habilitação → relatório complementar. Mesmo motor (plano, aprovação, reversão)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vyonix_deploy.config import DeployConfig
from vyonix_deploy.engine import Context, Engine, Step
from vyonix_deploy.errors import DeployError
from vyonix_deploy.steps.files import DirectoryStep


def _core(ctx: Context):
    """Banco do Core (papel da aplicação, RLS) e a organização desta instalação."""
    from vyonix.db.session import Database
    from vyonix.tenancy import service as tenancy
    from vyonix_deploy.steps.core import role_urls
    urls = role_urls(ctx)
    db = Database(urls["app"], service_url=urls["service"], pool_size=2)
    tid = tenancy.resolve(db, ctx.cfg.organization)
    if tid is None:
        db.dispose()
        raise DeployError("Organização do VYONIX não encontrada no banco: execute o reparo.")
    return db, tid


def _licensing(ctx: Context):
    lic = ctx.extra.get("licensing")
    if lic is None:
        from vyonix.licensing.service import Licensing, Machine
        lic = Licensing(Machine.build(ctx.paths.licensing))
        ctx.extra["licensing"] = lic
    return lic


class EntitlementStep(Step):
    category = "modulo"
    reversible = False

    def __init__(self, code: str) -> None:
        self.code = code
        self.id = f"module.{code}.entitlement"
        self.title = f"Direito assinado para o módulo {code}"

    def _status(self, ctx: Context) -> tuple[bool, str]:
        db, tid = _core(ctx)
        try:
            with db.session(tid) as s:
                return _licensing(ctx).module_ok(s, self.code)
        finally:
            db.dispose()

    def observe(self, ctx: Context) -> dict:
        ok, msg = self._status(ctx)
        return {"module": self.code, "licensed": ok, "message": msg}

    def desired(self, ctx: Context) -> dict:
        return {"module": self.code, "licensed": True}

    def describe(self, ctx: Context) -> dict:
        return {"current": self.observe(ctx), "proposed": self.desired(ctx),
                "impact": "Somente conferência da licença aplicada no VYONIX (assinatura do fornecedor).",
                "undo": "—"}

    def check(self, ctx: Context) -> bool:
        return self._status(ctx)[0]

    def apply(self, ctx: Context) -> None:
        raise DeployError(f"Sem direito vigente para o módulo {self.code}: {self._status(ctx)[1]} "
                          "Aplique a licença em Licença e módulos e tente de novo.")


class DependenciesStep(Step):
    category = "modulo"
    reversible = False

    def __init__(self, code: str) -> None:
        self.code = code
        self.id = f"module.{code}.dependencies"
        self.title = f"Dependências do módulo {code}"

    def _missing(self, ctx: Context) -> list[str]:
        from vyonix.modules import registry
        from vyonix.modules.manifest import MANIFESTS
        m = MANIFESTS.get(self.code)
        if m is None:
            raise DeployError(f"Módulo desconhecido: {self.code}")
        if not m.available:
            raise DeployError(f"O módulo {m.name} ainda não está disponível nesta versão.")
        db, tid = _core(ctx)
        try:
            with db.session(tid) as s:
                return [d for d in m.depends if not registry.is_enabled(s, d)]
        finally:
            db.dispose()

    def observe(self, ctx: Context) -> dict:
        return {"module": self.code, "missing": self._missing(ctx)}

    def desired(self, ctx: Context) -> dict:
        return {"module": self.code, "missing": []}

    def check(self, ctx: Context) -> bool:
        return not self._missing(ctx)

    def apply(self, ctx: Context) -> None:
        raise DeployError(f"Habilite antes: {', '.join(self._missing(ctx))}.")


class ModuleTestStep(Step):
    """Teste funcional do módulo antes de habilitar. Para o PRINT: o DICOM Print instalado responde
    (serviço em execução); sem ele, o teste registra "Não aplicável" e não bloqueia."""

    category = "modulo"
    reversible = False

    def __init__(self, code: str) -> None:
        self.code = code
        self.id = f"module.{code}.test"
        self.title = f"Teste do módulo {code}"

    def _run(self, ctx: Context) -> dict:
        if self.code == "print":
            from vyonix_deploy.sysrun import IS_WINDOWS
            if IS_WINDOWS:
                from vyonix_deploy.steps.services import query_service
                q = query_service("VyonixDicomPrint")
                if q is None:
                    return {"result": "Não aplicável", "detail": "VYONIX DICOM Print não instalado neste servidor."}
                ok = q["state"] == "Running"
                return {"result": "Aprovado" if ok else "Reprovado",
                        "detail": f"Serviço VyonixDicomPrint: {q['state']}."}
            return {"result": "Não aplicável", "detail": "Somente no Windows."}
        return {"result": "Não aplicável", "detail": "Módulo sem teste específico nesta versão."}

    def observe(self, ctx: Context) -> dict:
        return {"module": self.code, **self._run(ctx)}

    def desired(self, ctx: Context) -> dict:
        return {"module": self.code, "result": "Aprovado ou Não aplicável"}

    def check(self, ctx: Context) -> bool:
        return self._run(ctx)["result"] != "Reprovado"

    def apply(self, ctx: Context) -> None:
        raise DeployError(f"Teste do módulo reprovado: {self._run(ctx)['detail']}")


class ModuleEnableStep(Step):
    category = "modulo"

    def __init__(self, code: str) -> None:
        self.code = code
        self.id = f"module.{code}.enable"
        self.title = f"Habilitar o módulo {code}"

    def observe(self, ctx: Context) -> dict:
        from vyonix.modules import registry
        db, tid = _core(ctx)
        try:
            with db.session(tid) as s:
                return {"module": self.code, "enabled": registry.is_enabled(s, self.code)}
        finally:
            db.dispose()

    def desired(self, ctx: Context) -> dict:
        return {"module": self.code, "enabled": True}

    def describe(self, ctx: Context) -> dict:
        return {"current": self.observe(ctx), "proposed": self.desired(ctx),
                "impact": "Habilita o módulo no VYONIX (registrado na auditoria). Nada é reinstalado.",
                "undo": "Desabilita o módulo (dados preservados)."}

    def check(self, ctx: Context) -> bool:
        return self.observe(ctx)["enabled"]

    def apply(self, ctx: Context) -> None:
        from vyonix.modules import registry
        db, tid = _core(ctx)
        try:
            with db.session(tid) as s:
                registry.enable(s, self.code, actor="VYONIX DEPLOY", license_check=_licensing(ctx).module_ok)
        finally:
            db.dispose()

    def rollback(self, ctx: Context, before: dict) -> None:
        if before.get("enabled"):
            return
        from vyonix.modules import registry
        db, tid = _core(ctx)
        try:
            with db.session(tid) as s:
                registry.disable(s, self.code, actor="VYONIX DEPLOY", reason="reversão da ativação")
        finally:
            db.dispose()


def activation_steps(ctx: Context, code: str) -> list[Step]:
    return [EntitlementStep(code), DependenciesStep(code),
            DirectoryStep(f"module.{code}", ctx.paths.data_dir / "modules" / code, f"do módulo {code}"),
            ModuleTestStep(code), ModuleEnableStep(code)]


def activate(d, code: str, *, approve_all: bool = False, silent: bool = False, licensing=None,
             cfg: DeployConfig | None = None) -> dict[str, Any]:
    from vyonix_deploy import report
    cfg = cfg or d.saved_config()
    if cfg is None:
        raise DeployError("Nenhuma instalação registrada pelo DEPLOY neste servidor.")
    extra = {"licensing": licensing} if licensing is not None else {}

    def build(ctx: Context, kind: str) -> list[Step]:
        return activation_steps(ctx, code)
    ctx = d.context(cfg, inv=d.inventory(), extra=extra)
    eng = Engine(ctx, build)
    rid = eng.new_run("activate")
    d._run = rid
    items = eng.plan("activate")
    sha = eng.save_plan(rid, items)
    if not approve_all:
        rep = report.generate(d.db, d.paths, rid, secrets=d.secret_values(ctx))
        return {"run_id": rid, "status": "planned", "plan_sha": sha, "items": [i.as_dict() for i in items],
                "report": rep}
    eng.approve(rid, via="ativação de módulo")
    status = eng.execute(rid)
    observed = {}
    for st in build(ctx, "activate"):
        try:
            observed[st.id] = st.observe(ctx)
        except Exception as exc:  # noqa: BLE001
            observed[st.id] = {"erro": str(exc)[:200]}
    tests = [{"name": f"Módulo {code}: teste funcional", **(observed.get(f"module.{code}.test") or {})}]
    rep = report.generate(d.db, d.paths, rid, observed=observed, extra_tests=[
        {"name": t["name"], "result": t.get("result", "Não executado"), "detail": t.get("detail")} for t in tests],
        secrets=d.secret_values(ctx))
    return {"run_id": rid, "status": status, "message": d.db.run(rid)["message"], "report": rep}
