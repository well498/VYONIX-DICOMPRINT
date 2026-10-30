"""Aceitação da Fase 2 (VYONIX DEPLOY) no runner Windows do CI — tudo de verdade: instala pelo
VYONIX_Setup_x64.exe, confere no estado real do Windows, repete, quebra e repara, atualiza, ativa
módulo, testa rede em adaptador de loopback e desinstala.

Uso (como administrador, na raiz do repositório):
    python tools/ci_deploy_acceptance.py --setup dist\\installer-platform\\VYONIX_Setup_x64.exe
        --dist dist\\VyonixPlatform [--print-setup VYONIX_DICOM_Print_Setup.exe] --out dist\\acceptance

Resultado: ``acceptance.json`` e ``acceptance.md`` (Aprovado / Reprovado / Não executado com motivo).
Código de saída 1 se algum critério for reprovado.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
import traceback
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
print("::notice title=Aceitação::script iniciado", flush=True)

from vyonix_deploy.paths import default_paths  # noqa: E402
from vyonix_deploy.steps.services import query_service  # noqa: E402
from vyonix_deploy.sysrun import as_list, powershell  # noqa: E402

PATHS = default_paths()
PF = Path(os.environ.get("ProgramW6432", r"C:\Program Files"))
INSTALL = PF / "VYONIX" / "Platform"
DEPLOY_EXE = INSTALL / "vyonix-deploy.exe"
ADMIN_PW = "Admin-CI-Fase2x"
ORG = "clinica-ci"
RESULTS: list[dict] = []
OUT: Path


def _ann(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def record(crit: str, name: str, result: str, detail: str = "") -> None:
    RESULTS.append({"criterio": crit, "teste": name, "resultado": result, "detalhe": detail[:3000]})
    print(f"[{result}] {crit} · {name}: {detail[:300]}", flush=True)
    if result != "Aprovado":                     # o GitHub limita 10 anotações de cada nível por passo
        level = "error" if result == "Reprovado" else "warning"
        print(f"::{level} title={crit} {result}::{_ann(name + ' — ' + detail[:2500])}", flush=True)


def check(crit: str, name: str):
    def deco(fn):
        try:
            detail = fn() or ""
            record(crit, name, "Aprovado", str(detail))
        except NotRun as exc:
            record(crit, name, "Não executado", str(exc))
        except Exception as exc:  # noqa: BLE001
            record(crit, name, "Reprovado", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-1200:]}")
        return fn
    return deco


class NotRun(Exception):
    pass


def sh(args, *, timeout=900, env=None, ok=(0,)) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    if str(args[0]).lower() in ("powershell", "powershell.exe"):      # mesmo ambiente do computador do cliente:
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")         # módulos do Windows PowerShell 5.1, não do 7
        pf = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files")
        e["PSModulePath"] = os.pathsep.join([os.path.join(sysroot, "System32", "WindowsPowerShell", "v1.0", "Modules"),
                                             os.path.join(pf, "WindowsPowerShell", "Modules")])
    e.update(env or {})
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout, env=e,
                       encoding="utf-8", errors="replace")
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    with open(OUT / "logs" / "comandos.log", "a", encoding="utf-8") as f:
        f.write(f"\n$ {' '.join(map(str, args))}\n[código {p.returncode}]\n{p.stdout[-6000:]}\n{p.stderr[-3000:]}\n")
    if ok is not None and p.returncode not in ok:
        raise AssertionError(f"{Path(str(args[0])).name} código {p.returncode}: {(p.stdout + p.stderr)[-800:]}")
    return p


def deploy(*args, ok=(0,), timeout=1800, env=None):
    return sh([DEPLOY_EXE, *args], ok=ok, timeout=timeout, env={"VYONIX_ADMIN_PASSWORD": ADMIN_PW, **(env or {})})


def health(port: int, timeout: float = 120) -> dict:
    cert = PATHS.data_dir / "tls" / "server.crt"
    ctx = ssl.create_default_context(cafile=str(cert))
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), urllib.request.ProxyHandler({}))
            with op.open(f"https://localhost:{port}/api/v1/health", timeout=10) as r:
                d = json.loads(r.read())
                if d.get("status") == "ok":
                    return d
                last = d
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(3)
    raise AssertionError(f"/health não respondeu em https://localhost:{port}: {last}")


class Api:
    def __init__(self, port: int) -> None:
        import http.cookiejar
        self.base = f"https://localhost:{port}/api/v1"
        self.jar = http.cookiejar.CookieJar()
        ctx = ssl.create_default_context(cafile=str(PATHS.data_dir / "tls" / "server.crt"))
        self.op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx),
                                              urllib.request.HTTPCookieProcessor(self.jar), urllib.request.ProxyHandler({}))
        self.csrf = ""

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "X-CSRF-Token": self.csrf})
        with self.op.open(req, timeout=20) as r:
            return json.loads(r.read() or b"null")

    def login(self):
        me = self.call("POST", "/auth/login", {"username": "admin", "password": ADMIN_PW})
        self.csrf = me["csrf"]
        return me


def runs() -> list[dict]:
    p = deploy("runs")
    return json.loads(p.stdout)


def last_run_steps() -> tuple[dict, list[dict]]:
    import sqlite3
    c = sqlite3.connect(str(PATHS.db_file))
    c.row_factory = sqlite3.Row
    r = c.execute("SELECT * FROM runs ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
    steps = [dict(x) for x in c.execute("SELECT * FROM steps WHERE run_id = ? ORDER BY seq", (r["id"],))]
    out = dict(r)
    c.close()
    return out, steps


def diagnose() -> dict:
    p = deploy("diagnose", "--json", ok=(0, 1))
    return json.loads(p.stdout)


def problem_ids(d: dict) -> set[str]:
    return {p["id"] for p in d["problems"]}


class Listener:
    """Outro processo ocupando uma porta TCP (cenário de conflito)."""

    def __init__(self, port: int) -> None:
        self.port = port
        mark = OUT / f"listen-{port}-{time.time_ns()}.ok"
        code = (f"import socket,time;s=socket.socket();s.bind(('0.0.0.0',{port}));s.listen(5);"
                f"open(r'{mark}','w').write('1');time.sleep(3600)")
        self.p = subprocess.Popen([sys.executable, "-c", code])
        end = time.monotonic() + 20
        while not mark.exists() and time.monotonic() < end:
            time.sleep(0.2)
        assert mark.exists(), "processo de teste não ocupou a porta"

    def kill(self) -> None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.p.pid)], capture_output=True)
        end = time.monotonic() + 60
        while time.monotonic() < end:
            with socket.socket() as s:
                s.settimeout(1)
                if s.connect_ex(("127.0.0.1", self.port)) != 0:
                    return
            time.sleep(1)
        raise AssertionError(f"porta {self.port} continua ocupada após encerrar o processo de teste")


def listener(port: int) -> Listener:
    return Listener(port)


def secrets_values() -> list[str]:
    from vyonix.secrets import SecretStore
    vals = [ADMIN_PW]
    for d in (PATHS.data_dir, PATHS.deploy_dir):
        s = SecretStore(d)
        try:
            for n in s._load():
                v = s.get(n)
                if v:
                    vals.append(v.decode("utf-8", "ignore"))
        except Exception:  # noqa: BLE001
            pass
    return [v for v in vals if len(v) >= 6]


def pdf_text(p: Path) -> str:
    from pypdf import PdfReader
    return "\n".join(pg.extract_text() or "" for pg in PdfReader(str(p)).pages)


def reports_of(run_id: str) -> tuple[Path, Path]:
    import sqlite3
    c = sqlite3.connect(str(PATHS.db_file))
    rows = c.execute("SELECT kind, path FROM reports WHERE run_id = ?", (run_id,)).fetchall()
    c.close()
    d = {k: Path(p) for k, p in rows}
    return d["pdf"], d["manifest"]


def installation_id() -> str:
    from app.licensing.installation import InstallationManager
    from app.licensing.vault import FileBackend, RegistryBackend, Vault, machine_sealer
    v = Vault([FileBackend(PATHS.licensing), RegistryBackend()], machine_sealer(PATHS.licensing))
    rec, _ = v.best("installation", repair=False)
    return (rec or {}).get("installation_id") or "—"


def print_service_check(print_dir: Path) -> str:
    rep = OUT / f"print-check-{int(time.time())}.json"
    for _ in range(20):
        p = sh([print_dir / "Vyonix.exe", "--service-check", "--report", rep], ok=None, timeout=120)
        if p.returncode == 0:
            break
        time.sleep(3)
    r = json.loads(rep.read_text(encoding="utf-8"))
    if not r.get("ok"):
        raise AssertionError(f"service-check do DICOM Print falhou: {r.get('error')}")
    e = r.get("echo") or {}
    return (f"C-ECHO storage {e.get('storage_bound', {}).get('ms')} ms, print {e.get('print_bound', {}).get('ms')} ms; "
            f"serviço {r.get('status', {}).get('version')}")


# ======================================================================================================

def main() -> int:
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", required=True)
    ap.add_argument("--dist", required=True)
    ap.add_argument("--print-setup")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    OUT = Path(a.out).resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    setup, dist = Path(a.setup).resolve(), Path(a.dist).resolve()
    cfg_file = OUT / "opcoes.json"
    cfg_file.write_text(json.dumps({"organization": ORG, "organization_name": "Clínica CI", "admin_user": "admin",
                                    "https_port": 8444, "pg_port": 5544}, ensure_ascii=False), encoding="utf-8")
    print_dir = PF / "VYONIX" / "DICOM Print"
    state: dict = {}

    # ---------------------------------------------------------------- preparação: regra alheia, perfis
    powershell("New-NetFirewallRule -Name 'CI-Externa-1' -DisplayName 'Regra externa do CI' -Direction Inbound "
               "-Action Allow -Protocol TCP -LocalPort 9999 -Profile Any | Out-Null", as_json=False)
    profiles_before = as_list(powershell("Get-NetFirewallProfile | ForEach-Object { [pscustomobject]@{ n=[string]$_.Name; "
                                         "e=[string]$_.Enabled } }"))

    # ---------------------------------------------------------------- 2.8 (parte): DICOM Print antes
    if a.print_setup and Path(a.print_setup).exists():
        @check("2.8", "DICOM Print instalado antes da plataforma e respondendo")
        def _():
            sh([a.print_setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/TASKS=service,firewall",
                f"/LOG={OUT / 'setup-print.log'}"], timeout=900)
            sh([print_dir / "Vyonix.exe", "--license", "demo", "--report", OUT / "print-demo.json"], ok=None)
            state["print_echo_before"] = print_service_check(print_dir)
            state["iid_before"] = installation_id()
            return f"{state['print_echo_before']}; Installation ID {state['iid_before']}"
    else:
        record("2.8", "DICOM Print instalado antes da plataforma", "Não executado",
               "Instalador do DICOM Print não fornecido a este pipeline.")

    # ---------------------------------------------------------------- 2.1 inventário sem escrita
    @check("2.1", "Inventário com token restrito (sem privilégio administrativo) e sem alterar o sistema")
    def _():
        inv_file = OUT / "inventario-restrito.json"
        db_before = PATHS.db_file.exists()
        cmd = f'cmd /c ""{dist / "vyonix-deploy.exe"}" inventory --out "{inv_file}""'
        subprocess.Popen(["runas", "/trustlevel:0x20000", cmd])
        end = time.monotonic() + 300
        while not inv_file.exists() and time.monotonic() < end:
            time.sleep(2)
        time.sleep(2)
        inv = json.loads(inv_file.read_text(encoding="utf-8"))
        assert inv["admin"] is False, "inventário deveria rodar sem privilégio administrativo"
        assert inv["os"]["build"] >= 17763 and inv["nics"] and inv["disks"], "inventário incompleto"
        assert PATHS.db_file.exists() == db_before, "inventário criou o banco do DEPLOY"
        return (f"{inv['os']['caption']} build {inv['os']['build']}; {len(inv['nics'])} interfaces; "
                f"{len(inv['ports'])} portas em escuta; {len(inv['services'])} serviços relevantes; usuário {inv['user']}")

    @check("2.1", "Impeditivo detectado: porta HTTPS ocupada (nada alterado, relatório gerado)")
    def _():
        cfg2 = OUT / "opcoes-porta.json"           # porta própria: um listener encerrado pode demorar a sumir
        cfg2.write_text(json.dumps({**json.loads(cfg_file.read_text(encoding="utf-8")), "https_port": 8460}),
                        encoding="utf-8")
        lp = listener(8460)
        try:
            p = sh([dist / "vyonix-deploy.exe", "install", "--config", cfg2, "--plan-only"], ok=(2,))
        finally:
            lp.kill()
        assert "8460" in p.stdout and "Relatório" in p.stdout, p.stdout[-400:]
        assert query_service("VyonixCore") is None
        return p.stdout.strip().splitlines()[-2][:200]

    # ---------------------------------------------------------------- 2.5 instalação
    @check("2.5", "Instalação silenciosa pelo VYONIX_Setup_x64.exe com plano aprovado")
    def _():
        sh([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DEPLOYCONFIG={cfg_file}",
            f"/LOG={OUT / 'setup-install.log'}"], env={"VYONIX_ADMIN_PASSWORD": ADMIN_PW}, timeout=1800)
        run, steps = last_run_steps()
        assert run["kind"] == "install" and run["status"] == "succeeded", f"{run['status']}: {run['message']}"
        state["install_run"] = run["id"]
        return f"execução {run['id']}: " + ", ".join(f"{s['step_id']}={s['status']}" for s in steps)

    @check("2.5", "GET /api/v1/health responde por HTTPS (certificado conferido)")
    def _():
        d = health(8444)
        return json.dumps(d)

    # ---------------------------------------------------------------- 2.10 inicialização e acesso web (28/10/2026)
    @check("2.10", "Diagnóstico de inicialização sem administrador: tudo funcionando; endereços localhost e IP da rede")
    def _():
        out_json = OUT / "verificar-restrito.json"
        out_json.unlink(missing_ok=True)
        cmd = f'cmd /c ""{DEPLOY_EXE}" verificar --porta 8444 --json > "{out_json}""'
        subprocess.Popen(["runas", "/trustlevel:0x20000", cmd])
        end = time.monotonic() + 180
        while time.monotonic() < end:
            if out_json.exists() and out_json.stat().st_size > 50:
                try:
                    r = json.loads(out_json.read_text(encoding="utf-8", errors="replace"))
                    break
                except ValueError:
                    pass
            time.sleep(2)
        else:
            raise AssertionError("verificar (token restrito) não produziu resultado")
        bad = [c for c in r["checks"] if c["status"] == "fail"]
        assert r["web_ok"] and not bad, bad or r
        assert any(u.startswith("https://localhost:8444") for u in r["urls"]), r["urls"]
        lan = [u for u in r["urls"] if "localhost" not in u]
        assert lan, f"nenhum IP da rede respondeu: {r['checks']}"
        state["lan_url"] = lan[0]
        return f"status {r['status']}; endereços {r['urls']}; " + "; ".join(f"{c['id']}={c['status']}" for c in r["checks"])

    @check("2.10", "Acesso pelo IP da rede por HTTPS e http:// na mesma porta redirecionado para https://")
    def _():
        import http.client
        from urllib.parse import urlparse
        u = urlparse(state["lan_url"])
        ctx = ssl._create_unverified_context()
        c = http.client.HTTPSConnection(u.hostname, u.port, context=ctx, timeout=15)
        c.request("GET", "/api/v1/health")
        r = c.getresponse()
        body = json.loads(r.read())
        assert r.status == 200 and body["status"] == "ok" and body["database"], body
        c.request("GET", "/")
        r = c.getresponse()
        page = r.read()
        assert r.status == 200 and b"<html" in page[:2000].lower(), r.status
        h = http.client.HTTPConnection(u.hostname, u.port, timeout=15)
        h.request("GET", "/pacientes")
        r = h.getresponse()
        assert r.status == 301 and r.getheader("Location") == f"https://{u.hostname}:{u.port}/pacientes", \
            (r.status, r.getheader("Location"))
        return f"https://{u.hostname}:{u.port}/ responde (API e interface); http:// → {r.getheader('Location')}"

    @check("2.10", "Firewall: regra do perfil Público só para a sub-rede local (rede nova ou VM classificada como pública)")
    def _():
        r = powershell(r"""$r = Get-NetFirewallRule -Name 'VYONIX-core-lan-8444'; $af = $r | Get-NetFirewallAddressFilter
