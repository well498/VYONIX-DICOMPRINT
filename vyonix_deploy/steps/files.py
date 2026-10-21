"""Diretórios e permissões (ACL). Nunca apaga dados: a reversão só remove pastas criadas nesta
execução e que continuam vazias."""

from __future__ import annotations

import os
from pathlib import Path

from vyonix_deploy.engine import Context, Step
from vyonix_deploy.errors import DeployError
from vyonix_deploy.sysrun import IS_WINDOWS, as_list, powershell

# SIDs (independentes do idioma do Windows)
SYSTEM = "*S-1-5-18"
ADMINS = "*S-1-5-32-544"
USERS = "*S-1-5-32-545"
RIGHTS = {"F": "FullControl", "M": "Modify", "RX": "ReadAndExecute"}


class DirectoryStep(Step):
    category = "armazenamento"

    def __init__(self, key: str, path: Path, label: str) -> None:
        self.id = f"dir.{key}"
        self.path = Path(path)
        self.title = f"Pasta {label}"

    def describe(self, ctx: Context) -> dict:
        return {"current": self.observe(ctx), "proposed": {"path": str(self.path), "exists": True},
                "impact": "Cria a pasta (dados existentes são mantidos).",
                "undo": "Remove a pasta somente se tiver sido criada agora e estiver vazia."}

    def observe(self, ctx: Context) -> dict:
        return {"path": str(self.path), "exists": self.path.is_dir()}

    def desired(self, ctx: Context) -> dict:
        return {"path": str(self.path), "exists": True}

    def check(self, ctx: Context) -> bool:
        return self.path.is_dir()

    def apply(self, ctx: Context) -> None:
        self.path.mkdir(parents=True, exist_ok=True)

    def verify(self, ctx: Context) -> tuple[bool, str]:
        if not self.path.is_dir():
            return False, "pasta inexistente"
        probe = self.path / f".vyx-write-test-{os.getpid()}"
        try:
            probe.write_bytes(b"ok")
            ok = probe.read_bytes() == b"ok"
        except OSError as exc:
            return False, f"sem escrita: {exc}"
        finally:
            try:
                probe.unlink()
            except OSError:
                pass
        return ok, "pasta criada; escrita e leitura testadas"

    def rollback(self, ctx: Context, before: dict) -> None:
        if not before.get("exists") and self.path.is_dir() and not any(self.path.iterdir()):
            self.path.rmdir()

    def how_to_check(self) -> str:
        return f"Explorador de Arquivos: {self.path}"


class AclStep(Step):
    """Permissões explícitas mínimas, sem herança. ``grants`` = [(conta ou *SID, "F"|"M"|"RX")]."""

    category = "armazenamento"

    def __init__(self, key: str, path: Path, label: str, grants: list[tuple[str, str]]) -> None:
        self.id = f"acl.{key}"
        self.path = Path(path)
        self.title = f"Permissões de {label}"
        self.grants = grants

    def _want(self) -> list[dict]:
        return [{"account": a, "rights": RIGHTS[r]} for a, r in self.grants]

    def describe(self, ctx: Context) -> dict:
        return {"current": self.observe(ctx), "proposed": {"path": str(self.path), "inherit": False,
                                                           "grants": self._want()},
                "impact": "Somente sistema, administradores e as contas de serviço do VYONIX acessam a pasta.",
                "undo": "Restaura a lista de permissões anterior (SDDL gravado)."}

    def desired(self, ctx: Context) -> dict:
        return {"path": str(self.path), "inherit": False, "grants": self._want()}

    def observe(self, ctx: Context) -> dict:
        if not IS_WINDOWS or not self.path.exists():
            return {"path": str(self.path), "exists": self.path.exists()}
        r = powershell(r"""
$acl = [System.IO.Directory]::GetAccessControl($A.path)
[pscustomobject]@{ protected=[bool]$acl.AreAccessRulesProtected; sddl=$acl.Sddl
  rules=@($acl.Access | Where-Object { -not $_.IsInherited } | ForEach-Object {
    $sid = try { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value } catch { [string]$_.IdentityReference }
    [pscustomobject]@{ sid=$sid; name=[string]$_.IdentityReference; rights=[string]$_.FileSystemRights; type=[string]$_.AccessControlType;
      inherit=[string]$_.InheritanceFlags } }) }""", {"path": str(self.path)})
        r["rules"] = as_list(r.get("rules"))
        return {"path": str(self.path), "exists": True, **r}

    def _sids(self) -> list[tuple[str, str]]:
        out = []
        for acct, right in self.grants:
            out.append((acct[1:] if acct.startswith("*") else _sid_of(acct), RIGHTS[right]))
        return out

    def check(self, ctx: Context) -> bool:
        if not IS_WINDOWS:
            return self.path.exists()
        cur = self.observe(ctx)
        if not cur.get("exists") or not cur.get("protected"):
            return False
        have = {(r["sid"], r["type"]) : r for r in cur["rules"]}
        want = self._sids()
        if {s for s, _ in want} != {r["sid"] for r in cur["rules"] if r["type"] == "Allow"}:
            return False
        for sid, right in want:
            r = have.get((sid, "Allow"))
            if r is None or right not in r["rights"] or "ContainerInherit" not in r["inherit"]:
                return False
        return not any(r["type"] == "Deny" for r in cur["rules"])

    def capture(self, ctx: Context) -> dict:
        o = self.observe(ctx)
        return {"exists": o.get("exists"), "sddl": o.get("sddl")}

    def apply(self, ctx: Context) -> None:
        if not IS_WINDOWS:
            os.chmod(self.path, 0o750)
            return
        powershell(r"""
$acl = New-Object System.Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
foreach ($g in $A.grants) {
  $sid = New-Object System.Security.Principal.SecurityIdentifier($g.sid)
  $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, $g.rights, 'ContainerInherit,ObjectInherit', 'None', 'Allow')
  $acl.AddAccessRule($rule)
}
[System.IO.Directory]::SetAccessControl($A.path, $acl)
""", {"path": str(self.path), "grants": [{"sid": s, "rights": r} for s, r in self._sids()]}, as_json=False)

    def rollback(self, ctx: Context, before: dict) -> None:
        if IS_WINDOWS and before.get("sddl") and self.path.exists():
            powershell(r"""$acl = [System.IO.Directory]::GetAccessControl($A.path); $acl.SetSecurityDescriptorSddlForm($A.sddl);
[System.IO.Directory]::SetAccessControl($A.path, $acl)""", {"path": str(self.path), "sddl": before["sddl"]}, as_json=False)

    def how_to_check(self) -> str:
        return f"icacls \"{self.path}\""


