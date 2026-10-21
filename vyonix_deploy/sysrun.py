"""Execução de comandos do sistema (PowerShell, sc.exe, icacls, netsh) com registro e sem shell.

Nada aqui interpreta texto do usuário como comando: argumentos vão como lista, e scripts PowerShell
vão codificados (``-EncodedCommand``) com os valores passados como JSON em variável de ambiente.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from vyonix_deploy.errors import DeployError

IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0


def run(args: list[str], *, timeout: float = 120, check: bool = False, env: dict | None = None,
        input_text: str | None = None) -> Result:
    kw: dict[str, Any] = {}
    if IS_WINDOWS:
        kw["creationflags"] = CREATE_NO_WINDOW
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout, env=env, input=input_text.encode() if input_text
                           else None, **kw)
    except FileNotFoundError as exc:
        raise DeployError(f"Programa não encontrado: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DeployError(f"Tempo esgotado ({timeout:.0f} s) executando {os.path.basename(args[0])}.") from exc
    out = _decode(p.stdout)
    err = _decode(p.stderr)
    r = Result(p.returncode, out, err)
    if check and not r.ok:
        raise DeployError(f"{os.path.basename(args[0])} falhou (código {r.code}): {(err or out).strip()[:500]}")
    return r


def _decode(b: bytes) -> str:
    for enc in ("utf-8", "cp850", "cp1252"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


PS_PRELUDE = ("$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';"
              "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
              "$A = if ($env:VYX_PS_ARGS) { $env:VYX_PS_ARGS | ConvertFrom-Json } else { $null };")


def powershell(script: str, args: dict | None = None, *, timeout: float = 180, as_json: bool = True,
               check: bool = True) -> Any:
    """Executa um script PowerShell; ``$A`` contém ``args``. Com ``as_json``, o script deve emitir um
    objeto que é convertido com ``ConvertTo-Json``."""
    if not IS_WINDOWS:
        raise DeployError("PowerShell só está disponível no Windows.")
    body = PS_PRELUDE + (f"& {{ {script} }} | ConvertTo-Json -Depth 8 -Compress" if as_json else script)
    enc = base64.b64encode(body.encode("utf-16-le")).decode()
    env = dict(os.environ)
    env["VYX_PS_ARGS"] = json.dumps(args or {})
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0",
                       "powershell.exe")
    r = run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
            timeout=timeout, env=env)
    if check and not r.ok:
        raise DeployError("PowerShell: " + (r.err or r.out).strip()[:800])
    if not as_json:
        return r
    txt = r.out.strip()
    if not txt:
        return None
    try:
        return json.loads(txt)
    except ValueError as exc:
        raise DeployError(f"PowerShell devolveu saída ilegível: {txt[:300]}") from exc


def as_list(v: Any) -> list:
    """ConvertTo-Json devolve objeto único em vez de lista com 1 item."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]