$pf = $r | Get-NetFirewallPortFilter
[pscustomobject]@{ profile=[string]$r.Profile; remote=@($af.RemoteAddress); port=[string]$pf.LocalPort; enabled=[string]$r.Enabled }""")
        assert r["profile"] == "Public" and r["port"] == "8444" and r["enabled"] == "True", r
        assert [x.lower() for x in as_list(r["remote"])] == ["localsubnet"], r
        return json.dumps(r)

    def pg_diag() -> str:
        """Diagnóstico para quando o banco não volta (anexado à falha: os artefatos do CI não são legíveis daqui)."""
        out = []
        for n in ("VyonixPostgreSQL", "VyonixCore", "VyonixWorker"):
            q = query_service(n) or {}
            out.append(f"{n}={q.get('state')} pid={q.get('pid')}")
        try:
            out.append("porta 5544: " + json.dumps(powershell(
                "@(Get-NetTCPConnection -LocalPort 5544 -ErrorAction SilentlyContinue | ForEach-Object { "
                "$p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; "
                "[pscustomobject]@{ state=[string]$_.State; pid=$_.OwningProcess; vivo=[bool]$p; nome=$(if ($p) { $p.Name } else { '' }) } })"),
                ensure_ascii=False)[:600])
            out.append("processos: " + json.dumps(powershell(
                "@(Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('postgres.exe','pg_ctl.exe') } | "
                "ForEach-Object { [pscustomobject]@{ pid=$_.ProcessId; pai=$_.ParentProcessId; cmd=([string]$_.CommandLine).Substring(0, [Math]::Min(120, ([string]$_.CommandLine).Length)) } })"),
                ensure_ascii=False)[:900])
            out.append("log do PostgreSQL (Eventos): " + json.dumps(powershell(
                "@(Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='VYONIX PostgreSQL'} -MaxEvents 15 "
                "-ErrorAction SilentlyContinue | ForEach-Object { $_.TimeCreated.ToString('HH:mm:ss') + ' ' + "
                "([string]$_.Message).Substring(0, [Math]::Min(200, ([string]$_.Message).Length)) })"),
                ensure_ascii=False)[:1800])
            out.append("SCM: " + json.dumps(powershell(
                "@(Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Service Control Manager'} -MaxEvents 40 "
                "-ErrorAction SilentlyContinue | Where-Object { $_.Message -like '*VYONIX*' } | Select-Object -First 8 | "
                "ForEach-Object { $_.TimeCreated.ToString('HH:mm:ss') + ' ' + $_.Message.Substring(0, [Math]::Min(160, $_.Message.Length)) })"),
                ensure_ascii=False)[:1200])
        except Exception as exc:  # noqa: BLE001
            out.append(f"(diagnóstico incompleto: {exc})")
        return " ;; ".join(out)

    @check("2.10", "Banco de dados derrubado (processo encerrado à força): recuperado sozinho e o sistema volta a responder")
    def _():
        before = query_service("VyonixCore")["pid"]
        sh(["taskkill", "/F", "/T", "/IM", "postgres.exe"], ok=None)
        time.sleep(3)
        p = deploy("verificar", "--porta", "8444", "--json", ok=(0, 1))
        during = json.loads(p.stdout)
        try:
            d = health(8444, timeout=300)
        except AssertionError as exc:
            raise AssertionError(f"{exc} — DIAGNÓSTICO: {pg_diag()}") from None
        after = deploy("verificar", "--porta", "8444", "--json", ok=(0,))
        assert json.loads(after.stdout)["web_ok"]
        return (f"durante a queda: {[(c['id'], c['status']) for c in during['checks'] if c['status'] != 'ok']}; "
                f"depois: health {d['status']}/banco {d['database']}; Core PID {before} → {query_service('VyonixCore')['pid']}")

    @check("2.10", "Ordem de inicialização: com tudo parado, iniciar o Core sobe o banco antes (dependência) e o acesso volta")
    def _():
        powershell("Stop-Service VyonixWorker, VyonixCore -Force; Stop-Service VyonixPostgreSQL -Force", as_json=False,
                   timeout=240)
        p = deploy("verificar", "--porta", "8444", "--json", ok=(1,))
        down = json.loads(p.stdout)
        assert not down["web_ok"] and any(c["id"] == "service.VyonixCore" and c["status"] == "fail"
                                          for c in down["checks"]), down
        powershell("Start-Service VyonixCore; Start-Service VyonixWorker", as_json=False, timeout=240)
        health(8444, timeout=180)
        states = {n: query_service(n)["state"] for n in ("VyonixPostgreSQL", "VyonixCore", "VyonixWorker")}
        assert all(v == "Running" for v in states.values()), states
        return f"parado: {[(c['id'], c['status']) for c in down['checks'] if c['status'] != 'ok'][:6]}; depois: {states}"

    @check("2.11", "Kit de validação do proprietário (Validar_VYONIX.ps1, somente leitura): C1–C4 aprovados; reinício pendente")
    def _():
        ps1 = ROOT / "installer" / "validacao" / "Validar_VYONIX.ps1"
        outdir = OUT / "validacao"
        outdir.mkdir(parents=True, exist_ok=True)
        p = sh(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Porta", "8444",
                "-Saida", outdir, "-SemAbrir"], timeout=300)
        text = p.stdout
        for need in ("[APROVADO] VYONIX instalado e configurado", "[APROVADO] Servicos do Windows",
                     "[APROVADO] Acesso neste computador", "[APROVADO] Acesso pelo IP da rede",
                     "[PENDENTE] Reinicializacao real do Windows"):
            assert need in text, f"faltou '{need}' em: {text[-1500:]}"
        reports = list(outdir.glob("VYONIX_Validacao_*.html"))
        assert reports and "Resultado geral" in reports[0].read_text(encoding="utf-8-sig"), reports
        return " | ".join(l for l in text.splitlines() if l.startswith("["))[:900]

    @check("2.3", "Serviços com conta virtual, início automático, dependências e recuperação após falha")
    def _():
        out = []
        for name, deps, delayed in (("VyonixPostgreSQL", [], False), ("VyonixCore", ["VyonixPostgreSQL"], True),
                                    ("VyonixWorker", ["VyonixPostgreSQL"], True)):
            q = query_service(name)
            assert q, f"{name} ausente"
            assert q["account"].lower() == f"nt service\\{name}".lower(), f"{name}: conta {q['account']}"
            assert q["start"] == "Auto" and bool(q["delayed"]) == delayed, f"{name}: início {q['start']}/{q['delayed']}"
            assert sorted(q["depends"]) == deps, f"{name}: dependências {q['depends']}"
            assert q["recovery"]["actions"] == [[1, 5000], [1, 15000], [1, 60000]], f"{name}: recuperação {q['recovery']}"
            assert q["state"] == "Running", f"{name}: {q['state']}"
            out.append(f"{name}: {q['account']}, {q['start']}{' (atrasado)' if q['delayed'] else ''}, "
                       f"recuperação {q['recovery']['actions']}")
        return "; ".join(out)

    @check("2.3", "Firewall: regra nomeada do VYONIX criada; regras alheias intactas; firewall nunca desligado")
    def _():
        r = powershell(r"""$r = Get-NetFirewallRule -Name 'VYONIX-core-https-8444'; $pf = $r | Get-NetFirewallPortFilter
