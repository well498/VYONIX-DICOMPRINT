"""Adaptador do Banco Inter (API de Cobrança v3 — boleto com Pix), opcional.

Funciona somente no VYONIX License Server, com as credenciais da conta PJ contratante (Client ID,
Client Secret e o certificado digital da aplicação, usado em TLS mútuo). Nada disso existe no
VYONIX DICOM Print instalado nas clínicas.

Endereços (configuráveis, conferir na documentação vigente do Inter antes da homologação):

* produção  ``https://cdpj.partners.bancointer.com.br``
* sandbox   ``https://cdpj-sandbox.partners.uatinter.co``
* token     ``POST /oauth/v2/token`` (client_credentials; escopos ``boleto-cobranca.read`` e
  ``boleto-cobranca.write``)
* cobrança  ``POST /cobranca/v3/cobrancas`` · consulta ``GET /cobranca/v3/cobrancas/{codigoSolicitacao}``
* webhook   ``PUT /cobranca/v3/cobrancas/webhook`` (o Inter chama a URL cadastrada)

Segurança: o aviso do webhook **nunca** é tomado como pagamento — ele só indica qual cobrança
consultar; a situação é sempre confirmada pela consulta autenticada ao banco (``charge_status``).
"""

from __future__ import annotations

import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from vyonix_commercial.billing.base import (CANCELLED, EXPIRED, MANUAL_CHECK, OPEN, OVERDUE, PAID, BillingError,
                                            ChargeRequest, ChargeStatus, WebhookNotice)

PRODUCTION = "https://cdpj.partners.bancointer.com.br"
SANDBOX = "https://cdpj-sandbox.partners.uatinter.co"
SCOPES = "boleto-cobranca.read boleto-cobranca.write"
SITUACAO = {
    "RECEBIDO": PAID, "MARCADO_RECEBIDO": MANUAL_CHECK, "A_RECEBER": OPEN, "EM_PROCESSAMENTO": OPEN,
    "ATRASADO": OVERDUE, "PROTESTO": OVERDUE, "CANCELADO": CANCELLED, "EXPIRADO": EXPIRED,
    "FALHA_EMISSAO": CANCELLED,
}

Transport = Callable[[str, str, dict, bytes | None], tuple[int, bytes]]


@dataclass
class InterConfig:
    client_id: str
    client_secret: str
    cert_file: str                       # certificado da aplicação (.crt/.pem) — TLS mútuo
    key_file: str                        # chave do certificado (.key)
    base_url: str = PRODUCTION
    account: str | None = None           # x-conta-corrente (quando a aplicação tem mais de uma conta)
    ca_file: str | None = None           # autoridade adicional (somente homologação)
    timeout: float = 20.0
    days_to_cancel: int = 30             # numDiasAgenda: dias após o vencimento até a baixa automática

    def __repr__(self) -> str:           # nunca exibir segredos em registros
        return f"InterConfig(base_url={self.base_url!r}, client_id={self.client_id[:4]}…, account={self.account!r})"