_SID_CACHE: dict[str, str] = {}


def _sid_of(account: str) -> str:
    if account not in _SID_CACHE:
        r = powershell("(New-Object System.Security.Principal.NTAccount($A.n)).Translate("
                       "[System.Security.Principal.SecurityIdentifier]).Value", {"n": account})
        if not r:
            raise DeployError(f"Conta não encontrada: {account}")
        _SID_CACHE[account] = r
    return _SID_CACHE[account]


class AclGrantStep(Step):
    """Acrescenta permissão a uma pasta compartilhada sem mexer nas demais entradas (ex.: cofre de
    licenciamento usado também pelo DICOM Print)."""

    category = "armazenamento"

    def __init__(self, key: str, path: Path, label: str, account: str, right: str) -> None:
        self.id = f"grant.{key}"
        self.path = Path(path)
        self.account = account
        self.right = right
        self.title = f"Permissão de {account} em {label}"

    def desired(self, ctx: Context) -> dict:
        return {"path": str(self.path), "account": self.account, "rights": RIGHTS[self.right]}

    def observe(self, ctx: Context) -> dict:
        if not IS_WINDOWS or not self.path.exists():
            return {"path": str(self.path), "present": False}
        sid = _sid_of(self.account)
        r = powershell(r"""@(([System.IO.Directory]::GetAccessControl($A.path)).Access | Where-Object { -not $_.IsInherited -and $_.AccessControlType -eq 'Allow' } | ForEach-Object {
  $s = try { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value } catch { '' }
  if ($s -eq $A.sid) { [string]$_.FileSystemRights } })""", {"path": str(self.path), "sid": sid})
        rights = as_list(r)
        return {"path": str(self.path), "present": any(RIGHTS[self.right] in x for x in rights), "rights": rights}

    def describe(self, ctx: Context) -> dict:
        return {"current": self.observe(ctx), "proposed": self.desired(ctx),
                "impact": "Acrescenta uma permissão; as demais permissões da pasta não mudam.",
                "undo": "Remove a permissão acrescentada."}

    def check(self, ctx: Context) -> bool:
        return bool(self.observe(ctx).get("present"))

    def apply(self, ctx: Context) -> None:
        powershell(r"""
$acl = [System.IO.Directory]::GetAccessControl($A.path)
$sid = New-Object System.Security.Principal.SecurityIdentifier($A.sid)
$acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($sid, $A.rights, 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
[System.IO.Directory]::SetAccessControl($A.path, $acl)""", {"path": str(self.path), "sid": _sid_of(self.account),
                                                  "rights": RIGHTS[self.right]}, as_json=False)

    def rollback(self, ctx: Context, before: dict) -> None:
        if before.get("present"):
            return
        powershell(r"""
$acl = [System.IO.Directory]::GetAccessControl($A.path)
$sid = New-Object System.Security.Principal.SecurityIdentifier($A.sid)
$acl.PurgeAccessRules($sid); [System.IO.Directory]::SetAccessControl($A.path, $acl)""",
                   {"path": str(self.path), "sid": _sid_of(self.account)}, as_json=False)


class FilesPresentStep(Step):
    """Arquivos do programa (copiados pelo instalador). Só confere; não há o que aplicar aqui."""

    category = "aplicacao"
    id = "app.files"
    reversible = False

    def __init__(self, install_dir: Path, required: list[str], version: str) -> None:
        self.dir = Path(install_dir)
        self.required = required
        self.version = version
        self.title = f"Arquivos do VYONIX {version}"

    def desired(self, ctx: Context) -> dict:
        return {"dir": str(self.dir), "version": self.version, "files": self.required}

    def observe(self, ctx: Context) -> dict:
        v = None
        try:
            v = (self.dir / "VERSION.txt").read_text(encoding="utf-8").strip()
        except OSError:
            pass
        return {"dir": str(self.dir), "version": v, "missing": [f for f in self.required if not (self.dir / f).exists()]}

    def describe(self, ctx: Context) -> dict:
        return {"current": self.observe(ctx), "proposed": self.desired(ctx),
                "impact": "Conferência dos arquivos instalados pelo VYONIX_Setup.", "undo": "—"}

    def check(self, ctx: Context) -> bool:
        o = self.observe(ctx)
        return not o["missing"] and o["version"] == self.version

    def apply(self, ctx: Context) -> None:
        o = self.observe(ctx)
        raise DeployError("Arquivos do programa ausentes ou de outra versão "
                          f"(versão {o['version'] or '—'}; faltando: {', '.join(o['missing']) or 'nenhum'}). "
                          "Execute novamente o VYONIX_Setup_x64.exe.")
