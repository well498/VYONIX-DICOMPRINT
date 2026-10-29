"""Diagnóstico de inicialização do VYONIX — **somente leitura** e **sem privilégio administrativo**.

Responde "por que o VYONIX não abre?" em linguagem simples, componente por componente: instalação concluída
(assistente aprovado), serviços (banco, Core, Worker, motor DICOM), banco aceitando conexões, porta HTTPS (livre ou
ocupada por outro programa), API e interface web respondendo por HTTPS em ``localhost`` e em cada IP da rede local,
regras de firewall e o perfil da rede (Público bloqueia outros computadores) e o tempo desde a inicialização do
Windows (o VYONIX começa alguns minutos depois, com início automático atrasado).

Usado pelo atalho **VYONIX** (``vyonix-deploy abrir``): se tudo responde, abre o sistema no navegador; senão gera e
abre um relatório HTML com o que falhou e como resolver. Não lê segredos nem dados de pacientes.
"""

from __future__ import annotations

import html
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

SERVICES = (("VyonixPostgreSQL", "Banco de dados (PostgreSQL)"), ("VyonixCore", "VYONIX Core (sistema web)"),
            ("VyonixWorker", "VYONIX Worker (processamento em segundo plano)"))
OPTIONAL = (("VyonixPacsEngine", "Motor DICOM do PACS"),)
BOOT_GRACE_S = 300


@dataclass
class Probes:
    """Acesso ao sistema (substituível nos testes)."""
    service: Callable[[str], dict | None]
    tcp: Callable[[str, int], bool]
    https: Callable[[str, int, str], tuple[int, bytes] | None]
    lan_ips: Callable[[], list[str]]
    profiles: Callable[[], list[dict]]
    rules: Callable[[], list[dict]]
    port_owner: Callable[[int], dict | None]
    uptime_s: Callable[[], float | None]


@dataclass
class Check:
    id: str
    title: str
    status: str                 # ok | warn | fail | info
    detail: str
    fix: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Result:
    port: int
    checks: list[Check] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    checked_at: str = ""

    @property
    def status(self) -> str:
        st = {c.status for c in self.checks}
        return "fail" if "fail" in st else "warn" if "warn" in st else "ok"

    @property
    def web_ok(self) -> bool:
        return any(c.id == "web.localhost" and c.status == "ok" for c in self.checks)

    def as_dict(self) -> dict:
        return {"port": self.port, "status": self.status, "web_ok": self.web_ok, "urls": self.urls,
                "checked_at": self.checked_at, "checks": [c.as_dict() for c in self.checks]}


def run_checks(port: int = 8444, *, pg_port: int = 5544, probes: Probes | None = None) -> Result:
    pr = probes or default_probes()
    r = Result(port=port, checked_at=datetime.now().isoformat(timespec="seconds"))
    add = r.checks.append
    svc = {name: pr.service(name) for name, _ in SERVICES + OPTIONAL}
    if not any(svc[n] for n, _ in SERVICES):
        add(Check("install", "Instalação configurada", "fail",
                  "Os serviços do VYONIX não estão registrados: a configuração não foi concluída (o assistente do "
                  "VYONIX DEPLOY não foi aberto ou o plano não foi aprovado).",
                  "Menu Iniciar → VYONIX → “VYONIX - Assistente de instalacao” (ou reinstale e deixe marcado “Abrir o "
                  "assistente”). Aprove o plano até o fim."))
        _web(r, pr, port)
        return r
    add(Check("install", "Instalação configurada", "ok", "Serviços do VYONIX registrados no Windows."))
    up = pr.uptime_s()
    for name, label in SERVICES + OPTIONAL:
        q = svc[name]
        if q is None:
            if (name, label) in OPTIONAL:
                continue
            add(Check(f"service.{name}", label, "fail", "Serviço não registrado.",
                      "Execute o reparo: Menu Iniciar → VYONIX → “VYONIX Diagnóstico” → Reparar."))
            continue
        state = q.get("state")
        if state == "Running":
            add(Check(f"service.{name}", label, "ok", "Em execução."))
        elif up is not None and up < BOOT_GRACE_S and q.get("delayed"):
            add(Check(f"service.{name}", label, "warn",
                      f"Ainda não iniciou: o Windows ligou há {int(up // 60)} min e o VYONIX inicia alguns minutos "
                      "depois (início automático atrasado).", "Aguarde até 5 minutos e abra de novo."))
        else:
            add(Check(f"service.{name}", label, "fail", f"Serviço {_state(state)}.",
                      f"Serviços do Windows → “{name}” → Iniciar. Se parar de novo, use “VYONIX Diagnóstico” → Reparar "
                      "e envie o relatório gerado."))
    if pr.tcp("127.0.0.1", pg_port):
        add(Check("database", "Banco de dados aceitando conexões", "ok", f"127.0.0.1:{pg_port} respondendo."))
    else:
        add(Check("database", "Banco de dados aceitando conexões", "fail",
                  f"Nada respondendo em 127.0.0.1:{pg_port}. Sem o banco o sistema web não funciona.",
                  "Inicie o serviço VyonixPostgreSQL; se não iniciar, use “VYONIX Diagnóstico” → Reparar."))
    owner = pr.port_owner(port)
    if owner and (owner.get("process") or "").lower() not in ("vyonixplatform", "vyonixplatform.exe", "system"):
        add(Check("port", f"Porta {port}", "fail",
                  f"A porta {port} está ocupada por outro programa ({owner.get('process')}, PID {owner.get('pid')}).",
                  "Feche o outro programa ou use “VYONIX Diagnóstico” → Reparar, que move o VYONIX para uma porta livre."))
    elif owner is None and (svc.get("VyonixCore") or {}).get("state") == "Running":
        add(Check("port", f"Porta {port}", "fail",
                  f"O serviço VyonixCore está em execução, mas ninguém atende a porta {port}.",
                  "A porta configurada pode ser outra: veja a última página do relatório da instalação, ou use "
                  "“VYONIX Diagnóstico”."))
    else:
        add(Check("port", f"Porta {port}", "ok", "Atendida pelo VYONIX." if owner else "Livre."))
    _web(r, pr, port)
    _firewall(r, pr, port)
    return r