class InterProvider:
    name = "inter"

    def __init__(self, cfg: InterConfig, transport: Transport | None = None) -> None:
        self.cfg = cfg
        self._transport = transport or self._https
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ HTTP (TLS mútuo)
    def _context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context(cafile=self.cfg.ca_file) if self.cfg.ca_file else ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(self.cfg.cert_file, self.cfg.key_file)
        return ctx

    def _https(self, method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, bytes]:
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout, context=self._context()) as r:  # noqa: S310
                return r.status, r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, OSError, ssl.SSLError) as exc:
            raise BillingError(f"Banco Inter indisponível: {getattr(exc, 'reason', exc)}") from exc

    def _token_value(self) -> str:
        with self._lock:
            if self._token and self._token[1] > time.monotonic() + 30:
                return self._token[0]
            body = urllib.parse.urlencode({"client_id": self.cfg.client_id, "client_secret": self.cfg.client_secret,
                                           "grant_type": "client_credentials", "scope": SCOPES}).encode()
            status, data = self._transport("POST", self.cfg.base_url + "/oauth/v2/token",
                                           {"Content-Type": "application/x-www-form-urlencoded"}, body)
            if status != 200:
                raise BillingError(f"Banco Inter recusou a autenticação (HTTP {status}).")
            try:
                d = json.loads(data)
                tok, exp = d["access_token"], float(d.get("expires_in", 3600))
            except (ValueError, KeyError) as exc:
                raise BillingError("Resposta de autenticação do Banco Inter inesperada.") from exc
            self._token = (tok, time.monotonic() + exp)
            return tok

    def _call(self, method: str, path: str, payload: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._token_value()}", "Accept": "application/json"}
        if self.cfg.account:
            headers["x-conta-corrente"] = self.cfg.account
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        status, data = self._transport(method, self.cfg.base_url + path, headers, body)
        if status == 401:
            self._token = None
        if status >= 300:
            raise BillingError(f"Banco Inter: HTTP {status} em {path}: {data[:300].decode('utf-8', 'replace')}")
        try:
            return json.loads(data) if data else {}
        except ValueError as exc:
            raise BillingError("Resposta do Banco Inter ilegível.") from exc

    # ------------------------------------------------------------------ operações
    def create_charge(self, req: ChargeRequest) -> str:
        doc = "".join(ch for ch in req.payer_document if ch.isdigit())
        payer = {"cpfCnpj": doc, "tipoPessoa": "JURIDICA" if len(doc) == 14 else "FISICA", "nome": req.payer_name[:100]}
        addr = req.payer_address or {}
        payer.update({k: v for k, v in {"endereco": addr.get("endereco"), "cidade": addr.get("cidade"),
                                         "uf": addr.get("uf"), "cep": addr.get("cep"),
                                         "email": req.payer_email}.items() if v})
        payload = {"seuNumero": req.our_number[:15], "valorNominal": round(req.amount_cents / 100, 2),
                   "dataVencimento": req.due_date, "numDiasAgenda": self.cfg.days_to_cancel, "pagador": payer}
        if req.message:
            payload["mensagem"] = {"linha1": req.message[:78]}
        d = self._call("POST", "/cobranca/v3/cobrancas", payload)
        ref = d.get("codigoSolicitacao")
        if not ref:
            raise BillingError("O Banco Inter não devolveu o código da cobrança.")
        return str(ref)

    def charge_status(self, provider_ref: str) -> ChargeStatus:
        d = self._call("GET", "/cobranca/v3/cobrancas/" + urllib.parse.quote(provider_ref, safe=""))
        c = d.get("cobranca") or d
        if str(c.get("codigoSolicitacao") or provider_ref) != provider_ref:
            raise BillingError("Resposta do Banco Inter para outra cobrança.")
        sit = str(c.get("situacao") or "").upper()
        paid = c.get("valorTotalRecebido")
        when = c.get("dataSituacao") or c.get("dataHoraSituacao")
        paid_at = None
        if when and SITUACAO.get(sit) == PAID:
            try:
                paid_at = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
                if paid_at.tzinfo is None:
                    paid_at = paid_at.replace(tzinfo=timezone.utc)
            except ValueError:
                paid_at = None
        return ChargeStatus(provider_ref=provider_ref, status=SITUACAO.get(sit, OPEN), provider_status=sit,
                            paid_cents=int(round(float(paid) * 100)) if paid not in (None, "") else None,
                            paid_at=paid_at, raw=c)

    def register_webhook(self, url: str) -> None:
        self._call("PUT", "/cobranca/v3/cobrancas/webhook", {"webhookUrl": url})

    def parse_webhook(self, body: bytes) -> list[WebhookNotice]:
        try:
            data = json.loads(body or b"[]")
        except ValueError as exc:
            raise BillingError("Notificação do Banco Inter ilegível.") from exc
        items = data if isinstance(data, list) else [data]
        out = []
        for it in items:
            if not isinstance(it, dict) or not it.get("codigoSolicitacao"):
                continue
            ref = str(it["codigoSolicitacao"])
            sit = str(it.get("situacao") or "").upper()
            key = f"{ref}:{sit}:{it.get('dataHoraSituacao') or it.get('dataSituacao') or ''}"
            out.append(WebhookNotice(provider_ref=ref, event_key=key, claimed_status=sit))
        return out
