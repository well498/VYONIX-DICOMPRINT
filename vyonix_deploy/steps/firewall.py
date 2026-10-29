"""Regras do Firewall do Windows com nome próprio (``VYONIX - <serviço> - <porta>``), por programa e
porta, nos perfis privado e de domínio e, se informado, só para as origens indicadas. Regras complementares para o
perfil **Público** valem só para a sub-rede local (``LocalSubnet``): o Windows classifica redes novas — e muitas
máquinas virtuais — como públicas, o que bloqueava o acesso pela rede local.

Nunca desliga o firewall e nunca altera nem remove regras que não sejam do VYONIX (a regra é
localizada pelo nome interno, que sempre começa com ``VYONIX-``)."""

from __future__ import annotations

from vyonix_deploy.engine import Context, Step
from vyonix_deploy.errors import DeployError
from vyonix_deploy.sysrun import IS_WINDOWS, as_list, powershell

PS_GET = r"""
$r = Get-NetFirewallRule -Name $A.id -ErrorAction SilentlyContinue
if (-not $r) { return $null }
$pf = $r | Get-NetFirewallPortFilter; $af = $r | Get-NetFirewallAddressFilter; $ap = $r | Get-NetFirewallApplicationFilter
[pscustomobject]@{ id=$r.Name; name=$r.DisplayName; enabled=[string]$r.Enabled; direction=[string]$r.Direction; action=[string]$r.Action
  profile=[string]$r.Profile; protocol=[string]$pf.Protocol; port=[string]$pf.LocalPort; remote=@($af.RemoteAddress); program=[string]$ap.Program }
"""

PS_SET = r"""
Get-NetFirewallRule -Name $A.id -ErrorAction SilentlyContinue | Remove-NetFirewallRule
$p = @{ Name=$A.id; DisplayName=$A.name; Group='VYONIX'; Direction='Inbound'; Action='Allow'; Enabled='True';
        Profile=@($A.profiles); Protocol='TCP'; LocalPort=[string]$A.port; Description=$A.description }
if ($A.program) { $p.Program = $A.program }
if ($A.remote -and $A.remote.Count -gt 0) { $p.RemoteAddress = @($A.remote) }
New-NetFirewallRule @p | Out-Null
"""


