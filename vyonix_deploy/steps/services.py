"""Serviços do Windows: registro (conta de serviço virtual, início automático atrasado, dependências,
recuperação após falha) e execução. Usa ``sc.exe`` e CIM; nunca altera serviços que não sejam do VYONIX."""

from __future__ import annotations

import os
import struct
import time

from vyonix_deploy.engine import Context, Step
from vyonix_deploy.errors import DeployError
from vyonix_deploy.sysrun import IS_WINDOWS, as_list, powershell, run

SC = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "sc.exe")
RECOVERY = [(1, 5000), (1, 15000), (1, 60000)]        # reiniciar após 5 s, 15 s, 60 s
RESET_S = 86400


def query_service(name: str) -> dict | None:
    r = powershell(r"""
$s = Get-CimInstance Win32_Service -Filter ("Name='" + $A.n + "'")
if (-not $s) { return $null }
$key = 'HKLM:\SYSTEM\CurrentControlSet\Services\' + $A.n
$p = Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue
$fa = if ($p.FailureActions) { [Convert]::ToBase64String([byte[]]$p.FailureActions) } else { $null }
[pscustomobject]@{ name=$s.Name; display=$s.DisplayName; state=$s.State; start=$s.StartMode; delayed=[bool]$s.DelayedAutoStart
  account=$s.StartName; path=$s.PathName; description=$s.Description; pid=[int]$s.ProcessId
  depends=@((Get-Service -Name $A.n).ServicesDependedOn | ForEach-Object { $_.Name }); failure_actions=$fa }
""", {"n": name})
    if r:
        r["depends"] = as_list(r.get("depends"))
        r["recovery"] = _parse_failure_actions(r.pop("failure_actions", None))
    return r


def _parse_failure_actions(b64: str | None) -> dict | None:
    if not b64:
        return None
    import base64
    raw = base64.b64decode(b64)
    if len(raw) < 20:
        return None
    reset, _msg, _cmd, count, _ptr = struct.unpack_from("<IIIII", raw, 0)
    actions = [struct.unpack_from("<II", raw, 20 + 8 * i) for i in range(count) if 20 + 8 * i + 8 <= len(raw)]
    return {"reset": reset, "actions": [list(a) for a in actions]}


class ServiceStep(Step):
    category = "servico"

    def __init__(self, name: str, display: str, description: str, binpath: str, *, depends: list[str] | None = None,
                 delayed: bool = True, virtual_account: bool = True) -> None:
        self.id = f"service.{name}"
        self.name = name
        self.display = display
        self.description = description
        self.binpath = binpath
        self.depends = depends or []
        self.delayed = delayed
        self.account = f"NT SERVICE\\{name}" if virtual_account else "LocalSystem"
        self.title = f"Serviço {display}"

    def desired(self, ctx: Context) -> dict:
        return {"name": self.name, "path": self.binpath, "account": self.account, "start": "Auto",
                "delayed": self.delayed, "depends": self.depends,
                "recovery": {"reset": RESET_S, "actions": [list(a) for a in RECOVERY]}}

    def observe(self, ctx: Context) -> dict:
        if not IS_WINDOWS:
            return {"name": self.name, "exists": False}
        q = query_service(self.name)
        return {"name": self.name, "exists": bool(q), **(q or {})}

    def describe(self, ctx: Context) -> dict:
        cur = self.observe(ctx)
        return {"current": cur if cur.get("exists") else {"exists": False}, "proposed": self.desired(ctx),
                "impact": f"Registra o serviço com a conta virtual {self.account} (sem senha), início automático"
                          + (" atrasado" if self.delayed else "") + " e reinício automático após falha (3 tentativas).",
                "undo": "Remove o serviço se foi criado agora; senão restaura a configuração anterior."}

    def check(self, ctx: Context) -> bool:
        if not IS_WINDOWS:
            return False
        q = query_service(self.name)
        if not q:
            return False
        acct = (q.get("account") or "").lower()
        return (_norm(q["path"]) == _norm(self.binpath) and acct == self.account.lower() and q["start"] == "Auto"
                and bool(q.get("delayed")) == self.delayed
                and sorted(d.lower() for d in q["depends"]) == sorted(d.lower() for d in self.depends)
                and (q.get("recovery") or {}).get("actions") == [list(a) for a in RECOVERY])

    def capture(self, ctx: Context) -> dict:
        return self.observe(ctx)

    def apply(self, ctx: Context) -> None:
        if not IS_WINDOWS:
            raise DeployError("Serviços do Windows só no Windows.")
        exists = query_service(self.name) is not None
        start = "delayed-auto" if self.delayed else "auto"
        dep = "/".join(self.depends) if self.depends else "/"
        verb = "config" if exists else "create"
        run([SC, verb, self.name, "binPath=", self.binpath, "start=", start, "obj=", self.account,
             "DisplayName=", self.display, "depend=", dep], check=True)
        run([SC, "description", self.name, self.description], check=True)
        actions = "/".join(f"restart/{d}" for _t, d in RECOVERY)
        run([SC, "failure", self.name, "reset=", str(RESET_S), "actions=", actions], check=True)
        run([SC, "failureflag", self.name, "1"], check=True)
        run([SC, "sidtype", self.name, "unrestricted"], check=True)

    def rollback(self, ctx: Context, before: dict) -> None:
        if not before.get("exists"):
            stop_service(self.name)
            run([SC, "delete", self.name])
            return
        start = "delayed-auto" if before.get("delayed") else {"Auto": "auto", "Manual": "demand",
                                                              "Disabled": "disabled"}.get(before.get("start"), "demand")
        run([SC, "config", self.name, "binPath=", before["path"], "start=", start, "obj=", before["account"],
             "DisplayName=", before.get("display") or self.display,
             "depend=", "/".join(before.get("depends") or []) or "/"])

    def how_to_check(self) -> str:
        return f"sc qc {self.name} · sc qfailure {self.name} · services.msc"