def _state(s: str | None) -> str:
    return {"Stopped": "parado", "Start Pending": "iniciando", "Stop Pending": "parando", "Paused": "pausado"}.get(
        s or "", s or "desconhecido")


def _web(r: Result, pr: Probes, port: int) -> None:
    add = r.checks.append
    resp = pr.https("127.0.0.1", port, "/api/v1/health")
    if resp is None:
        add(Check("web.localhost", f"Sistema web em https://localhost:{port}", "fail",
                  "Sem resposta HTTPS neste computador.",
                  "Confira os itens acima (serviços, banco e porta). Lembre: o endereço começa com https://, não http://."))
        return
    code, body = resp
    try:
        h = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        h = {}
    if code != 200 or h.get("status") != "ok" or not h.get("database"):
        add(Check("web.localhost", f"Sistema web em https://localhost:{port}", "fail",
                  f"O VYONIX respondeu, mas sem banco ou com erro (HTTP {code}).",
                  "Inicie o serviço VyonixPostgreSQL e aguarde 1 minuto; o Core reconecta sozinho."))
        return
    add(Check("web.localhost", f"Sistema web em https://localhost:{port}", "ok",
              f"API respondendo (versão {h.get('version')}, banco ok).", ""))
    r.urls.append(f"https://localhost:{port}/")
    page = pr.https("127.0.0.1", port, "/")
    if page and page[0] == 200 and b"<html" in page[1][:2000].lower():
        add(Check("web.frontend", "Interface web", "ok", "Página inicial entregue."))
    else:
        add(Check("web.frontend", "Interface web", "fail", "A API responde, mas a página inicial não foi entregue.",
                  "Reinstale a mesma versão (arquivos da interface ausentes ou danificados)."))
    for ip in pr.lan_ips():
        resp = pr.https(ip, port, "/api/v1/health")
        if resp and resp[0] == 200:
            r.urls.append(f"https://{ip}:{port}/")
            add(Check(f"web.lan.{ip}", f"Acesso pelo IP {ip}", "ok", f"https://{ip}:{port}/ responde neste computador."))
        else:
            add(Check(f"web.lan.{ip}", f"Acesso pelo IP {ip}", "warn",
                      f"https://{ip}:{port}/ não respondeu (o sistema pode estar limitado a este computador).",
                      "Use “VYONIX Diagnóstico” → Reparar; se persistir, envie o relatório."))


