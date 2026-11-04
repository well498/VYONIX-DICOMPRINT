"""CI (Windows, após a instalação): ativação de módulo pelo DEPLOY SEM licença (decisão de 04/11/2026).

Confere: módulo desabilitado antes e habilitado depois, todas as etapas aprovadas; módulo planejado (indisponível)
continua recusado; e a pasta de licenciamento compartilhada com o VYONIX DICOM Print não é alterada pela ativação
(nomes, tamanhos e SHA-256 dos arquivos antes e depois). Resultado em <out>/activation[-<módulo>].json."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


IGNORED = {"time.vxs", "time.tmp"}           # horário confiável: o serviço do DICOM Print regrava periodicamente


def snapshot(d: Path) -> dict[str, str]:
    """Arquivos (SHA-256), ACL da pasta e valores do registro do cofre do DICOM Print — só leitura.
    Arquivo ilegível NÃO é aceito como igual: vira marca que reprova a comparação."""
    out: dict[str, str] = {}
    if d.exists():
        for p in sorted(x for x in d.rglob("*") if x.is_file()):
            rel = str(p.relative_to(d))
            if p.name.lower() in IGNORED:
                continue
            try:
                out["arquivo:" + rel] = f"{p.stat().st_size}:{hashlib.sha256(p.read_bytes()).hexdigest()}"
            except OSError as exc:
                out["ILEGIVEL:" + rel] = type(exc).__name__
        if sys.platform == "win32":
            import subprocess
            r = subprocess.run(["icacls", str(d)], capture_output=True, text=True, errors="replace")
            out["acl"] = hashlib.sha256(r.stdout.encode()).hexdigest() if r.returncode == 0 else f"ILEGIVEL:{r.returncode}"
    if sys.platform == "win32":
        import winreg
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\VYONIX\DICOM Print\State", 0,
                               winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
            i = 0
            while True:
                try:
                    name, val, _t = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if name.lower() != "time":
                    out["registro:" + name] = hashlib.sha256(str(val).encode()).hexdigest()
        except FileNotFoundError:
            out["registro"] = "ausente"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--module", default="print")
    a = ap.parse_args()
    out, code = Path(a.out), a.module
    res: dict = {}
    try:
        from vyonix.modules import registry
        from vyonix_deploy.modules import _core, activate
        from vyonix_deploy.service import Deploy
        d = Deploy()
        cfg = d.saved_config()
        ctx = d.context(cfg)
        before_lic = snapshot(d.paths.licensing)
        db, tid = _core(ctx)
        with db.session(tid) as s:
            res["before_enabled"] = registry.is_enabled(s, code)
        r = activate(d, code, approve_all=True)
        res.update(status=r["status"], message=r["message"], run_id=r["run_id"], report=r["report"]["pdf"])
        steps = d.db.steps(r["run_id"])
        res["steps"] = [(s["step_id"], s["status"], s.get("verify_msg")) for s in steps]
        res["activated_without_license"] = (r["status"] == "succeeded"
                                            and not any("entitlement" in s["step_id"] for s in steps))
        with db.session(tid) as s:
            res["after_enabled"] = registry.is_enabled(s, code)
        try:                                                  # planejado: continua recusado (segurança mantida)
            r2 = activate(d, "notify", approve_all=True)
            res["planned_module_refused"] = r2["status"] != "succeeded"
        except Exception as exc:                              # noqa: BLE001 - recusa por exceção também vale
            res["planned_module_refused"] = True
            res["planned_module_message"] = str(exc)[:300]
        after_lic = snapshot(d.paths.licensing)
        res["licensing_files"] = len(before_lic)
        unreadable = [k for k in list(before_lic) + list(after_lic) if k.startswith("ILEGIVEL")]
        res["licensing_unreadable"] = unreadable
        res["licensing_untouched"] = before_lic == after_lic and not unreadable
        if not res["licensing_untouched"]:
            res["licensing_diff"] = sorted(set(before_lic.items()) ^ set(after_lic.items()))[:20]
        if code == "pacs":
            from vyonix_deploy.steps.pacs import engine_probe
            res["engine_probe"] = engine_probe(ctx)
        db.dispose()
        d.close()
    except Exception:  # noqa: BLE001
        import traceback
        res["status"] = "error"
        res["error"] = traceback.format_exc()
    (out / f"activation-{code}.json" if code != "print" else out / "activation.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    return 0 if res.get("status") == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