def _norm(p: str | None) -> str:
    return " ".join((p or "").replace('"', "").lower().split())


def stop_service(name: str, timeout: float = 60) -> None:
    run([SC, "stop", name])
    _wait(name, "Stopped", timeout)


def _wait(name: str, state: str, timeout: float) -> str | None:
    deadline = time.monotonic() + timeout
    cur = None
    while time.monotonic() < deadline:
        q = query_service(name)
        cur = q["state"] if q else None
        if cur == state or q is None:
            return cur
        time.sleep(1.5)
    return cur


class ServiceRunningStep(Step):
    category = "servico"

    def __init__(self, name: str, display: str, *, probe=None, timeout: float = 90) -> None:
        self.id = f"running.{name}"
        self.name = name
        self.title = f"Iniciar {display}"
        self.probe = probe              # verificação funcional extra (ex.: HTTPS /health, conexão ao banco)
        self.timeout = timeout

    def desired(self, ctx: Context) -> dict:
        return {"name": self.name, "state": "Running"}

    def observe(self, ctx: Context) -> dict:
        q = query_service(self.name) if IS_WINDOWS else None
        return {"name": self.name, "state": q["state"] if q else "Ausente"}

    def describe(self, ctx: Context) -> dict:
        return {"current": self.observe(ctx), "proposed": self.desired(ctx),
                "impact": "Inicia o serviço e confere o funcionamento.", "undo": "Para o serviço."}

    def check(self, ctx: Context) -> bool:
        if not IS_WINDOWS:
            return False
        if self.observe(ctx)["state"] != "Running":
            return False
        return self.probe is None or self.probe(ctx)[0]

    def apply(self, ctx: Context) -> None:
        q = query_service(self.name)
        if q and q["state"] == "Running" and self.probe is not None and not self.probe(ctx)[0]:
            ctx.log("INFO", f"{self.name} em execução, mas sem responder como esperado: reiniciando.")
            stop_service(self.name)
            q = query_service(self.name)
        if q and q["state"] != "Running":
            r = run([SC, "start", self.name])
            if not r.ok and "1056" not in r.out:          # 1056 = já em execução
                raise DeployError(f"Não foi possível iniciar {self.name}: {(r.out or r.err).strip()[:300]}")
        st = _wait(self.name, "Running", self.timeout)
        if st != "Running":
            raise DeployError(f"{self.name} não ficou em execução (estado: {st}).")

    def verify(self, ctx: Context) -> tuple[bool, str]:
        if self.observe(ctx)["state"] != "Running":
            return False, "serviço não está em execução"
        if self.probe is None:
            return True, "em execução"
        deadline = time.monotonic() + self.timeout
        ok, msg = False, ""
        while time.monotonic() < deadline:
            ok, msg = self.probe(ctx)
            if ok:
                break
            time.sleep(2)
        return ok, msg

    def rollback(self, ctx: Context, before: dict) -> None:
        if before.get("state") != "Running":
            stop_service(self.name)

    def how_to_check(self) -> str:
        return f"sc query {self.name}"