def _firewall(r: Result, pr: Probes, port: int) -> None:
    add = r.checks.append
    found = pr.rules()
    if found is None:
        add(Check("firewall", "Firewall do Windows", "info", "Não foi possível ler as regras (sem permissão)."))
        return
    rules = [x for x in found if str(x.get("port")) == str(port) and str(x.get("enabled")) == "True"]
    if not rules:
        add(Check("firewall", "Firewall do Windows", "warn",
                  f"Nenhuma regra do VYONIX ativa para a porta {port}: outros computadores não acessam.",
                  "“VYONIX Diagnóstico” → Reparar (recria a regra; o firewall continua ligado)."))
        return
    covered = set()
    for x in rules:
        covered |= {p.strip() for p in str(x.get("profile", "")).split(",") if p.strip()}
    public_nets = [p for p in pr.profiles() if (p.get("category") or "").lower() == "public"]
    if public_nets and "Public" not in covered and "Any" not in covered:
        names = ", ".join(p.get("alias") or "?" for p in public_nets)
        add(Check("firewall", "Firewall do Windows", "warn",
                  f"A rede “{names}” está classificada como Pública e a regra do VYONIX vale só para redes privadas e "
                  "de domínio: outros computadores não conseguem acessar.",
                  "“VYONIX Diagnóstico” → Reparar (cria a regra da sub-rede local) ou classifique a rede como Privada "
                  "(Configurações do Windows → Rede → Propriedades)."))
    else:
        add(Check("firewall", "Firewall do Windows", "ok",
                  f"Regras do VYONIX ativas para a porta {port} ({', '.join(sorted(covered))})."))


# --------------------------------------------------------------------------- relatório

