"""Rotas de acesso: login, sessão, troca de senha e segundo fator (TOTP)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from vyonix.api.app import COOKIE, AuthPending, Ctx, client_ip, platform
from vyonix.auth import service as auth
from vyonix.errors import Unauthorized, ValidationFailed, VyonixError
from vyonix.tenancy import service as tenancy

router = APIRouter()


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=256)
    organization: str | None = Field(None, max_length=40)


class PasswordIn(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=20)


def _me(c_or_p) -> dict:
    p = c_or_p.p if isinstance(c_or_p, Ctx) else c_or_p
    return {**p.public(), "csrf": p.csrf}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    plat = platform(request)
    ip = client_ip(request)
    if not request.app.state.login_limiter.hit(ip):
        raise VyonixError("Muitas tentativas. Aguarde um minuto.", code="rate_limited")
    # Só usuário e senha: a instalação local atende uma organização; no servidor com várias instituições, o login
    # é único na plataforma e o diretório global indica a instituição. O código da organização continua aceito
    # (compatibilidade) para contas antigas com o mesmo login em duas organizações.
    code = (body.organization or "").strip().lower()
    if code:
        tid = tenancy.resolve(plat.db, code)
    elif plat.edge:
        tid = tenancy.resolve(plat.db, plat.cfg.default_organization)
    else:
        from vyonix.auth import directory
        with plat.db.service_session() as s:
            tid = directory.resolve(s, body.username)
    if tid is None:
        auth.passwords.check_password(body.password, auth.passwords.DUMMY_HASH)
        raise Unauthorized(auth.GENERIC)
    err = None
    with plat.db.session(tid) as s:
        try:
            token, ses, _u = auth.login(s, body.username, body.password, ip=ip,
                                        user_agent=request.headers.get("user-agent"))
        except Unauthorized as exc:
            err = exc                       # a tentativa (e o bloqueio) precisa ser confirmada
    if err:
        raise err
    with plat.db.session(tid) as s:
        p = auth.authenticate(s, token)
    response.set_cookie(COOKIE, token, httponly=True, secure=request.app.state.cookie_secure, samesite="strict",
                        path="/")
    return _me(p)


@router.post("/auth/logout")
def logout(response: Response, c: Ctx = AuthPending):
    with c.session() as s:
        auth.logout(s, c.p, ip=c.ip)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(c: Ctx = AuthPending):
    return _me(c)


@router.post("/auth/password")
def change_password(body: PasswordIn, c: Ctx = AuthPending):
    with c.session() as s:
        auth.change_password(s, c.p, body.current, body.new, ip=c.ip)
    return {"ok": True}


@router.post("/auth/mfa/enroll")
def mfa_enroll(c: Ctx = AuthPending):
    if c.p.stage not in ("ok", "mfa_enroll"):
        raise ValidationFailed("Conclua a etapa pendente antes de cadastrar o segundo fator.")
    with c.session() as s:
        return auth.mfa_enroll_start(s, c.p, c.plat.mfa_key)


@router.post("/auth/mfa/confirm")
def mfa_confirm(body: CodeIn, c: Ctx = AuthPending):
    with c.session() as s:
        codes = auth.mfa_enroll_confirm(s, c.p, c.plat.mfa_key, body.code, ip=c.ip)
    return {"recovery_codes": codes}


@router.post("/auth/mfa/verify")
def mfa_verify(body: CodeIn, c: Ctx = AuthPending):
    err = None
    with c.session() as s:
        try:
            auth.mfa_verify(s, c.p, c.plat.mfa_key, body.code, ip=c.ip)
        except Unauthorized as exc:
            err = exc                       # tentativas erradas contam para o bloqueio
    if err:
        raise err
    return {"ok": True}
