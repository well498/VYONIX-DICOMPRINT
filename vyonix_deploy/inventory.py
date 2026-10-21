"""Inventário do servidor — **somente leitura**. Nada aqui altera o sistema.

No Windows a coleta usa CIM/WMI e os módulos NetTCPIP/NetSecurity do PowerShell. Em outros sistemas
há uma coleta reduzida (desenvolvimento); a instalação em si exige Windows nesta fase.
"""

from __future__ import annotations

import getpass
import os
import platform
import shutil
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vyonix_deploy import __version__
from vyonix_deploy.paths import Paths
from vyonix_deploy.sysrun import IS_WINDOWS, as_list, powershell

INTERESTING_SERVICES = ("*postgres*", "*vyonix*", "*orthanc*", "*dcm4*", "*conquest*", "*pacs*", "*dicom*",
                        "MpsSvc", "Spooler", "W32Time")

PS_INVENTORY = r"""
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = @(Get-CimInstance Win32_Processor)
$disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
  [pscustomobject]@{ drive=$_.DeviceID; size=[int64]$_.Size; free=[int64]$_.FreeSpace; fs=$_.FileSystem } })
$ifs = @(Get-NetIPInterface -AddressFamily IPv4 -ErrorAction SilentlyContinue)
$nics = @(Get-NetIPConfiguration -ErrorAction SilentlyContinue | ForEach-Object {
  $idx = $_.InterfaceIndex
  $ipif = $ifs | Where-Object { $_.InterfaceIndex -eq $idx } | Select-Object -First 1
  $ad = Get-NetAdapter -InterfaceIndex $idx -ErrorAction SilentlyContinue
  [pscustomobject]@{
    alias=$_.InterfaceAlias; index=$idx; description=$_.InterfaceDescription
    status= if ($ad) { [string]$ad.Status } else { $null }
    mac= if ($ad) { [string]$ad.MacAddress } else { $null }
    virtual= if ($ad) { [bool]$ad.Virtual } else { $null }
    ipv4=@($_.IPv4Address | ForEach-Object { [pscustomobject]@{ ip=$_.IPAddress; prefix=[int]$_.PrefixLength } })
    gateway=@($_.IPv4DefaultGateway | ForEach-Object { $_.NextHop })
    dns=@($_.DNSServer | Where-Object { $_.AddressFamily -eq 2 } | ForEach-Object { $_.ServerAddresses } | Select-Object -Unique)
    dhcp= if ($ipif) { [string]$ipif.Dhcp } else { $null }
  } })
$procs = @{}
Get-Process -ErrorAction SilentlyContinue | ForEach-Object { $procs[[int]$_.Id] = $_.ProcessName }
$ports = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
  [pscustomobject]@{ proto='tcp'; address=$_.LocalAddress; port=[int]$_.LocalPort; pid=[int]$_.OwningProcess; process=$procs[[int]$_.OwningProcess] } })
$svcPatterns = $A.services
$services = @(Get-CimInstance Win32_Service | Where-Object { $n=$_.Name; $svcPatterns | Where-Object { $n -like $_ } } | ForEach-Object {
  [pscustomobject]@{ name=$_.Name; display=$_.DisplayName; state=$_.State; start=$_.StartMode; account=$_.StartName; path=$_.PathName } })
$fwp = @(Get-NetFirewallProfile | ForEach-Object { [pscustomobject]@{ name=[string]$_.Name; enabled=[bool]($_.Enabled -eq 'True' -or $_.Enabled -eq 1) } })
$rules = @(Get-NetFirewallRule -DisplayName 'VYONIX*' -ErrorAction SilentlyContinue | ForEach-Object {
  $pf = $_ | Get-NetFirewallPortFilter; $af = $_ | Get-NetFirewallAddressFilter; $ap = $_ | Get-NetFirewallApplicationFilter
  [pscustomobject]@{ name=$_.DisplayName; enabled=[string]$_.Enabled; direction=[string]$_.Direction; action=[string]$_.Action
    profile=[string]$_.Profile; protocol=[string]$pf.Protocol; port=[string]$pf.LocalPort; remote=@($af.RemoteAddress); program=[string]$ap.Program } })
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$admin = ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$certs = @(Get-ChildItem Cert:\LocalMachine\My -ErrorAction SilentlyContinue | Where-Object { $_.Subject -like '*VYONIX*' -or $_.FriendlyName -like 'VYONIX*' } | ForEach-Object {
  [pscustomobject]@{ subject=$_.Subject; thumbprint=$_.Thumbprint; not_after=$_.NotAfter.ToUniversalTime().ToString('o'); friendly=$_.FriendlyName } })
$uninst = @(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
  Where-Object { $_.DisplayName -like 'VYONIX*' -or $_.DisplayName -like 'PostgreSQL*' } | ForEach-Object {
  [pscustomobject]@{ name=$_.DisplayName; version=$_.DisplayVersion; location=$_.InstallLocation } })
$pending = (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') -or
           (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired')
[pscustomobject]@{
  os=[pscustomobject]@{ caption=$os.Caption; version=$os.Version; build=[int]$os.BuildNumber; arch=$os.OSArchitecture;
    product_type=[int]$os.ProductType; last_boot=$os.LastBootUpTime.ToUniversalTime().ToString('o') }
  computer=[pscustomobject]@{ name=$env:COMPUTERNAME; domain=$cs.Domain; part_of_domain=[bool]$cs.PartOfDomain;
    memory=[int64]$cs.TotalPhysicalMemory; manufacturer=$cs.Manufacturer; model=$cs.Model }
  cpu=[pscustomobject]@{ name=($cpu | Select-Object -First 1).Name; logical=[int](($cpu | Measure-Object NumberOfLogicalProcessors -Sum).Sum) }
  disks=$disks; nics=$nics; ports=$ports; services=$services; firewall_profiles=$fwp; firewall_rules=$rules
  admin=$admin; user=$id.Name; certificates=$certs; installed=$uninst; reboot_pending=$pending
  powershell=$PSVersionTable.PSVersion.ToString()
}
"""