$ap = $r | Get-NetFirewallApplicationFilter
[pscustomobject]@{ name=$r.DisplayName; profile=[string]$r.Profile; port=[string]$pf.LocalPort; program=[string]$ap.Program; enabled=[string]$r.Enabled }""")
        assert r["name"] == "VYONIX - Core HTTPS - 8444" and r["port"] == "8444" and r["enabled"] == "True", r
        assert set(r["profile"].replace(" ", "").split(",")) == {"Domain", "Private"}, r
        assert r["program"].lower().endswith("vyonixplatform.exe"), r
        ext = powershell("Get-NetFirewallRule -Name 'CI-Externa-1' | ForEach-Object { [string]$_.Enabled }")
        assert ext == "True", "regra externa alterada"
        prof = as_list(powershell("Get-NetFirewallProfile | ForEach-Object { [pscustomobject]@{ n=[string]$_.Name; "
                                  "e=[string]$_.Enabled } }"))
        assert prof == profiles_before, f"perfis mudaram: {profiles_before} → {prof}"
        return f"{r}; regra externa intacta; perfis {prof}"

    @check("2.3", "Pastas com ACL mínima (sem herança; só sistema, administradores e contas de serviço)")
    def _():
        r = powershell(r"""$a = [System.IO.Directory]::GetAccessControl($A.p)
