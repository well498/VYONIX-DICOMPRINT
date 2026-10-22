"""CI (Windows): passo de IP fixo do DEPLOY num adaptador de loopback (KM-TEST) criado para o teste —
nunca na interface principal do runner. Prova: conflito recusado, aplicação e reversão, reversão
automática por falta de conectividade e restauração pela tarefa de segurança quando o processo do
DEPLOY morre no meio. Resultado em <out>/network.json."""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vyonix_deploy.config import NetworkChoice  # noqa: E402
from vyonix_deploy.steps.network import SAFETY_TASK, StaticIpStep, interface_config  # noqa: E402
from vyonix_deploy.sysrun import as_list, powershell  # noqa: E402


def devcon() -> str | None:
    pats = [r"C:\Program Files (x86)\Windows Kits\10\Tools\*\x64\devcon.exe",
            r"C:\Program Files (x86)\Windows Kits\10\Tools\x64\devcon.exe"]
    for p in pats:
        hits = sorted(glob.glob(p))
        if hits:
            return hits[-1]
    return None


def loopback_aliases() -> list[str]:
    r = powershell("@(Get-NetAdapter | Where-Object { $_.InterfaceDescription -like '*KM-TEST Loopback*' } "
                   "| Sort-Object ifIndex | ForEach-Object { $_.Name })")
    return as_list(r)


def task_info() -> dict:
    return powershell("$t = Get-ScheduledTask -TaskName $A.n -ErrorAction SilentlyContinue; if (-not $t) { return $null }; "
                      "$i = $t | Get-ScheduledTaskInfo; [pscustomobject]@{ state=[string]$t.State; "
                      "last=[string]$i.LastRunTime; result=[int64]$i.LastTaskResult; next=[string]$i.NextRunTime }",
                      {"n": SAFETY_TASK}) or {}


def norm(c: dict) -> dict:
    return {"dhcp": c["dhcp"], "ips": sorted((x["ip"], x["prefix"]) for x in c["ips"] if not x["ip"].startswith("169.254.")),
            "gateway": sorted(c["gateway"]), "dns": sorted(c["dns"])}


def main_nic() -> tuple[str, dict]:
    r = powershell("Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1 | "
                   "ForEach-Object { [pscustomobject]@{ alias=$_.InterfaceAlias; gw=$_.NextHop } }")
    return r["alias"], {"gw": r["gw"], "cfg": norm(interface_config(r["alias"]))}


