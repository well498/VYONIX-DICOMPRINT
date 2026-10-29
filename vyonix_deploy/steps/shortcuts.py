"""Atalhos no menu Iniciar (todos os usuários): VYONIX, VYONIX Administração, VYONIX Diagnóstico e
VYONIX Relatórios Técnicos.

O atalho **VYONIX** executa ``vyonix-deploy abrir``: confere se o sistema está funcionando e abre o navegador; se não
estiver, abre o diagnóstico de inicialização com o que falhou e como resolver (antes era um link direto, que só
mostrava "não foi possível acessar o site")."""

from __future__ import annotations

import os
from pathlib import Path

from vyonix_deploy.engine import Context, Step
from vyonix_deploy.sysrun import IS_WINDOWS, powershell


LEGACY = ("VYONIX.url",)          # atalhos de versões anteriores substituídos


def start_menu_dir() -> Path:
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / \
        "Programs" / "VYONIX"


class ShortcutsStep(Step):
    category = "atalho"
    id = "shortcuts"
    title = "Atalhos do VYONIX no menu Iniciar"

    def __init__(self, https_port: int, deploy_exe: Path, reports_dir: Path, folder: Path | None = None) -> None:
        self.folder = folder or start_menu_dir()
        base = f"https://localhost:{https_port}/"
        self.items = {
            "VYONIX.lnk": {"target": str(deploy_exe), "args": f"abrir --porta {https_port}"},
            "VYONIX Administração.url": {"url": base + "#/configuracoes"},
            "VYONIX Diagnóstico.lnk": {"target": str(deploy_exe), "args": "wizard --diagnose", "admin": True},
            "VYONIX Relatórios Técnicos.lnk": {"target": str(reports_dir), "args": ""},
        }

    def desired(self, ctx: Context) -> dict:
        return {"folder": str(self.folder), "items": self.items}

    def observe(self, ctx: Context) -> dict:
        return {"folder": str(self.folder), "present": sorted(n for n in self.items if (self.folder / n).exists())}

    def describe(self, ctx: Context) -> dict:
        return {"current": self.observe(ctx), "proposed": self.desired(ctx),
                "impact": "Cria a pasta VYONIX no menu Iniciar com os quatro atalhos.",
                "undo": "Remove os atalhos criados."}

    def check(self, ctx: Context) -> bool:
        if not all((self.folder / n).exists() for n in self.items):
            return False
        for n, spec in self.items.items():
            if "url" in spec and f"URL={spec['url']}" not in (self.folder / n).read_text(encoding="utf-8",
                                                                                          errors="ignore"):
                return False
        return True

    def apply(self, ctx: Context) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        for old in LEGACY:
            (self.folder / old).unlink(missing_ok=True)
        lnks = []
        for n, spec in self.items.items():
            p = self.folder / n
            if "url" in spec:
                p.write_text(f"[InternetShortcut]\r\nURL={spec['url']}\r\n", encoding="utf-8")
            else:
                lnks.append({"path": str(p), "target": spec["target"], "args": spec["args"],
                             "admin": bool(spec.get("admin"))})
        if lnks and IS_WINDOWS:
            powershell(r"""$sh = New-Object -ComObject WScript.Shell
foreach ($l in $A.links) { $s = $sh.CreateShortcut($l.path); $s.TargetPath = $l.target; $s.Arguments = $l.args; $s.Save()
  if ($l.admin) { $b = [IO.File]::ReadAllBytes($l.path); $b[0x15] = $b[0x15] -bor 0x20; [IO.File]::WriteAllBytes($l.path, $b) } }""",
                       {"links": lnks}, as_json=False)
        elif lnks:
            for spec in lnks:
                Path(spec["path"]).write_text(spec["target"], encoding="utf-8")

    def rollback(self, ctx: Context, before: dict) -> None:
        for n in self.items:
            if n not in before.get("present", []):
                try:
                    (self.folder / n).unlink()
                except OSError:
                    pass
        try:
            self.folder.rmdir()
        except OSError:
            pass