[pscustomobject]@{ prot=[bool]$a.AreAccessRulesProtected; ids=@($a.Access | ForEach-Object { [string]$_.IdentityReference }) }""",
                       {"p": str(PATHS.data_dir)})
        ids = [x.lower() for x in as_list(r["ids"])]
        assert r["prot"], "herança não removida"
        assert not any("users" in x or "usuários" in x or "everyone" in x or "todos" in x for x in ids), ids
        assert any("vyonixcore" in x for x in ids) and any("vyonixworker" in x for x in ids), ids
        return f"{PATHS.data_dir}: {ids}"

    @check("2.3", "Atalhos no menu Iniciar e certificado autoassinado registrado como pendência")
    def _():
        sm = Path(os.environ["ProgramData"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "VYONIX"
        names = sorted(p.name for p in sm.iterdir())
        need = {"VYONIX.lnk", "VYONIX Administração.url", "VYONIX Diagnóstico.lnk", "VYONIX Relatórios Técnicos.lnk",
                "VYONIX - Assistente de instalacao.lnk", "VYONIX - Verificar funcionamento.lnk",
                "VYONIX - Reparar instalacao.lnk", "VYONIX - Validar instalacao.lnk"}
        assert need <= set(names) and "VYONIX.url" not in names, names
        args = powershell("(New-Object -ComObject WScript.Shell).CreateShortcut($A.p).Arguments",
                          {"p": str(sm / "VYONIX.lnk")})
        assert args == "abrir --porta 8444", args
        runas = (sm / "VYONIX Diagnóstico.lnk").read_bytes()[0x15] & 0x20
        assert runas, "atalho do diagnóstico sem 'executar como administrador'"
        pdf, man = reports_of(state["install_run"])
        m = json.loads(man.read_text(encoding="utf-8"))
        assert any("autoassinado" in x for x in m["future_interventions"]), m["future_interventions"]
        return f"{names}"

    # ---------------------------------------------------------------- 2.6 relatório e manifesto
    @check("2.6", "PDF e manifesto com as alterações reais lidas do Windows; sem senhas, tokens ou chaves")
    def _():
        pdf, man = reports_of(state["install_run"])
        body = man.read_text(encoding="utf-8")
        m = json.loads(body)
        assert m["schema"] == "vyonix-deploy-manifest/1"
        items = {i["id"]: i for i in m["items"]}
        obs = items["service.VyonixCore"]["observed"]
        assert obs["account"].lower() == "nt service\\vyonixcore" and obs["state"] in ("Running", "Stopped"), obs
        fw = items["firewall.core-https"]["observed"]
        assert fw.get("exists") and fw.get("port") == "8444", fw
        text = pdf_text(pdf)
        assert "VyonixCore" in text and "VYONIX - Core HTTPS - 8444" in text, "PDF sem os itens reais"
        secrets = secrets_values()
        for name, content in (("manifesto", body), ("PDF", text)):
            for s in secrets:
                assert s not in content, f"segredo encontrado no {name}"
            assert "PRIVATE KEY" not in content, f"chave privada no {name}"
        import hashlib
        assert hashlib.sha256(pdf.read_bytes()).hexdigest() == m["pdf"]["sha256"]
        return f"{pdf.name} ({pdf.stat().st_size} bytes), {man.name}; {len(secrets)} segredos procurados: nenhum presente"

    # ---------------------------------------------------------------- 2.2 idempotência
    @check("2.2", "Segunda execução não muda nada (todos os passos já conformes)")
    def _():
        deploy("install", "--config", cfg_file, "--approve-all", "--silent")
        run, steps = last_run_steps()
        assert run["status"] == "succeeded", run["message"]
        changed = [s["step_id"] for s in steps if s["status"] not in ("already",)]
        assert not changed, f"passos reaplicados: {changed}"
        return f"execução {run['id']}: {len(steps)} passos, todos 'já estava conforme'"

    # dados para conferir a preservação na atualização
    @check("2.8", "Dados de referência criados pela API (paciente e configuração)")
    def _():
        api = Api(8444)
        api.login()
        p = api.call("POST", "/patients", {"name": "Paciente Persistencia CI",
                                           "identifiers": [{"issuer": "PRONT", "value": "CI-1"}]})
        api.call("PUT", "/settings/core/institution", {"value": {"display_name": "Clínica CI Persistente"}})
        state["patient"] = p["id"]
        return f"paciente {p['id']}"

    # ---------------------------------------------------------------- 2.5 reinício
    @check("2.5", "Reinício do serviço e recuperação automática após falha do processo")
    def _():
        powershell("Restart-Service VyonixCore", as_json=False, timeout=180)
        health(8444)
        pid = query_service("VyonixCore")["pid"]
        sh(["taskkill", "/F", "/PID", str(pid)], ok=None)
        time.sleep(8)
        end = time.monotonic() + 120
        while time.monotonic() < end:
            q = query_service("VyonixCore")
            if q["state"] == "Running" and q["pid"] != pid:
                break
            time.sleep(3)
        health(8444)
        return f"reiniciado; processo {pid} encerrado à força e substituído por {query_service('VyonixCore')['pid']}"

    # ---------------------------------------------------------------- 2.7 diagnosticar e reparar
    def scenario(name: str, breaker, expect: str, after=None):
        @check("2.7", f"Cenário: {name} — detectado e reparado")
        def _():
            breaker()
            d = diagnose()
            ids = problem_ids(d)
            assert any(expect in i for i in ids), f"não detectado: {ids}"
            deploy("repair", "--approve-all", "--silent")
            if after:
                after()
            d2 = diagnose()
            assert not d2["problems"], f"ainda há problemas: {[p['id'] for p in d2['problems']]}"
            run, _ = last_run_steps()
            return f"detectado ({expect}); reparo aplicado; novo diagnóstico sem problemas; relatório {run['id']}"

    scenario("serviço parado", lambda: powershell("Stop-Service VyonixWorker", as_json=False), "running.VyonixWorker")
    scenario("regra de firewall apagada",
             lambda: powershell("Remove-NetFirewallRule -Name 'VYONIX-core-https-8444'", as_json=False),
             "firewall.core-https")

    def expire_cert():
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        k = ec.generate_private_key(ec.SECP256R1())
        n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "expirado")])
        now = datetime.now(timezone.utc)
        c = (x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key())
             .serial_number(1).not_valid_before(now - timedelta(days=30)).not_valid_after(now - timedelta(days=1))
             .sign(k, hashes.SHA256()))
        tls = PATHS.data_dir / "tls"
        (tls / "server.crt").write_bytes(c.public_bytes(serialization.Encoding.PEM))
        (tls / "server.key").write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                         serialization.NoEncryption()))
    scenario("certificado vencido", expire_cert, "https.certificate", after=lambda: health(8444))
    scenario("permissão removida",
             lambda: sh(["icacls", PATHS.data_dir, "/remove:g", "NT SERVICE\\VyonixWorker"]), "acl.data")

    @check("2.7", "Cenário: porta ocupada — detectada e reparada (HTTPS movido para porta livre)")
    def _():
        powershell("Stop-Service VyonixCore", as_json=False)
        lp = listener(8444)
        try:
            d = diagnose()
            prob = next((p for p in d["problems"] if p["id"] == "port.8444"), None)
            assert prob, f"não detectado: {problem_ids(d)}"
            new = prob["config_change"]["https_port"]
            deploy("repair", "--approve-all", "--silent")
            health(new)
            ids = {r["Name"] if isinstance(r, dict) else r for r in as_list(powershell(
                "@(Get-NetFirewallRule -Name 'VYONIX-core-https-*' | ForEach-Object { $_.Name })"))}
            assert ids == {f"VYONIX-core-https-{new}"}, ids
            lan = {r["Name"] if isinstance(r, dict) else r for r in as_list(powershell(
                "@(Get-NetFirewallRule -Name 'VYONIX-core-lan-*' | ForEach-Object { $_.Name })"))}
            assert lan == {f"VYONIX-core-lan-{new}"}, lan
            d2 = diagnose()
            assert not d2["problems"], [p["id"] for p in d2["problems"]]
            state["port"] = new
            return f"porta 8444 ocupada por outro processo; HTTPS movido para {new}; regra antiga substituída"
        finally:
            lp.kill()

    # ---------------------------------------------------------------- 2.9 ativação de módulo
    @check("2.9", "Ativação do módulo PRINT: direito assinado → dependências → preparo → teste → habilitação")
    def _():
        p = sh([sys.executable, ROOT / "tools" / "ci_activation.py", "--out", OUT], timeout=900, ok=None)
        r = json.loads((OUT / "activation.json").read_text(encoding="utf-8"))
        assert r["status"] == "succeeded", r
        assert r["before_enabled"] is False and r["after_enabled"] is True, r
        assert r["refused_without_license"], "habilitou sem licença"
        return json.dumps(r, ensure_ascii=False)[:800]

    @check("2.5", "VYONIX VIEWER (OHIF) servido pelo Core instalado, com política de conteúdo própria")
    def _():
        port = state.get("port", 8444)
        api = Api(port)
        req = urllib.request.Request(api.base.replace("/api/v1", "") + "/viewer/", headers={"User-Agent": "CI"})
        with api.op.open(req, timeout=20) as r:
            body, csp = r.read().decode("utf-8", "replace"), r.headers.get("Content-Security-Policy", "")
        assert r.status == 200 and "<html" in body.lower(), r.status
        assert "'wasm-unsafe-eval'" in csp and "'sha256-" in csp and "frame-ancestors 'none'" in csp, csp
        assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0], csp
        n = csp.count("'sha256-")
        return f"/viewer/ 200; CSP com {n} hash(es) de script"

    @check("2.9", "Ativação do módulo PACS: motor DICOM (Orthanc sem plugins) como serviço, Core configurado e habilitado")
    def _():
        sh([sys.executable, ROOT / "tools" / "ci_activation.py", "--out", OUT, "--module", "pacs"], timeout=900,
           ok=None)
        r = json.loads((OUT / "activation-pacs.json").read_text(encoding="utf-8"))
        assert r["status"] == "succeeded", r
        assert r["before_enabled"] is False and r["after_enabled"] is True, r
        assert r["refused_without_license"], "habilitou sem licença"
        ok, msg = r["engine_probe"]
        assert ok, msg
        q = query_service("VyonixPacsEngine")
        assert q and q["state"] == "Running" and q["account"].lower() == "nt service\\vyonixpacsengine", q
        port = state.get("port", 8444)
        health(port)
        api = Api(port)
        api.login()
        st = api.call("GET", "/pacs/status")
        assert st["engine"]["configured"] and st["engine"]["reachable"] and st["enabled"], st
        import socket
        with socket.create_connection(("127.0.0.1", 4242), timeout=5):
            pass
        # consulta/recuperação pelo Core (C-FIND/C-MOVE): porta 4243 escutando e estação não cadastrada recusada
        deadline = time.monotonic() + 60
        while True:
            try:
                with socket.create_connection(("127.0.0.1", 4243), timeout=5):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(2)
        from pynetdicom import AE
        qae = AE(ae_title="CI_SEM_CADASTRO")
        qae.add_requested_context("1.2.840.10008.1.1")
        qa = qae.associate("127.0.0.1", 4243, ae_title="VYONIX_QR")
        assert not qa.is_established, "consulta DICOM aceitou estação não cadastrada"
        # backup diário do PACS configurado: pasta criada com permissões mínimas e visível no monitoramento
        bdir = PATHS.backups / "PACS"
        assert bdir.is_dir(), f"pasta de backup do PACS ausente: {bdir}"
        hd = api.call("GET", "/health/detail")
        assert hd["components"]["pacs_backup"]["configured"] is True, hd["components"].get("pacs_backup")
        return (f"{msg}; Core: {st['engine'].get('version')} alcançável; porta DICOM 4242 aberta; consulta DICOM 4243 "
                "escutando e recusando estação não cadastrada; backup diário do PACS configurado")

    @check("2.9", "PACS no Windows: C-STORE de modalidade simulada indexado pelo Worker; backup e verificação pelo "
                  "comando do produto")
    def _():
        import io
        from pydicom.dataset import FileDataset, FileMetaDataset
        from pydicom.uid import ExplicitVRLittleEndian, generate_uid
        from pynetdicom import AE
        study, series, sop = (generate_uid(prefix=None) for _ in range(3))
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID = "1.2.840.10008.5.1.4.1.1.2", sop
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
        ds.SOPClassUID, ds.SOPInstanceUID = meta.MediaStorageSOPClassUID, sop
        ds.StudyInstanceUID, ds.SeriesInstanceUID = study, series
        ds.PatientName, ds.PatientID, ds.Modality = "TESTE^SINTETICO CI", "CI-PACS-0001", "CT"
        ds.StudyDate, ds.InstanceNumber, ds.SeriesNumber = "20261028", 1, 1
        ds.Rows = ds.Columns = 8
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 0
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        ds.PixelData = bytes(128)
        buf = io.BytesIO()
        ds.save_as(buf, enforce_file_format=True)
        ae = AE(ae_title="CI_MODALIDADE")
        ae.add_requested_context(meta.MediaStorageSOPClassUID, ExplicitVRLittleEndian)
        a = ae.associate("127.0.0.1", 4242, ae_title="VYONIX_PACS")
        assert a.is_established, "motor DICOM recusou a associação de C-STORE"
        try:
            st = a.send_c_store(ds)
            assert st and st.Status == 0, f"C-STORE: {st}"
        finally:
            a.release()
        port = state.get("port", 8444)
        api = Api(port)
        api.login()
        deadline = time.monotonic() + 180                  # sincronização do Worker a cada 15 s
        found = []
        while time.monotonic() < deadline and not found:
            found = api.call("GET", f"/pacs/dicomweb/studies?StudyInstanceUID={study}") or []
            if not found:
                time.sleep(5)
        assert found, "estudo enviado por C-STORE não foi indexado pelo VyonixWorker em 180 s"
        dest = OUT / "pacs-backup"
        p = sh([PATHS.core_exe, "--data", PATHS.data_dir, "pacs-backup", "--dest", dest], timeout=600)
        out = json.loads(p.stdout[p.stdout.index("{"):])
        assert out["instances"] >= 1 and not out["integrity_failures"], out
        # o motor regrava o File Meta ao receber por C-STORE: compara o conteúdo do objeto, não os bytes do arquivo
        from pydicom import dcmread
        got = dcmread(dest / study / series / f"{sop}.dcm")
        assert (got.SOPInstanceUID, got.StudyInstanceUID, got.PatientID, bytes(got.PixelData)) == \
            (sop, study, "CI-PACS-0001", bytes(128)), "objeto do backup difere do enviado"
        pv = sh([PATHS.core_exe, "pacs-verify", "--src", dest], timeout=300).stdout
        v = json.loads(pv[pv.index("{"):])
        assert v["valid"], v
        return (f"C-STORE → motor → indexado; backup {out['instances']} instância(s), {out['copied']} copiada(s), "
                "objeto idêntico ao enviado (UIDs, paciente, pixels); verificação do manifesto válida")

    # ---------------------------------------------------------------- 2.8 atualização
    @check("2.8", "Atualização: backup antes da migração; dados e configurações preservados")
    def _():
        sh([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DEPLOYUPDATE=1",
            f"/LOG={OUT / 'setup-update.log'}"], timeout=1800)
        run, steps = last_run_steps()
        assert run["kind"] == "update" and run["status"] == "succeeded", f"{run['kind']} {run['status']}: {run['message']}"
        b = next(s for s in steps if s["step_id"] == "backup.before_update")
        assert b["status"] == "done", b
        port = state.get("port", 8444)
        health(port)
        api = Api(port)
        api.login()
        pt = api.call("GET", f"/patients/{state['patient']}")
        inst = api.call("GET", "/settings/core/institution")
        assert pt["name"] == "Paciente Persistencia CI" and inst["value"]["display_name"] == "Clínica CI Persistente"
        backups = sorted(PATHS.backups.glob("antes-da-atualizacao-*"))
        return f"execução {run['id']}; backup {backups[-1].name}; paciente e configuração preservados"

    if a.print_setup and Path(a.print_setup).exists():
        @check("2.8", "DICOM Print continua funcionando após instalar e atualizar a plataforma (C-ECHO)")
        def _():
            q = query_service("VyonixDicomPrint")
            assert q and q["state"] == "Running", q
            echo = print_service_check(print_dir)
            iid = installation_id()
            assert iid == state["iid_before"], f"Installation ID mudou: {state['iid_before']} → {iid}"
            return f"{echo}; Installation ID preservado ({iid})"
        record("2.8", "Impressão de teste no DICOM Print", "Não executado",
               "Exige equipamento autorizado e impressora configurados no DICOM Print; coberto pelos testes do "
               "próprio DICOM Print (test_print_scp) no pipeline Windows release.")

    # ---------------------------------------------------------------- 2.7 reparo destrutivo
    @check("2.7", "Restaurar backup exige segunda confirmação específica e restaura os dados do backup")
    def _():
        port = state.get("port", 8444)
        api = Api(port)
        api.login()
        p2 = api.call("POST", "/patients", {"name": "Paciente Depois Do Backup"})
        b = sorted(PATHS.backups.glob("antes-da-atualizacao-*"))[-1].name
        r = deploy("restore", "--backup", b, "--approve-all", "--silent", ok=(2,))
        assert "RESTAURAR" in r.stdout, r.stdout[-300:]
        deploy("restore", "--backup", b, "--approve-all", "--silent", "--confirm", f"backup.restore=RESTAURAR {b}")
        run, steps = last_run_steps()
        assert run["kind"] == "restore" and run["status"] == "succeeded", run["message"]
        assert any(s["step_id"] == "backup.antes-da-restauracao" and s["status"] == "done" for s in steps)
        health(port)
        api = Api(port)
        api.login()
        names = {x["name"] for x in api.call("GET", "/patients?q=Paciente")}
        assert "Paciente Persistencia CI" in names and "Paciente Depois Do Backup" not in names, names
        return f"sem confirmação: recusado; com “RESTAURAR {b}”: restaurado (backup do estado atual feito antes)"

    # ---------------------------------------------------------------- 2.4 rede (adaptador de loopback)
    @check("2.4", "Rede em adaptador de loopback: conflito recusado, IP fixo aplicado e revertido, reversão automática")
    def _():
        p = sh([sys.executable, ROOT / "tools" / "ci_network.py", "--out", OUT], timeout=1200, ok=None)
        r = json.loads((OUT / "network.json").read_text(encoding="utf-8"))
        if r.get("not_run"):
            raise NotRun(r["not_run"])
        assert r["ok"], r
        return json.dumps(r, ensure_ascii=False)[:900]

    # ---------------------------------------------------------------- reports / cadeia
    @check("2.6", "Histórico sem sobrescrita e cadeia de manifestos íntegra; alteração manual detectada")
    def _():
        p = deploy("verify-reports")
        import sqlite3
        c = sqlite3.connect(str(PATHS.db_file))
        n = c.execute("SELECT count(*) FROM reports WHERE kind='manifest'").fetchone()[0]
        man = Path(c.execute("SELECT path FROM reports WHERE kind='manifest' ORDER BY id LIMIT 1").fetchone()[0])
        c.close()
        man.write_text(man.read_text(encoding="utf-8").replace('"clinica-ci"', '"clinica-xx"'), encoding="utf-8")
        p2 = deploy("verify-reports", ok=(1,))
        assert "alterado" in p2.stdout, p2.stdout
        return f"{n} manifestos encadeados; alteração manual no primeiro detectada: {p2.stdout.strip()[:200]}"

    # ---------------------------------------------------------------- desinstalação em condições reais (2.12)
    def app_processes() -> list[str]:
        return as_list(powershell(
            "$d = [IO.Path]::GetFullPath($A.d).TrimEnd([char]92) + [char]92; @(Get-CimInstance Win32_Process | "
            "Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($d, [StringComparison]::OrdinalIgnoreCase) } "
            "| ForEach-Object { $_.Name + ' ' + $_.ProcessId })", {"d": str(INSTALL)}))

    def wait_uninstall_finished(started: float, timeout: float = 900) -> dict:
        """Estado FINAL real: espera o desinstalador (e a cópia temporária _iu*.tmp) terminar e o status gravado."""
        st = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "VYONIX" / "Logs" / "desinstalacao.json"
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            busy = as_list(powershell("@(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '_iu*' "
                                      "-or $_.Name -like 'unins*' } | ForEach-Object { $_.Name })"))
            if not busy and st.exists() and st.stat().st_mtime >= started - 2:
                return json.loads(st.read_text(encoding="utf-8-sig"))
            time.sleep(3)
        raise AssertionError(f"desinstalação não terminou em {timeout} s (status: "
                             f"{st.read_text(encoding='utf-8-sig') if st.exists() else 'ausente'})")

    @check("2.12", "Desinstalação com o assistente aberto e uma execução interrompida: nada fica preso")
    def _():
        import sqlite3
        wiz = subprocess.Popen([str(INSTALL / "vyonix-deploy.exe"), "wizard", "--no-browser"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)          # prende arquivos do programa
        time.sleep(8)
        assert wiz.poll() is None, "o assistente não ficou aberto"
        c = sqlite3.connect(str(PATHS.db_file))                  # execução que "caiu no meio" (processo encerrado)
        rid = c.execute("SELECT id FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        c.execute("UPDATE runs SET status='running' WHERE id=?", (rid,))
        c.commit()
        c.close()
        state["stale_run"] = rid
        before = app_processes()
        un = INSTALL / "unins000.exe"
        t0 = time.time()
        sh([un, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={OUT / 'uninstall.log'}"], timeout=900)
        fin = wait_uninstall_finished(t0)
        assert fin["status"] == "concluida", f"desinstalação: {fin}"
        for n in ("VyonixPacsEngine", "VyonixCore", "VyonixWorker", "VyonixPostgreSQL"):
            assert query_service(n) is None, f"{n} ainda registrado"
        left = app_processes()
        assert not left, f"processos da pasta do programa ainda em execução: {left}"
        assert wiz.poll() is not None, "o assistente continuou aberto"
        files = [str(x) for x in INSTALL.rglob("*") if x.is_file()] if INSTALL.exists() else []
        assert not files, f"arquivos do programa não removidos: {files[:5]}"
        c = sqlite3.connect(str(PATHS.db_file))
        st = c.execute("SELECT status FROM runs WHERE id=?", (state["stale_run"],)).fetchone()[0]
        c.close()
        assert st == "abandoned", f"execução interrompida ficou {st}"
        log = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "VYONIX" / "Logs" / "instalador.log"
        raw = log.read_bytes()
        try:
            txt = raw.decode("utf-8")
        except UnicodeDecodeError:
            txt = raw.decode("cp1252", errors="replace")     # o Inno grava o registro em ANSI
        assert "desinstalação concluída" in txt, txt[-800:]
        shutil.copy2(log, OUT / "instalador.log")
        return (f"código 0; estado final verificado após o término ({fin}); "
                f"antes: {len(before)} processo(s) na pasta do programa (assistente e serviços); depois: nenhum; "
                "4 serviços removidos; pasta do programa vazia; execução interrompida registrada como abandonada; "
                "registro em ProgramData\\VYONIX\\Logs\\instalador.log")

    @check("2.8", "Desinstalação: serviços, regra e atalhos removidos; dados e DICOM Print preservados")
    def _():
        for n in ("VyonixCore", "VyonixWorker", "VyonixPostgreSQL"):
            assert query_service(n) is None, f"{n} ainda registrado"
        left = as_list(powershell("@(Get-NetFirewallRule -Name 'VYONIX-core-*' -ErrorAction SilentlyContinue | "
                                  "ForEach-Object { $_.Name })"))
        assert not left, left
        assert (PATHS.pg_data / "PG_VERSION").exists() and (PATHS.data_dir / "config.json").exists(), "dados removidos"
        ext = powershell("Get-NetFirewallRule -Name 'CI-Externa-1' | ForEach-Object { [string]$_.Enabled }")
        assert ext == "True"
        extra = ""
        if query_service("VyonixDicomPrint"):
            assert query_service("VyonixDicomPrint")["state"] == "Running"
            extra = "; DICOM Print em execução"
        return "serviços e regra removidos; cluster PostgreSQL, configuração e relatórios preservados" + extra

    def reinstall(name: str) -> str:
        sh([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DEPLOYUPDATE=1", f"/LOG={OUT / name}"],
           timeout=1800)
        run, _steps = last_run_steps()
        assert run["kind"] == "update" and run["status"] == "succeeded", f"{run['kind']} {run['status']}: {run['message']}"
        port = state.get("port", 8444)
        health(port)
        api = Api(port)
        api.login()
        names = {x["name"] for x in api.call("GET", "/patients?q=Paciente")}
        assert "Paciente Persistencia CI" in names, names
        for n in ("VyonixCore", "VyonixWorker", "VyonixPostgreSQL"):
            q = query_service(n)
            assert q and q["state"] == "Running" and q["start"] == "Auto", f"{n}: {q}"
            assert (q.get("recovery") or {}).get("actions"), f"{n} sem recuperação automática"
        return f"atualização {run['id']} concluída; serviços automáticos com recuperação; dados preservados"

    @check("2.12", "Reinstalar depois de desinstalar: reconhece os dados e atualiza (sem perda)")
    def _():
        return reinstall("setup-reinstall.log")

    @check("2.12", "Atualizar por cima da versão instalada (sem desinstalar), com o assistente aberto")
    def _():
        wiz = subprocess.Popen([str(INSTALL / "vyonix-deploy.exe"), "wizard", "--no-browser"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(8)
        out = reinstall("setup-upgrade.log")
        assert wiz.poll() is not None, "o assistente antigo continuou aberto prendendo arquivos"
        return out

    @check("2.12", "Reparar instalação: serviço removido por fora é detectado e recriado")
    def _():
        sh(["sc.exe", "stop", "VyonixWorker"], ok=None)
        time.sleep(5)
        sh(["sc.exe", "delete", "VyonixWorker"], ok=None)
        time.sleep(3)
        assert query_service("VyonixWorker") is None
        deploy("repair", "--approve-all", "--silent")
        q = query_service("VyonixWorker")
        assert q and q["state"] == "Running", q
        health(state.get("port", 8444))
        return "serviço do Worker apagado por fora; reparo recriou e iniciou; sistema respondendo"

    @check("2.12", "Ferramenta de recuperação: diagnóstico sem alterar; aplicar libera a reinstalação; dados intactos")
    def _():
        ps = ROOT / "installer" / "recuperacao" / "Recuperar_VYONIX.ps1"
        sh(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps, "-Saida", OUT, "-SemAbrir"],
           timeout=600)
        assert query_service("VyonixCore") is not None, "o diagnóstico alterou o sistema"
        html = sorted(OUT.glob("VYONIX_Recuperacao_*.html"))[-1].read_text(encoding="utf-8-sig")
        assert "somente diagnostico" in html and "Servico VyonixCore" in html, html[:400]
        sh(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps, "-Aplicar", "-SemConfirmar",
            "-Saida", OUT, "-SemAbrir"], timeout=900)
        for n in ("VyonixPacsEngine", "VyonixCore", "VyonixWorker", "VyonixPostgreSQL"):
            assert query_service(n) is None, f"{n} ainda registrado depois da recuperação"
        assert not INSTALL.exists(), "pasta do programa não foi renomeada"
        old = list(INSTALL.parent.glob("Platform.anterior-*"))
        assert old, "pasta renomeada não encontrada"
        assert (PATHS.pg_data / "PG_VERSION").exists() and (PATHS.data_dir / "config.json").exists(), "dados alterados"
        rec = sorted(PATHS.backups.glob("recuperacao-*"))[-1]
        bj = json.loads((rec / "backup.json").read_text(encoding="utf-8-sig"))
        assert bj.get("restauracao_testada") is True and bj.get("conteudo_conferido") is True and bj["tabelas"] > 0, bj
        assert (rec / "estado-anterior" / "servicos.json").exists(), "estado anterior não registrado"
        assert "R0" in html and "O que a recuperacao faria" in html, "relatório sem backups ou sem o plano"
        if query_service("VyonixDicomPrint"):
            assert query_service("VyonixDicomPrint")["state"] == "Running", "DICOM Print afetado"
        out = reinstall("setup-after-recovery.log")
        return f"diagnóstico só leitura; aplicar: serviços removidos, pasta renomeada ({old[0].name}); {out}"

    # ---------------------------------------------------------------- 2.13 recuperação: falhas, reexecução e reversão
    REC = ROOT / "installer" / "recuperacao"

    def rec_tool(*extra, ok=(0,)):
        return sh(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", REC / "Recuperar_VYONIX.ps1",
                   "-Saida", OUT, "-SemAbrir", *extra], timeout=1800, ok=ok)

    def system_snapshot() -> dict:
        """O que o diagnóstico não pode mudar: serviços, registro, pasta do programa, backups, regras de firewall."""
        return powershell(
            "$app = $A.app; $o = [ordered]@{}; "
            "$o.servicos = @(Get-CimInstance Win32_Service | Where-Object { $_.Name -like 'Vyonix*' } | Sort-Object Name | "
            "ForEach-Object { $_.Name + '|' + $_.State + '|' + $_.StartMode + '|' + $_.PathName + '|' + $_.StartName }); "
            "$k = 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{EE8E242D-1625-4E1B-8317-5BFD8610DD26}_is1'; "
            "$o.registro = if (Test-Path $k) { (Get-ItemProperty $k | Select-Object DisplayVersion, UninstallString, InstallLocation | ConvertTo-Json -Compress) } else { '' }; "
            "$o.programa = @(if (Test-Path $app) { Get-ChildItem $app -Recurse -File | Sort-Object FullName | ForEach-Object { $_.FullName + '|' + $_.Length + '|' + $_.LastWriteTimeUtc.Ticks } }); "
            "$o.backups = @(Get-ChildItem $A.bk -Directory -ErrorAction SilentlyContinue | Sort-Object Name | ForEach-Object { $_.Name }); "
            "$o.firewall = @(Get-NetFirewallRule -Name 'VYONIX-*' -ErrorAction SilentlyContinue | Sort-Object Name | ForEach-Object { $_.Name + '|' + $_.Enabled }); "
            "$o", {"app": str(INSTALL), "bk": str(PATHS.backups)})

    def patients() -> set:
        api = Api(state.get("port", 8444))
        api.login()
        return {x["name"] for x in api.call("GET", "/patients?q=Paciente")}

    @check("2.13", "Diagnóstico da recuperação é só leitura (serviços, registro, arquivos, backups e firewall iguais) "
                   "e identifica o que pertence ao VYONIX")
    def _():
        a = system_snapshot()
        rec_tool()
        b = system_snapshot()
        diff = [k for k in a if a[k] != b[k]]
        assert not diff, f"o diagnóstico alterou: {diff}"
        html = sorted(OUT.glob("VYONIX_Recuperacao_*.html"))[-1].read_text(encoding="utf-8-sig")
        for t in ("pertence ao VYONIX Platform", "O que a recuperacao faria (nada foi feito)", "Banco de dados do VYONIX",
                  "VyonixDicomPrint"):
            assert t in html, f"relatório sem “{t}”"
        return (f"antes = depois em {len(a['servicos'])} serviço(s), {len(a['programa'])} arquivo(s) do programa, "
                f"{len(a['backups'])} pasta(s) de backup, registro e firewall; plano e inventário no relatório")

    @check("2.13", "Recuperação interrompida antes da confirmação: nada alterado")
    def _():
        a = system_snapshot()
        p = rec_tool("-Aplicar", "-Confirmacao", "nao", ok=(3,))
        b = system_snapshot()
        assert a == b, [k for k in a if a[k] != b[k]]
        assert "O QUE A RECUPERACAO VAI FAZER" in p.stdout and "Cancelado" in p.stdout, p.stdout[-500:]
        return "plano mostrado; resposta diferente de RECUPERAR → código 3, nenhum serviço, arquivo, registro ou backup alterado"

    @check("2.13", "Falha na remoção de serviço (aberto por outro programa), serviço alheio com o mesmo nome e falha "
                   "ao renomear a pasta (arquivo preso por outro programa): nada apagado, backup testado, aviso claro")
    def _():
        holder_svc = subprocess.Popen([sys.executable, "-c", (
            "import ctypes,sys,time\n"
            "a=ctypes.windll.advapi32\n"
            "a.OpenSCManagerW.restype=ctypes.c_void_p; a.OpenServiceW.restype=ctypes.c_void_p\n"
            "a.OpenServiceW.argtypes=[ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]\n"
            "m=a.OpenSCManagerW(None,None,1); h=a.OpenServiceW(m,'VyonixWorker',4)\n"
            "print(h, flush=True); time.sleep(3600)")], stdout=subprocess.PIPE, text=True)
        assert holder_svc.stdout.readline().strip() not in ("", "None", "0"), "sem handle do serviço"
        holder_file = subprocess.Popen([sys.executable, "-c",
                                        f"f=open(r'{INSTALL / 'vyonix-deploy.exe'}','rb'); print('ok', flush=True); "
                                        "import time; time.sleep(3600)"], stdout=subprocess.PIPE, text=True)
        assert holder_file.stdout.readline().strip() == "ok"
        pacs = query_service("VyonixPacsEngine")
        if pacs:                               # o motor PACS volta pela reversão (reparo) / próxima atualização
            sh(["sc.exe", "stop", "VyonixPacsEngine"], ok=None)
            time.sleep(5)
            sh(["sc.exe", "config", "VyonixPacsEngine", "binPath=", r"C:\Windows\System32\svchost.exe -k ci-alheio"])
        else:
            sh(["sc.exe", "create", "VyonixPacsEngine", "binPath=", r"C:\Windows\System32\svchost.exe -k ci-alheio",
                "start=", "demand"])
        try:
            p = rec_tool("-Aplicar", "-SemConfirmar", ok=(5,))
            assert "NAO PERTENCE" in p.stdout, "serviço alheio não identificado"
            assert query_service("VyonixPacsEngine") is not None, "serviço alheio removido"
            assert holder_file.poll() is None and holder_svc.poll() is None, "processo de outro programa encerrado"
            assert INSTALL.exists() and (INSTALL / "vyonix-deploy.exe").exists(), "pasta do programa alterada"
            w = powershell("(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\VyonixWorker' -Name DeleteFlag "
                           "-ErrorAction SilentlyContinue).DeleteFlag")
            assert str(w) == "1", f"Worker deveria estar marcado para exclusão: {w}"
            rec = sorted(PATHS.backups.glob("recuperacao-*"))[-1]
            bj = json.loads((rec / "backup.json").read_text(encoding="utf-8-sig"))
            assert bj.get("restauracao_testada") is True and bj.get("conteudo_conferido") is True, bj
            meta = json.loads((rec / "recuperacao.json").read_text(encoding="utf-8-sig"))
            assert meta["concluida"] is False and not meta["pasta_renomeada"], meta
            assert (PATHS.pg_data / "PG_VERSION").exists() and (PATHS.data_dir / "config.json").exists()
            out = p.stdout
            assert "PARCIAL" in out and "NAO renomeada" in out and "marcado para exclusao" in out, out[-900:]
        finally:
            holder_svc.kill()
            holder_file.kill()
            time.sleep(3)
        state["rec_parcial"] = rec.name
        return (f"código 5 (parcial): Worker marcado para exclusão (o Windows remove ao soltar/reiniciar), serviço "
                f"alheio “VyonixPacsEngine” não tocado, processos alheios não encerrados, pasta não renomeada e não "
                f"apagada; backup novo restaurado em banco temporário e idêntico ao original ({bj['tabelas']} tabelas, "
                f"{bj['linhas']} linhas: contagem + MD5 do conteúdo, sequências, estrutura; {bj.get('indices')}); "
                f"dados intactos")

    @check("2.13", "Reexecução segura: depois de soltar os bloqueios, a recuperação conclui (cópia a frio conferida)")
    def _():
        sh(["sc.exe", "delete", "VyonixPacsEngine"], ok=None)          # o "serviço alheio" do teste anterior
        time.sleep(5)
        assert query_service("VyonixWorker") is None, "Worker deveria ter saído ao soltar o handle"
        rec_tool("-Aplicar", "-SemConfirmar")
        for n in ("VyonixPacsEngine", "VyonixCore", "VyonixWorker", "VyonixPostgreSQL"):
            assert query_service(n) is None, f"{n} ainda registrado"
        assert not INSTALL.exists(), "pasta do programa não foi renomeada"
        rec = sorted(PATHS.backups.glob("recuperacao-*"))[-1]
        meta = json.loads((rec / "recuperacao.json").read_text(encoding="utf-8-sig"))
        assert meta["concluida"] is True and meta["pasta_renomeada"], meta
        assert meta.get("dados_inalterados") is True, f"arquivos DICOM/configurações mudaram: {meta.get('dados')}"
        assert (rec / "copia-fria.json").exists() or (rec / "backup.json").exists(), "sem backup confirmado"
        assert (PATHS.pg_data / "PG_VERSION").exists() and (PATHS.data_dir / "config.json").exists()
        if query_service("VyonixDicomPrint"):
            assert query_service("VyonixDicomPrint")["state"] == "Running", "DICOM Print afetado"
        tipo = "cópia a frio conferida por SHA-256" if (rec / "copia-fria.json").exists() else "backup lógico testado"
        tipo += f"; arquivos DICOM e configurações inalterados ({meta['dados']})"
        state["rec_final"] = rec
        return f"2ª execução concluída ({tipo}); serviços removidos; pasta renomeada para {Path(meta['pasta_renomeada']).name}"

    @check("2.13", "Reversão da recuperação: pasta, registro e serviços restaurados; sistema e dados de volta")
    def _():
        sh(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", REC / "Reverter_VYONIX.ps1",
            "-Pasta", state["rec_final"], "-SemConfirmar", "-Saida", OUT, "-SemAbrir"], timeout=1800)
        assert (INSTALL / "vyonix-deploy.exe").exists(), "pasta do programa não restaurada"
        for n in ("VyonixCore", "VyonixWorker", "VyonixPostgreSQL"):
            q = query_service(n)
            assert q and q["state"] == "Running", f"{n}: {q}"
        health(state.get("port", 8444), 300)
        assert "Paciente Persistencia CI" in patients()
        return "Reverter_VYONIX: pasta de volta, serviços recriados pelo reparo oficial, sistema respondendo, paciente preservado"

    @check("2.13", "Falha durante a migração do banco (simulada): para com segurança, registra o erro, backup antes; "
                   "restauração do backup e nova atualização funcionam")
    def _():
        port = state.get("port", 8444)
        deploy("update", "--approve-all", "--silent", ok=(1,), env={"VYONIX_DEPLOY_FALHA_SIMULADA": "migracao"})
        run, steps = last_run_steps()
        assert run["kind"] == "update" and run["status"] in ("rolled_back", "failed"), run
        bad = [s for s in steps if s["status"] == "failed"]
        assert bad and bad[0]["step_id"] == "core.database" and "simulada" in (bad[0]["error"] or ""), bad
        bk = [s for s in steps if s["step_id"] == "backup.before_update"]
        assert bk and bk[0]["status"] == "done", bk
        b = sorted(PATHS.backups.glob(f"antes-da-atualizacao-{run['id']}"))
        assert b and (b[0] / "backup.json").exists(), "backup antes da migração ausente"
        health(port, 300)
        assert "Paciente Persistencia CI" in patients(), "dados perdidos após a falha"
        deploy("restore", "--backup", b[0].name, "--approve-all", "--silent", "--confirm",
               f"backup.restore=RESTAURAR {b[0].name}")
        r2, _s = last_run_steps()
        assert r2["kind"] == "restore" and r2["status"] == "succeeded", r2["message"]
        health(port, 300)
        assert "Paciente Persistencia CI" in patients()
        deploy("update", "--approve-all", "--silent")
        r3, _s = last_run_steps()
        assert r3["status"] == "succeeded", r3["message"]
        return (f"execução {run['id']}: {run['status']} em “core.database” (erro registrado), backup "
                f"{b[0].name} feito antes; sistema seguiu respondendo; restauração e nova atualização concluídas")

    @check("2.13", "Falha na inicialização após atualização (simulada): erro registrado, nada perdido; nova "
                   "atualização conclui e o sistema responde")
    def _():
        port = state.get("port", 8444)
        deploy("update", "--approve-all", "--silent", ok=(1,), env={"VYONIX_DEPLOY_FALHA_SIMULADA": "inicializacao"})
        run, steps = last_run_steps()
        assert run["status"] in ("rolled_back", "failed"), run
        bad = [s for s in steps if s["status"] == "failed"]
        assert bad and bad[0]["step_id"] == "running.VyonixCore" and "simulada" in (bad[0]["error"] or ""), bad
        deploy("update", "--approve-all", "--silent")
        r2, _s = last_run_steps()
        assert r2["status"] == "succeeded", r2["message"]
        health(port, 300)
        assert "Paciente Persistencia CI" in patients()
        p = deploy("verificar", "--porta", str(port), "--esperar", "120")     # 2.7 pode ter movido a porta
        return f"execução {run['id']}: {run['status']} (erro registrado no DEPLOY); nova atualização ok; verificar: código {p.returncode}"

    # ---------------------------------------------------------------- 2.1 (ao final, para não afetar os demais)
    @check("2.1", "Impeditivo detectado: espaço em disco insuficiente (cenário montado com arquivo de preenchimento)")
    def _():
        free = shutil.disk_usage("C:\\").free
        folder = Path("C:\\vyx-ci-filler")
        folder.mkdir(exist_ok=True)
        powershell("Add-MpPreference -ExclusionPath $A.p", {"p": str(folder)}, as_json=False, check=False)
        filler = folder / "filler.bin"
        size = free - 6 * 1024 ** 3
        if size <= 0:
            raise NotRun("disco já com menos de 6 GB livres")
        sh(["fsutil", "file", "createnew", filler, str(size)], timeout=600)
        try:
            p = sh([dist / "vyonix-deploy.exe", "install", "--config", cfg_file, "--plan-only"], ok=(2,))
        finally:
            for _ in range(300):
                try:
                    filler.unlink(missing_ok=True)
                    break
                except OSError:
                    time.sleep(2)
            end = time.monotonic() + 300
            while shutil.disk_usage("C:\\").free < free - 2 * 1024 ** 3 and time.monotonic() < end:
                time.sleep(2)
        after = shutil.disk_usage("C:\\").free
        assert not filler.exists() and after >= free - 2 * 1024 ** 3, f"espaço não liberado: {after / 1024 ** 3:.1f} GB"
        assert "Espaço livre" in p.stdout, p.stdout[-400:]
        return (f"impeditivo de espaço livre apontado com {6} GB livres; arquivo removido "
                f"({after / 1024 ** 3:.1f} GB livres de novo)")

    # ---------------------------------------------------------------- resultado
    for p in sorted(PATHS.reports.glob("*")) if PATHS.reports.exists() else []:
        dst = OUT / "relatorios"
        dst.mkdir(exist_ok=True)
        shutil.copy2(p, dst / p.name)
    (OUT / "acceptance.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["| Critério | Teste | Resultado | Detalhe |", "| --- | --- | --- | --- |"]
    md += [f"| {r['criterio']} | {r['teste']} | {r['resultado']} | {r['detalhe'][:220].replace('|', '/').replace(chr(10), ' ')} |"
           for r in RESULTS]
    (OUT / "acceptance.md").write_text("\n".join(md), encoding="utf-8")
    counts = {k: sum(1 for r in RESULTS if r["resultado"] == k) for k in ("Aprovado", "Reprovado", "Não executado")}
    print(f"::notice title=Aceitação DEPLOY::aprovados={counts['Aprovado']} reprovados={counts['Reprovado']} "
          f"nao_executados={counts['Não executado']}")
    chunk, chunks = "", []
    for r in RESULTS:
        if r["resultado"] == "Aprovado":
            line = f"[{r['criterio']}] {r['teste']}: {r['detalhe'][:260]}\n"
            if len(chunk) + len(line) > 3800:
                chunks.append(chunk)
                chunk = ""
            chunk += line
    if chunk:
        chunks.append(chunk)
    for i, c in enumerate(chunks[:8], 1):
        print(f"::notice title=Aprovados ({i}/{len(chunks)})::{_ann(c)}", flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Aceitação da Fase 2 (VYONIX DEPLOY)\n\n" + "\n".join(md) + "\n")
    return 1 if counts["Reprovado"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        print(f"::error title=Aceitação interrompida::{_ann(traceback.format_exc()[-3500:])}", flush=True)
        sys.exit(1)