class Ctx:
    def __init__(self, out: Path) -> None:
        self.paths = type("P", (), {"deploy_dir": out / "deploy-net"})()
        self.paths.deploy_dir.mkdir(parents=True, exist_ok=True)

    def log(self, level, msg):
        print(f"[{level}] {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--child", help=argparse.SUPPRESS)
    a = ap.parse_args()
    out = Path(a.out).resolve()
    if a.child:                       # processo que aplica e é encerrado à força no meio
        alias = a.child
        st = StaticIpStep(NetworkChoice(mode="static", interface=alias, ip="10.250.0.30", prefix=24,
                                        gateway="10.250.0.254", confirmed=True))
        st.apply(Ctx(out))
        return 0
    res: dict = {"ok": False, "checks": []}
    dv = devcon()
    if not dv:
        res["not_run"] = "devcon.exe (Windows Driver Kit) não encontrado no runner: adaptador de loopback indisponível."
        (out / "network.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    try:
        main_alias, main_before = main_nic()
        for _ in range(2):                    # dois adaptadores: um faz o papel do gateway
            r = subprocess.run([dv, "install", os.path.join(os.environ["SystemRoot"], "inf", "netloop.inf"), "*msloop"],
                               capture_output=True, text=True, timeout=300)
            res.setdefault("devcon", []).append((r.stdout + r.stderr)[-200:])
        time.sleep(10)
        names = loopback_aliases()
        assert len(names) >= 2, f"adaptadores de loopback: {names}"
        alias, gw_alias = names[0], names[1]
        res["adapter"], res["gateway_adapter"] = alias, gw_alias
        powershell("Set-NetIPInterface -InterfaceAlias $A.a -Dhcp Disabled; "
                   "New-NetIPAddress -InterfaceAlias $A.a -IPAddress 10.250.0.1 -PrefixLength 24 | Out-Null",
                   {"a": gw_alias}, as_json=False)
        time.sleep(5)
        ctx = Ctx(out)
        before = norm(interface_config(alias))
        res["before"] = before

        # 1) conflito: IP que já responde na rede (gateway da interface principal)
        gw = main_before["gw"]
        st = StaticIpStep(NetworkChoice(mode="static", interface=alias, ip=gw, prefix=24,
                                        gateway=".".join(gw.split(".")[:3] + ["254"]) if not gw.endswith(".254")
                                        else ".".join(gw.split(".")[:3] + ["253"]), confirmed=True))
        try:
            st.apply(ctx)
            res["checks"].append(["conflito recusado", False, "aplicou um IP em uso"])
        except Exception as exc:  # noqa: BLE001
            ok = "conflito" in str(exc) and norm(interface_config(alias)) == before
            res["checks"].append(["conflito recusado", ok, str(exc)[:200]])

        # 2) sem conectividade → reversão automática (60 s)
        st = StaticIpStep(NetworkChoice(mode="static", interface=alias, ip="10.250.0.10", prefix=24,
                                        gateway="10.250.0.254", confirmed=True))
        t0 = time.monotonic()
        try:
            st.apply(ctx)
            res["checks"].append(["reversão automática", False, "aplicou sem conectividade"])
        except Exception as exc:  # noqa: BLE001
            after = norm(interface_config(alias))
            task = powershell("@(Get-ScheduledTask -TaskName $A.n -ErrorAction SilentlyContinue).Count", {"n": SAFETY_TASK})
            res["checks"].append(["reversão automática", after == before and not task,
                                  f"{str(exc)[:160]}; {time.monotonic() - t0:.0f} s; configuração restaurada={after == before}"])

        # 3) aplicação com conectividade (gateway = o próprio endereço) e reversão pelo motor
        st = StaticIpStep(NetworkChoice(mode="static", interface=alias, ip="10.250.0.20", prefix=24,
                                        gateway="10.250.0.1", confirmed=True))
        cap = st.capture(ctx)
        try:
            st.apply(ctx)
            applied = st.check(ctx)
            seen = interface_config(alias)
        except Exception as exc:  # noqa: BLE001
            applied, seen = False, {"erro": str(exc)[:300]}
        st.rollback(ctx, cap)
        time.sleep(3)
        res["checks"].append(["IP fixo aplicado, conferido e revertido", applied and norm(interface_config(alias)) == before,
                              f"aplicado={applied}; observado={seen}; restaurado={norm(interface_config(alias)) == before}"])

        # 4) DEPLOY interrompido no meio: a tarefa de segurança restaura em até ~3 min
        p = subprocess.Popen([sys.executable, __file__, "--out", str(out), "--child", alias])
        end = time.monotonic() + 120
        changed = False
        while time.monotonic() < end:
            if any(ip == "10.250.0.30" for ip, _ in norm(interface_config(alias))["ips"]):
                changed = True
                break
            time.sleep(1)
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        res["task_after_kill"] = task_info()
        restored = False
        end = time.monotonic() + 300
        while changed and time.monotonic() < end:
            time.sleep(10)
            if norm(interface_config(alias)) == before:
                restored = True
                break
        res["task_end"] = task_info()
        res["checks"].append(["tarefa de segurança restaurou após o DEPLOY ser encerrado", changed and restored,
                              f"IP alterado={changed}; restaurado pela tarefa={restored}; tarefa: "
                              f"{res['task_after_kill']} → {res['task_end']}; final={norm(interface_config(alias))}"])
        res["main_interface_untouched"] = norm(interface_config(main_alias)) == main_before["cfg"]
        res["checks"].append(["interface principal intocada", res["main_interface_untouched"], main_alias])
        res["ok"] = all(c[1] for c in res["checks"])
    except Exception:  # noqa: BLE001
        res["error"] = traceback.format_exc()
    finally:
        try:
            subprocess.run([dv, "remove", "*msloop"], capture_output=True, timeout=120)
        except Exception:  # noqa: BLE001
            pass
    (out / "network.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