def collect(paths: Paths) -> dict[str, Any]:
    if IS_WINDOWS:
        data = powershell(PS_INVENTORY, {"services": list(INTERESTING_SERVICES)}, timeout=300)
        for k in ("disks", "nics", "ports", "services", "firewall_profiles", "firewall_rules", "certificates",
                  "installed"):
            data[k] = as_list(data.get(k))
        for n in data["nics"]:
            for k in ("ipv4", "gateway", "dns"):
                n[k] = as_list(n.get(k))
        for r in data["firewall_rules"]:
            r["remote"] = as_list(r.get("remote"))
    else:
        data = _collect_posix()
    data["collected_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["deploy_version"] = __version__
    data["paths"] = {k: {"path": v, "exists": Path(v).exists()} for k, v in paths.all().items()}
    data["previous"] = _previous(paths, data)
    return data


def _previous(paths: Paths, data: dict) -> dict[str, Any]:
    names = {s["name"].lower(): s for s in data.get("services", [])}
    platform_cfg = paths.data_dir / "config.json"
    return {
        "platform_installed": platform_cfg.exists() or "vyonixcore" in names,
        "platform_version": _read_version(paths.install_dir / "VERSION.txt"),
        "dicom_print": names.get("vyonixdicomprint") or next(
            ({"name": i["name"], "version": i.get("version")} for i in data.get("installed", [])
             if "DICOM Print" in (i.get("name") or "")), None),
        "deploy_db": paths.db_file.exists(),
    }


def _read_version(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _collect_posix() -> dict[str, Any]:
    mem = 0
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem = int(line.split()[1]) * 1024
    except OSError:
        pass
    du = shutil.disk_usage("/")
    ports = []
    for fn in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(fn, encoding="ascii") as f:
                next(f)
                for line in f:
                    parts = line.split()
                    if parts[3] == "0A":                       # LISTEN
                        ports.append({"proto": "tcp", "address": parts[1].rsplit(":", 1)[0],
                                      "port": int(parts[1].rsplit(":", 1)[1], 16), "pid": None, "process": None})
        except OSError:
            continue
    return {"os": {"caption": platform.platform(), "version": platform.release(), "build": 0,
                   "arch": platform.machine(), "product_type": 0},
            "computer": {"name": socket.gethostname(), "memory": mem},
            "cpu": {"name": platform.processor() or platform.machine(), "logical": os.cpu_count() or 0},
            "disks": [{"drive": "/", "size": du.total, "free": du.free, "fs": None}],
            "nics": [], "ports": ports, "services": [], "firewall_profiles": [], "firewall_rules": [],
            "admin": hasattr(os, "geteuid") and os.geteuid() == 0, "user": getpass.getuser(), "certificates": [],
            "installed": [], "reboot_pending": False, "powershell": None, "unsupported": sys.platform}


def port_owner(inv: dict, port: int) -> dict | None:
    for p in inv.get("ports", []):
        if p.get("port") == port:
            return p
    return None


def free_port(inv: dict, preferred: int, *, avoid: set[int] | None = None) -> int:
    used = {p["port"] for p in inv.get("ports", [])} | (avoid or set())
    port = preferred
    while port in used:
        port += 1
    return port
