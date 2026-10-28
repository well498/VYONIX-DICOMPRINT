"""API HTTP do VYONIX Core (FastAPI) e entrega da interface web.

Segurança da API:

* Sessão em cookie ``vyx_session`` — ``HttpOnly``, ``Secure`` (HTTPS), ``SameSite=Strict``; o token
  nunca fica acessível ao JavaScript. Requisições que alteram dados exigem o cabeçalho
  ``X-CSRF-Token`` com o token anti-CSRF da sessão.
* Toda consulta roda com o row level security da clínica da sessão.
* Limite de tentativas de login por endereço IP (além do bloqueio por usuário).
* Cabeçalhos: CSP restrita a ``'self'``, ``X-Frame-Options: DENY``, ``nosniff``, sem referrer, sem
  cache nas respostas da API.
* Erros com ``{"error": código, "message": texto, "details": {...}}``; nenhuma pilha de erro é
  devolvida ao navegador.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from vyonix import __version__
from vyonix.auth import service as auth
from vyonix.context import Platform
from vyonix.errors import Forbidden, Unauthorized, VyonixError

log = logging.getLogger("vyonix.api")
COOKIE = "vyx_session"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
WEB_DIST = (Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "web" if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2] / "web" / "dist")


class RateLimiter:
    def __init__(self, limit: int, window_s: float) -> None:
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = {}
        self.lock = threading.Lock()

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits.setdefault(key, deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self.hits) > 10000:
                self.hits = {k: v for k, v in self.hits.items() if v}
            return True


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp: Response = await call_next(request)
        h = resp.headers
        h.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; style-src 'self' "
                                                "'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; "
                                                "form-action 'self'")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        if request.url.scheme == "https":
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        return resp


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def create_app(plat: Platform, *, cookie_secure: bool = True, web_dist: Path | None = None,
               viewer_dist: Path | None = None) -> FastAPI:
    app = FastAPI(title="VYONIX Core", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.plat = plat
    app.state.cookie_secure = cookie_secure
    app.state.login_limiter = RateLimiter(20, 60.0)
    app.add_middleware(SecurityHeaders)

    @app.exception_handler(VyonixError)
    async def _vy(request: Request, exc: VyonixError):
        return JSONResponse({"error": exc.code, "message": str(exc), "details": exc.details}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _val(request: Request, exc: RequestValidationError):
        errs = [{"field": ".".join(str(x) for x in e.get("loc", [])[1:]), "message": e.get("msg", "")}
                for e in exc.errors()]
        return JSONResponse({"error": "validation", "message": "Dados inválidos.", "details": {"errors": errs}},
                            status_code=422)

    @app.exception_handler(Exception)
    async def _any(request: Request, exc: Exception):
        log.exception("Erro interno em %s %s", request.method, request.url.path)
        return JSONResponse({"error": "internal", "message": "Erro interno. O detalhe foi registrado no servidor.",
                             "details": {}}, status_code=500)

    from vyonix.api import (routes_admin, routes_auth, routes_clinical, routes_license, routes_pacs, routes_report,
                            routes_ris)
    for mod in (routes_auth, routes_admin, routes_license, routes_clinical, routes_pacs, routes_ris, routes_report):
        app.include_router(mod.router, prefix="/api/v1")

    @app.get("/api/v1/health")
    def health():
        from sqlalchemy import text
        try:
            with plat.db.session() as s:
                s.execute(text("SELECT 1"))
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
        return JSONResponse({"status": "ok" if db_ok else "degraded", "database": db_ok, "version": __version__,
                             "mode": plat.cfg.mode}, status_code=200 if db_ok else 503)

    from vyonix.api import viewer
    viewer.mount(app, viewer_dist)

    @app.get("/api/v1/health/detail")
    def health_detail(c: Ctx = Depends(needs("core.settings.read"))):
        from vyonix import monitoring
        with c.session() as s:
            return monitoring.health_detail(c.plat, s)

    dist = web_dist or WEB_DIST
    if (dist / "index.html").exists():
        root = dist.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"error": "not_found", "message": "Rota inexistente.", "details": {}}, 404)
            f = (root / path).resolve()
            if path and f.is_file() and root in f.parents:
                return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"}
                                    if "/assets/" in f.as_posix() else None)
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})
    return app


# --------------------------------------------------------------------------- dependências

def platform(request: Request) -> Platform:
    return request.app.state.plat


class Ctx:
    """Contexto autenticado de uma requisição."""

    def __init__(self, plat: Platform, p: auth.Principal, ip: str) -> None:
        self.plat, self.p, self.ip = plat, p, ip

    @property
    def actor(self) -> dict[str, Any]:
        return {"actor": self.p.username, "actor_id": self.p.user_id, "ip": self.ip}

    def session(self):
        return self.plat.db.session(self.p.tenant_id)

    def require(self, perm: str, site_id: uuid.UUID | None = None) -> None:
        auth.require(self.p, perm, site_id)


def _principal(request: Request, *, allow_pending: bool) -> Ctx:
    plat = platform(request)
    token = request.cookies.get(COOKIE)
    tid = auth.tenant_of_token(token or "")
    if not token or tid is None:
        raise Unauthorized("Entre no sistema.")
    with plat.db.session(tid) as s:
        p = auth.authenticate(s, token)
    if request.method in UNSAFE:
        sent = request.headers.get("X-CSRF-Token", "")
        import hmac
        if not sent or not hmac.compare_digest(sent, p.csrf):
            raise Forbidden("Token anti-CSRF ausente ou inválido. Recarregue a página.", code="csrf")
    if not allow_pending and p.stage != "ok":
        raise Forbidden("Conclua a etapa de acesso pendente.", details={"stage": p.stage}, code="stage")
    return Ctx(plat, p, client_ip(request))


def ctx(request: Request) -> Ctx:
    return _principal(request, allow_pending=False)


def ctx_pending(request: Request) -> Ctx:
    return _principal(request, allow_pending=True)


def needs(perm: str) -> Callable[[Request], Ctx]:
    def dep(request: Request) -> Ctx:
        c = ctx(request)
        c.require(perm)
        return c
    return dep


Auth = Depends(ctx)
AuthPending = Depends(ctx_pending)
