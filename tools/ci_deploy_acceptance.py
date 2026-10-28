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
        assert len(names) == 4, names
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

    # ---------------------------------------------------------------- desinstalação
    @check("2.8", "Desinstalação: serviços, regra e atalhos removidos; dados e DICOM Print preservados")
    def _():
        un = INSTALL / "unins000.exe"
        sh([un, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=900)
        time.sleep(5)
        for n in ("VyonixCore", "VyonixWorker", "VyonixPostgreSQL"):
            assert query_service(n) is None, f"{n} ainda registrado"
        left = as_list(powershell("@(Get-NetFirewallRule -Name 'VYONIX-core-https-*' -ErrorAction SilentlyContinue | "
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
