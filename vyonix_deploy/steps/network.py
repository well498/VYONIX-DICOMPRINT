"""Rede: o padrão é **manter o IP atual** (nenhum passo). IP fixo só com confirmação explícita.

Proteções do IP fixo:
1. Antes: confere se o IP pretendido já responde na rede (ARP/ping) — se responder, recusa.
2. Uma tarefa agendada de segurança (SYSTEM) é criada antes da mudança para restaurar a
   configuração anterior em 3 minutos, mesmo que o DEPLOY seja interrompido.
3. Depois: confere gateway e DNS por até 60 s; sem conectividade, desfaz na hora.
4. Confirmada a conectividade, a tarefa de segurança é removida.
"""

from __future__ import annotations

import json
import time

from vyonix_deploy.config import NetworkChoice
from vyonix_deploy.engine import Context, Step
from vyonix_deploy.errors import DeployError
from vyonix_deploy.sysrun import IS_WINDOWS, as_list, powershell

CONFIRM_TEXT = "ALTERAR IP"
SAFETY_TASK = "VYONIX - restaurar rede"
CONNECTIVITY_TIMEOUT_S = 60

PS_GET = r"""
$i = Get-NetIPInterface -InterfaceAlias $A.alias -AddressFamily IPv4 -ErrorAction Stop
$ips = @(Get-NetIPAddress -InterfaceAlias $A.alias -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.PrefixOrigin -ne 'WellKnown' } |
  ForEach-Object { [pscustomobject]@{ ip=$_.IPAddress; prefix=[int]$_.PrefixLength; origin=[string]$_.PrefixOrigin } })
$gw = @(Get-NetRoute -InterfaceAlias $A.alias -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | ForEach-Object { $_.NextHop })
$dns = @((Get-DnsClientServerAddress -InterfaceAlias $A.alias -AddressFamily IPv4 -ErrorAction SilentlyContinue).ServerAddresses)
[pscustomobject]@{ alias=$A.alias; dhcp=[string]$i.Dhcp; ips=$ips; gateway=$gw; dns=$dns }
"""

# Restaura uma configuração capturada (usada pela reversão e pela tarefa de segurança).
PS_RESTORE = r"""
$c = $A.before
Get-NetIPAddress -InterfaceAlias $c.alias -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.PrefixOrigin -ne 'WellKnown' } | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
Get-NetRoute -InterfaceAlias $c.alias -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
if ($c.dhcp -eq 'Enabled') {
  Set-NetIPInterface -InterfaceAlias $c.alias -Dhcp Enabled
  Set-DnsClientServerAddress -InterfaceAlias $c.alias -ResetServerAddresses
} else {
  Set-NetIPInterface -InterfaceAlias $c.alias -Dhcp Disabled
  foreach ($a in @($c.ips)) { if ($a.ip) { New-NetIPAddress -InterfaceAlias $c.alias -IPAddress $a.ip -PrefixLength $a.prefix | Out-Null } }
  foreach ($g in @($c.gateway)) { if ($g) { New-NetRoute -InterfaceAlias $c.alias -DestinationPrefix '0.0.0.0/0' -NextHop $g | Out-Null } }
  if (@($c.dns).Count -gt 0) { Set-DnsClientServerAddress -InterfaceAlias $c.alias -ServerAddresses @($c.dns) } else { Set-DnsClientServerAddress -InterfaceAlias $c.alias -ResetServerAddresses }
}
"""


def interface_config(alias: str) -> dict:
    r = powershell(PS_GET, {"alias": alias})
    for k in ("ips", "gateway", "dns"):
        r[k] = as_list(r.get(k))
    return r


def ip_in_use(ip: str, alias: str) -> bool:
    """O IP responde na rede (e não é deste computador)?"""
    r = powershell(r"""
$mine = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object { $_.IPAddress })
if ($mine -contains $A.ip) { return $false }
$ping = Test-Connection -ComputerName $A.ip -Count 2 -Quiet -ErrorAction SilentlyContinue
$arp = @(Get-NetNeighbor -IPAddress $A.ip -ErrorAction SilentlyContinue | Where-Object { $_.State -in 'Reachable','Stale','Permanent' })
[bool]($ping -or $arp.Count -gt 0)""", {"ip": ip, "alias": alias})
    return bool(r)


