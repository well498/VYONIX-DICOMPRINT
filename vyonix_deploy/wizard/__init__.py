"""Assistente do DEPLOY no navegador: servidor local só em 127.0.0.1, porta aleatória, acesso por
token de uso único (trocado por cookie HttpOnly/SameSite=Strict na primeira abertura)."""

from __future__ import annotations

import json
import secrets
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from vyonix_deploy import __version__
from vyonix_deploy.config import DeployConfig
from vyonix_deploy.errors import Blocked, DeployError, NotApproved

HERE = Path(__file__).resolve().parent
IDLE_LIMIT_S = 2 * 3600          # o assistente encerra sozinho após 2 h sem uso


class State:
    def __init__(self, deploy) -> None:
        self.d = deploy
        self.token = secrets.token_urlsafe(24)
        self.session = secrets.token_urlsafe(24)
        self.used = False
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}
        self.cfgs: dict[str, DeployConfig] = {}


def serve(d, *, port: int = 0, open_browser: bool = True, start: str | None = None) -> int:
    st = State(d)

    class H(BaseHTTPRequestHandler):
        server_version = "VYONIX-DEPLOY"
        sys_version = ""

        def log_message(self, *a):  # silencioso
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
            data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(
                body, ensure_ascii=False, default=str)).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                        "script-src 'self'; frame-ancestors 'none'")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _authed(self) -> bool:
            c = self.headers.get("Cookie", "")
            return any(p.strip() == f"vyxdeploy={st.session}" for p in c.split(";"))

        def do_GET(self):  # noqa: N802
            u = urlsplit(self.path)
            if u.path == "/" and "t" in parse_qs(u.query):
                with st.lock:
                    ok = not st.used and secrets.compare_digest(parse_qs(u.query)["t"][0], st.token)
                    if ok:
                        st.used = True
                if not ok:
                    return self._send(403, "Link do assistente já usado ou inválido. Abra o assistente de novo.",
                                      "text/plain; charset=utf-8")
                return self._send(303, b"", headers={"Location": "/" + (f"#{start}" if start else ""),
                                                     "Set-Cookie": f"vyxdeploy={st.session}; HttpOnly; "
                                                                   "SameSite=Strict; Path=/"})
            if not self._authed():
                return self._send(403, "Acesso negado.", "text/plain; charset=utf-8")
            if u.path == "/":
                return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/app.js":
                return self._send(200, (HERE / "app.js").read_bytes(), "text/javascript; charset=utf-8")
            if u.path == "/api/state":
                cfg = st.d.saved_config()
                return self._send(200, {"version": __version__, "installed": cfg is not None,
                                        "config": (cfg or DeployConfig()).to_dict(), "runs": st.d.db.runs(15),
                                        "pending": st.d.db.unfinished() is not None})
            if u.path.startswith("/api/job/"):
                jid = u.path.rsplit("/", 1)[1]
                job = st.jobs.get(jid)
                if not job:
                    return self._send(404, {"error": "trabalho inexistente"})
                out = dict(job)
                if job.get("run_id"):
                    out["steps"] = [{k: s[k] for k in ("step_id", "title", "status", "verify_msg", "error")}
                                    for s in st.d.db.steps(job["run_id"])]
                    out["events"] = [dict(e) for e in st.d.db.x(
                        "SELECT at, level, message FROM events WHERE run_id = ? ORDER BY id DESC LIMIT 30",
                        (job["run_id"],)).fetchall()]
                return self._send(200, out)
            if u.path.startswith("/api/report/"):
                rid = u.path.rsplit("/", 1)[1]
                r = st.d.db.x("SELECT path FROM reports WHERE run_id = ? AND kind = 'pdf' ORDER BY id DESC LIMIT 1",
                              (rid,)).fetchone()
                if not r:
                    return self._send(404, {"error": "relatório inexistente"})
                p = Path(r["path"])
                return self._send(200, p.read_bytes(), "application/pdf",
                                  {"Content-Disposition": f'attachment; filename="{p.name}"'})
            return self._send(404, {"error": "rota inexistente"})

        def do_POST(self):  # noqa: N802
            if not self._authed() or self.headers.get("X-Vyonix-Wizard") != "1":
                return self._send(403, {"error": "Acesso negado."})
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                return self._send(413, {"error": "Requisição grande demais."})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._send(400, {"error": "JSON inválido."})
            u = urlsplit(self.path)
            try:
                return self._send(200, route(st, u.path, body))
            except Blocked as exc:
                return self._send(409, {"error": "Impeditivos encontrados — nada foi alterado.",
                                        **json.loads(str(exc))})
            except (DeployError, NotApproved, ValueError) as exc:
                return self._send(422, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                st.d.db.event(None, "ERROR", traceback.format_exc()[:4000])
                return self._send(500, {"error": f"Erro interno: {type(exc).__name__}. Detalhe no log do DEPLOY."})

    httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/?t={st.token}"
    print(f"Assistente do VYONIX DEPLOY: {url}", flush=True)
    if open_browser:
        import subprocess
        import sys
        if sys.platform == "win32":
            # explorer.exe entrega a URL ao shell do usuário: o navegador não roda elevado
            subprocess.Popen(["explorer.exe", url])
        else:
            webbrowser.open(url)
    last = {"t": time.monotonic()}
    orig = H.handle_one_request

    def touch(self):
        last["t"] = time.monotonic()
        return orig(self)
    H.handle_one_request = touch

    def idle_guard():
        while True:
            time.sleep(30)
            busy = any(j.get("status") == "running" for j in st.jobs.values())
            if not busy and time.monotonic() - last["t"] > IDLE_LIMIT_S:
                httpd.shutdown()
                return
    threading.Thread(target=idle_guard, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def route(st: State, path: str, body: dict):
    d = st.d
    if path == "/api/inventory":
        from vyonix_deploy import compat
        inv = d.inventory()
        cfg = _cfg(body, d)
        return {"inventory": inv, "compatibility": [f.as_dict() for f in compat.evaluate(inv, cfg)]}
    if path == "/api/plan":
        kind = body.get("kind")
        if kind not in ("install", "update", "repair", "reconfigure", "uninstall"):
            raise DeployError("Operação inválida.")
        cfg = _cfg(body, d)
        if kind == "repair":
            diag = d.diagnose(cfg)
            plan, ids, cfg = d.repair_plan(diag, cfg)
            plan["suggested"] = ids
            plan["problems"] = diag["problems"]
        else:
            plan = d.plan(kind, cfg)
        st.cfgs[plan["run_id"]] = cfg
        return plan
    if path == "/api/approve":
        rid = body["run_id"]
        cfg = st.cfgs.get(rid) or _cfg({}, d)
        d.approve(rid, cfg, items=body.get("items"), confirmations=body.get("confirmations") or {},
                  expected_sha=body.get("plan_sha"), via="assistente")
        extra = {k: v for k, v in (body.get("secrets") or {}).items() if k in ("admin_password", "pfx_password") and v}
        jid = secrets.token_hex(6)
        st.jobs[jid] = {"id": jid, "run_id": rid, "status": "running"}

        def work():
            try:
                r = d.execute(rid, extra=extra)
                st.jobs[jid].update(status=r["status"], message=r["message"], report=r["report"])
            except Exception as exc:  # noqa: BLE001
                st.jobs[jid].update(status="error", message=str(exc))
        threading.Thread(target=work, daemon=True).start()
        return {"job": jid}
    if path == "/api/diagnose":
        r = d.diagnose()
        return {k: v for k, v in r.items() if k != "observed"}
    if path == "/api/report-only":
        return d.report_only(body["run_id"])
    raise DeployError("Rota inexistente.")


def _cfg(body: dict, d) -> DeployConfig:
    base = (d.saved_config() or DeployConfig()).to_dict()
    opts = body.get("config") or {}
    net = {**base.get("network", {}), **(opts.pop("network", None) or {})}
    base.update({k: v for k, v in opts.items() if k in base})
    base["network"] = net
    cfg = DeployConfig.from_dict(base)
    cfg.validate()
    return cfg