class FirewallRuleStep(Step):
    category = "firewall"

    def __init__(self, key: str, service: str, port: int, program: str | None, remote: list[str] | None = None,
                 profiles: tuple[str, ...] = ("Domain", "Private")) -> None:
        self.profiles = tuple(profiles)
        self.rule_id = f"VYONIX-{key}-{port}"
        self.name = f"VYONIX - {service} - {port}"
        self.id = f"firewall.{key}"
        self.title = f"Regra de firewall {self.name}"
        self.port = int(port)
        self.program = program
        self.remote = list(remote or [])

    def desired(self, ctx: Context) -> dict:
        return {"id": self.rule_id, "name": self.name, "direction": "Inbound", "action": "Allow", "enabled": "True",
                "profile": ", ".join(self.profiles), "protocol": "TCP", "port": str(self.port),
                "remote": self.remote or ["Any"], "program": self.program or "Any"}

    def observe(self, ctx: Context) -> dict:
        if not IS_WINDOWS:
            return {"id": self.rule_id, "exists": False}
        r = powershell(PS_GET, {"id": self.rule_id})
        if not r:
            return {"id": self.rule_id, "exists": False}
        r["remote"] = as_list(r.get("remote"))
        return {"exists": True, **r}

    def describe(self, ctx: Context) -> dict:
        cur = self.observe(ctx)
        if self.remote == ["LocalSubnet"]:
            origin = f"a sub-rede local (perfil {', '.join(self.profiles)})"
        else:
            origin = ", ".join(self.remote) if self.remote else "qualquer origem das redes privada e de domínio"
        return {"current": cur, "proposed": self.desired(ctx),
                "impact": f"Libera TCP {self.port} de entrada para {origin}. O firewall continua ligado.",
                "undo": "Remove a regra (ou restaura a versão anterior dela)."}

    def check(self, ctx: Context) -> bool:
        cur = self.observe(ctx)
        if not cur.get("exists"):
            return False
        want = self.desired(ctx)
        prog_ok = (cur.get("program") or "Any").lower() == (want["program"] or "Any").lower()
        remote_ok = sorted(x.lower() for x in cur["remote"]) == sorted(x.lower() for x in want["remote"])
        return (cur["enabled"] == "True" and cur["direction"] == "Inbound" and cur["action"] == "Allow"
                and set(cur["profile"].replace(" ", "").split(",")) == set(self.profiles)
                and cur["protocol"] == "TCP" and cur["port"] == str(self.port) and prog_ok and remote_ok)

    def _siblings(self) -> list[dict]:
        """Regras do mesmo item do VYONIX com outra porta (ex.: porta HTTPS alterada no reparo)."""
        prefix = self.rule_id.rsplit("-", 1)[0] + "-"
        r = powershell(r"""@(Get-NetFirewallRule -Name ($A.prefix + '*') -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne $A.id } |
  ForEach-Object { $pf = $_ | Get-NetFirewallPortFilter; $af = $_ | Get-NetFirewallAddressFilter; $ap = $_ | Get-NetFirewallApplicationFilter
  [pscustomobject]@{ id=$_.Name; name=$_.DisplayName; port=[string]$pf.LocalPort; remote=@($af.RemoteAddress); program=[string]$ap.Program } })""",
                       {"prefix": prefix, "id": self.rule_id})
        out = as_list(r)
        for x in out:
            x["remote"] = as_list(x.get("remote"))
        return out

    def capture(self, ctx: Context) -> dict:
        return {**self.observe(ctx), "siblings": self._siblings() if IS_WINDOWS else []}

    def apply(self, ctx: Context) -> None:
        if not IS_WINDOWS:
            raise DeployError("Firewall do Windows só no Windows.")
        for s in self._siblings():
            powershell("Remove-NetFirewallRule -Name $A.id", {"id": s["id"]}, as_json=False)
        powershell(PS_SET, {"id": self.rule_id, "name": self.name, "port": self.port, "program": self.program,
                            "remote": self.remote, "profiles": list(self.profiles),
                            "description": "Criada pelo VYONIX DEPLOY."}, as_json=False)

    def rollback(self, ctx: Context, before: dict) -> None:
        for s in before.get("siblings") or []:
            powershell(PS_SET, {"id": s["id"], "name": s["name"], "port": s["port"],
                                "program": s["program"] if (s.get("program") or "Any") != "Any" else None,
                                "remote": [x for x in s.get("remote") or [] if x.lower() != "any"],
                                "profiles": list(self.profiles),
                                "description": "Restaurada pelo VYONIX DEPLOY."}, as_json=False)
        if not before.get("exists"):
            powershell("Get-NetFirewallRule -Name $A.id -ErrorAction SilentlyContinue | Remove-NetFirewallRule",
                       {"id": self.rule_id}, as_json=False)
            return
        remote = [x for x in before.get("remote") or [] if x.lower() != "any"]
        program = before.get("program") if (before.get("program") or "Any") != "Any" else None
        profiles = [x for x in (before.get("profile") or "").replace(" ", "").split(",") if x] or list(self.profiles)
        powershell(PS_SET, {"id": self.rule_id, "name": before.get("name") or self.name, "port": before.get("port"),
                            "program": program, "remote": remote, "profiles": profiles,
                            "description": "Restaurada pelo VYONIX DEPLOY."}, as_json=False)

    def how_to_check(self) -> str:
        return f'Get-NetFirewallRule -Name "{self.rule_id}" · wf.msc (grupo VYONIX)'


def firewall_profiles() -> list[dict]:
    if not IS_WINDOWS:
        return []
    return as_list(powershell("Get-NetFirewallProfile | ForEach-Object { [pscustomobject]@{ name=[string]$_.Name; "
                              "enabled=[string]$_.Enabled } }"))