def render_html(res: Result) -> str:
    color = {"ok": "#2e7d4f", "warn": "#a85a00", "fail": "#b3261e", "info": "#45606f"}
    label = {"ok": "OK", "warn": "Atenção", "fail": "Falha", "info": "Info"}
    head = {"ok": "O VYONIX está funcionando.", "warn": "O VYONIX funciona, com avisos.",
            "fail": "O VYONIX não está funcionando — veja o que falhou e como resolver."}[res.status]
    rows = "".join(
        f"<tr><td><span class='b' style='background:{color[c.status]}'>{label[c.status]}</span></td>"
        f"<td><strong>{html.escape(c.title)}</strong><div>{html.escape(c.detail)}</div>"
        + (f"<div class='fix'>Como resolver: {html.escape(c.fix)}</div>" if c.fix and c.status != "ok" else "")
        + "</td></tr>" for c in res.checks)
    urls = "".join(f"<li><a href='{html.escape(u)}'>{html.escape(u)}</a></li>" for u in res.urls)
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>VYONIX — Diagnóstico de inicialização</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f1f5f7;color:#16242f;margin:0;padding:24px}}
main{{max-width:900px;margin:0 auto;background:#fff;border:1px solid #d7e0e6;border-radius:10px;padding:24px}}
h1{{font-size:1.4rem;margin:0 0 4px}}table{{width:100%;border-collapse:collapse;margin-top:12px}}
td{{border-top:1px solid #e3e9ee;padding:10px 8px;vertical-align:top}}.b{{color:#fff;border-radius:99px;padding:2px 10px;
font-size:.8rem;white-space:nowrap}}.fix{{margin-top:4px;color:#45606f}}.sum{{padding:10px 12px;border-radius:8px;
background:{'#e3f3e9' if res.status == 'ok' else '#fbefdc' if res.status == 'warn' else '#fbe6e4'}}}</style></head>
<body><main><h1>VYONIX — Diagnóstico de inicialização</h1><p>Verificado em {html.escape(res.checked_at)} · porta {res.port}</p>
<p class="sum"><strong>{head}</strong></p>
{f"<p>Endereços que responderam (use <strong>https://</strong>):</p><ul>{urls}</ul>" if urls else ""}
<table>{rows}</table>
<p style="color:#45606f;font-size:.85rem">Somente leitura: nada foi alterado. O primeiro acesso mostra um aviso de
certificado (certificado da própria instalação): Avançado → Continuar.</p></main></body></html>"""


# --------------------------------------------------------------------------- sondas reais (Windows)

def _https(host: str, port: int, path: str) -> tuple[int, bytes] | None:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE                     # diagnóstico local: só disponibilidade, sem enviar dados
    url = f"https://{host}:{port}{path}"
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), urllib.request.ProxyHandler({}))
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "VYONIX-DEPLOY-startup"}), timeout=8) as r:
            return r.status, r.read(200_000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000) if hasattr(e, "read") else b""
    except Exception:  # noqa: BLE001
        return None


def _tcp(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def _safe(fn, fallback):
    """Uma sonda que falha (sem permissão, PowerShell indisponível) não derruba o diagnóstico."""
    def wrapped(*a):
        try:
            return fn(*a)
        except Exception:  # noqa: BLE001
            return fallback
    return wrapped


def default_probes() -> Probes:
    from vyonix_deploy.sysrun import IS_WINDOWS, as_list, powershell

    def service(name):
        if not IS_WINDOWS:
            return None
        r = powershell("$s = Get-CimInstance Win32_Service -Filter (\"Name='\" + $A.n + \"'\"); if (-not $s) { return $null }; "
                       "[pscustomobject]@{ state=$s.State; start=$s.StartMode; delayed=[bool]$s.DelayedAutoStart }",
                       {"n": name})
        return r or None

    def lan_ips():
        if not IS_WINDOWS:
            return []
        return [x for x in as_list(powershell(
            "@(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike "
            "'127.*' -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { $_.IPAddress })")) if x][:6]

    def profiles():
        if not IS_WINDOWS:
            return []
        return as_list(powershell("@(Get-NetConnectionProfile -ErrorAction SilentlyContinue | ForEach-Object { "
                                  "[pscustomobject]@{ alias=[string]$_.InterfaceAlias; category=[string]$_.NetworkCategory } })"))

    def rules():
        if not IS_WINDOWS:
            return []
        return as_list(powershell("@(Get-NetFirewallRule -Name 'VYONIX-core-*' -ErrorAction SilentlyContinue | ForEach-Object { "
                                  "$pf = $_ | Get-NetFirewallPortFilter; [pscustomobject]@{ id=$_.Name; enabled=[string]$_.Enabled; "
                                  "profile=[string]$_.Profile; port=[string]$pf.LocalPort } })"))

    def port_owner(port):
        if not IS_WINDOWS:
            return None
        r = powershell("$c = Get-NetTCPConnection -State Listen -LocalPort $A.p -ErrorAction SilentlyContinue | Select-Object -First 1; "
                       "if (-not $c) { return $null }; $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; "
                       "[pscustomobject]@{ pid=[int]$c.OwningProcess; process=[string]$p.ProcessName }", {"p": int(port)})
        return r or None

    def uptime_s():
        if not IS_WINDOWS:
            return None
        try:
            v = powershell("[int]((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalSeconds")
            return float(v)
        except Exception:  # noqa: BLE001
            return None

    return Probes(service=_safe(service, None), tcp=_tcp, https=_https, lan_ips=_safe(lan_ips, []),
                  profiles=_safe(profiles, []), rules=_safe(rules, None), port_owner=_safe(port_owner, None),
                  uptime_s=_safe(uptime_s, None))


def wait_until_ready(port: int, *, pg_port: int = 5544, timeout: float = 0, probes: Probes | None = None) -> Result:
    """Verifica; se o Core ainda está iniciando (pouco depois do boot), espera até ``timeout`` segundos."""
    end = time.monotonic() + timeout
    while True:
        res = run_checks(port, pg_port=pg_port, probes=probes)
        if res.web_ok or time.monotonic() >= end or not _starting(res):
            return res
        time.sleep(5)


def _starting(res: Result) -> bool:
    """Vale a pena esperar: serviço ainda dentro da janela de início após o boot, ou Core no ar sem responder ainda."""
    by = {c.id: c for c in res.checks}
    if any(c.id.startswith("service.") and c.status == "warn" for c in res.checks):
        return True
    core, db, port = by.get("service.VyonixCore"), by.get("database"), by.get("port")
    busy = bool(port and port.status == "fail" and "ocupada" in port.detail)
    return bool(core and core.status == "ok" and db and db.status == "ok" and not busy)


def to_text(res: Result) -> str:
    sym = {"ok": "[OK]   ", "warn": "[AVISO]", "fail": "[FALHA]", "info": "[INFO] "}
    out = [f"VYONIX — diagnóstico de inicialização (porta {res.port}): "
           + {"ok": "funcionando", "warn": "funcionando com avisos", "fail": "NÃO está funcionando"}[res.status]]
    for c in res.checks:
        out.append(f"{sym[c.status]} {c.title}: {c.detail}")
        if c.fix and c.status != "ok":
            out.append(f"          Como resolver: {c.fix}")
    if res.urls:
        out.append("Endereços: " + "  ".join(res.urls))
    return "\n".join(out)


def as_json(res: Result) -> str:
    return json.dumps(res.as_dict(), ensure_ascii=False, indent=2)


def summary(res: Result) -> dict[str, Any]:
    return res.as_dict()