class StaticIpStep(Step):
    category = "rede"
    id = "network.static_ip"
    reboot = False
    confirm = CONFIRM_TEXT

    def __init__(self, choice: NetworkChoice) -> None:
        self.c = choice
        self.title = f"IP fixo {choice.ip}/{choice.prefix} em {choice.interface}"

    def desired(self, ctx: Context) -> dict:
        return {"alias": self.c.interface, "dhcp": "Disabled", "ips": [{"ip": self.c.ip, "prefix": self.c.prefix}],
                "gateway": [self.c.gateway], "dns": list(self.c.dns)}

    def observe(self, ctx: Context) -> dict:
        if not IS_WINDOWS:
            return {"alias": self.c.interface}
        try:
            return interface_config(self.c.interface)
        except DeployError as exc:
            return {"alias": self.c.interface, "erro": str(exc)[:200]}

    def describe(self, ctx: Context) -> dict:
        return {"current": self.observe(ctx), "proposed": self.desired(ctx),
                "impact": "Muda o endereço do servidor: estações e equipamentos que usam o IP antigo deixam de "
                          "alcançá-lo. Prefira reserva no DHCP quando possível.",
                "undo": "Restaura a configuração anterior automaticamente se a conectividade não voltar em 60 s "
                        "(e por tarefa de segurança em 3 min, se o DEPLOY for interrompido)."}

    def check(self, ctx: Context) -> bool:
        if not IS_WINDOWS:
            return False
        cur = self.observe(ctx)
        if "erro" in cur:
            return False
        return (cur["dhcp"] == "Disabled" and [(x["ip"], x["prefix"]) for x in cur["ips"]] == [(self.c.ip, self.c.prefix)]
                and cur["gateway"] == [self.c.gateway] and (not self.c.dns or cur["dns"] == list(self.c.dns)))

    def capture(self, ctx: Context) -> dict:
        return interface_config(self.c.interface)

    def apply(self, ctx: Context) -> None:
        if not self.c.confirmed:
            raise DeployError("Mudança de IP sem confirmação explícita.")
        if ip_in_use(self.c.ip, self.c.interface):
            raise DeployError(f"O IP {self.c.ip} já responde na rede (conflito). Nada foi alterado.")
        before = interface_config(self.c.interface)
        self._arm_safety(ctx, before)
        try:
            powershell(r"""
Get-NetIPAddress -InterfaceAlias $A.alias -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.PrefixOrigin -ne 'WellKnown' } | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
Get-NetRoute -InterfaceAlias $A.alias -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
Set-NetIPInterface -InterfaceAlias $A.alias -Dhcp Disabled
New-NetIPAddress -InterfaceAlias $A.alias -IPAddress $A.ip -PrefixLength $A.prefix -DefaultGateway $A.gateway | Out-Null
if (@($A.dns).Count -gt 0) { Set-DnsClientServerAddress -InterfaceAlias $A.alias -ServerAddresses @($A.dns) }
""", {"alias": self.c.interface, "ip": self.c.ip, "prefix": self.c.prefix, "gateway": self.c.gateway,
      "dns": list(self.c.dns)}, as_json=False)
            ok, msg = self.connectivity(CONNECTIVITY_TIMEOUT_S)
            if not ok:
                ctx.log("WARN", f"Sem conectividade após a mudança de IP ({msg}): restaurando a configuração anterior.")
                powershell(PS_RESTORE, {"before": before}, as_json=False)
                raise DeployError(f"Conectividade não confirmada em {CONNECTIVITY_TIMEOUT_S} s ({msg}). "
                                  "A configuração anterior foi restaurada.")
        finally:
            self._disarm_safety(ctx)

    def connectivity(self, timeout: float) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            r = powershell(r"""
$gw = Test-Connection -ComputerName $A.gateway -Count 1 -Quiet -ErrorAction SilentlyContinue
$dns = $true
foreach ($d in @($A.dns)) { if ($d) { $dns = $dns -and (Test-Connection -ComputerName $d -Count 1 -Quiet -ErrorAction SilentlyContinue) } }
[pscustomobject]@{ gateway=[bool]$gw; dns=[bool]$dns }""", {"gateway": self.c.gateway, "dns": list(self.c.dns)})
            if r.get("gateway") and r.get("dns"):
                return True, "gateway e DNS respondem"
            last = "gateway não responde" if not r.get("gateway") else "DNS não responde"
            time.sleep(3)
        return False, last

    def _script(self, ctx: Context):
        return ctx.paths.deploy_dir / "restaurar_rede.ps1"

    def _arm_safety(self, ctx: Context, before: dict) -> None:
        """Tarefa agendada (SYSTEM) que restaura a rede em 3 min se o DEPLOY não confirmar a mudança."""
        f = self._script(ctx)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("$ErrorActionPreference='Continue'\r\n$A = '" + json.dumps({"before": before}).replace("'", "''")
                     + "' | ConvertFrom-Json\r\n" + PS_RESTORE + "\r\nUnregister-ScheduledTask -TaskName '"
                     + SAFETY_TASK + "' -Confirm:$false\r\n", encoding="utf-8-sig")
        powershell(r"""
$act = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $A.file + '"')
$trg = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(3))
Register-ScheduledTask -TaskName $A.name -Action $act -Trigger $trg -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
""", {"file": str(f), "name": SAFETY_TASK}, as_json=False)

    def _disarm_safety(self, ctx: Context) -> None:
        powershell("Unregister-ScheduledTask -TaskName $A.name -Confirm:$false -ErrorAction SilentlyContinue",
                   {"name": SAFETY_TASK}, as_json=False, check=False)
        try:
            self._script(ctx).unlink()
        except OSError:
            pass

    def rollback(self, ctx: Context, before: dict) -> None:
        powershell(PS_RESTORE, {"before": before}, as_json=False)

    def how_to_check(self) -> str:
        return f'Get-NetIPConfiguration -InterfaceAlias "{self.c.interface}"'
