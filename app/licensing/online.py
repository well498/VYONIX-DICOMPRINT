"""Consulta ao VYONIX License Server (licenças com validação online).

O que é enviado: identificadores da licença e da instalação, Hardware ID, versão do programa, um
número aleatório de uso único e a sequência da última autorização. **Nenhuma** imagem, nome de
paciente ou informação clínica (``REQUEST_FIELDS`` é a lista completa, conferida nos testes).

Conexão: HTTPS (TLS 1.2+). Se a licença traz a impressão digital do certificado do servidor
(``server_pin``, assinada), o certificado precisa corresponder a ela; senão, vale a cadeia de
certificação do Windows (e, opcionalmente, um arquivo de autoridade configurado pelo administrador).

Resultado técnico (não comercial) de cada consulta — falta de internet nunca é tratada como
inadimplência:

* ``ok``                  autorização recebida e válida;
* ``no_internet``         nome do servidor não resolvido (internet ou DNS indisponível);
* ``server_unavailable``  servidor não respondeu, recusou a conexão ou devolveu erro interno;
* ``rejected``            servidor respondeu com recusa (licença desconhecida, instalação divergente);
* ``invalid_response``    resposta com assinatura, consulta ou certificado divergentes (suspeita de
                          adulteração ou interceptação) — registrada como evento de segurança.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import secrets
import socket
import ssl
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable

from vyonix_protocol import formats as F

from app import __version__
from app.core.errors import ValidationError

REQUEST_FIELDS = ("v", "product_id", "license_id", "installation_id", "hardware_id", "nonce", "known_seq",
                  "app_version", "client_time")
TIMEOUT_S = 20.0


@dataclass
class OnlineResult:
    result: str
    message: str
    authorization: dict[str, Any] | None = None


class OnlineError(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def _post(url: str, body: dict, *, pin: str | None, ca_file: str | None, proxy: str | None,
          timeout: float = TIMEOUT_S) -> tuple[int, bytes]:
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or not u.hostname:
        raise OnlineError("rejected", f"Endereço do License Server inválido: {url}")
    host, port = u.hostname, u.port or 443
    if pin:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE                  # conferido pela impressão digital assinada, abaixo
    else:
        ctx = ssl.create_default_context(cafile=ca_file or None)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        if proxy:
            ph, _, pp = proxy.rpartition(":")
            conn = http.client.HTTPSConnection(ph or proxy, int(pp or 8080), timeout=timeout, context=ctx)
            conn.set_tunnel(host, port)
        else:
            socket.getaddrinfo(host, port)               # separa "sem internet/DNS" de "servidor fora do ar"
            conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
        conn.connect()
    except socket.gaierror as exc:
        raise OnlineError("no_internet", f"Não foi possível localizar {host} (internet ou DNS indisponível).") from exc
    except ssl.SSLCertVerificationError as exc:
        raise OnlineError("invalid_response", f"Certificado do License Server não confiável: {exc.verify_message}.") \
            from exc
    except (OSError, ssl.SSLError) as exc:
        raise OnlineError("server_unavailable", f"License Server indisponível ({host}:{port}): {exc}.") from exc
    try:
        if pin:
            der = conn.sock.getpeercert(binary_form=True) or b""
            if hashlib.sha256(der).hexdigest().lower() != pin.replace(":", "").lower():
                raise OnlineError("invalid_response", "O certificado do servidor não é o registrado na licença "
                                                      "(possível interceptação).")
        path = (u.path.rstrip("/") or "") + "/v1/authorize"
        data = json.dumps(body).encode()
        conn.request("POST", path, body=data, headers={"Content-Type": "application/json",
                                                       "User-Agent": f"VYONIX-DICOM-Print/{__version__}"})
        r = conn.getresponse()
        return r.status, r.read(1_000_000)
    except OnlineError:
        raise
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise OnlineError("server_unavailable", f"License Server não respondeu: {exc}.") from exc
    finally:
        conn.close()


class OnlineValidator:
    """Consulta o servidor e aplica a autorização recebida (chamada pelo serviço e pelo botão
    *Verificar agora*)."""

    def __init__(self, svc, post: Callable[..., tuple[int, bytes]] | None = None) -> None:
        self.svc = svc
        self._post = post or _post

    def request_body(self, nonce: str) -> dict[str, Any]:
        lic = self.svc.installed_license()
        cur = self.svc.authorizations.current(lic.license_id) if lic else None
        ts = self.svc.time.check()
        return {"v": F.VERSION, "product_id": F.PRODUCT_ID, "license_id": lic.license_id,
                "installation_id": self.svc.installation_id(), "hardware_id": self.svc.hardware_id(),
                "nonce": nonce, "known_seq": int(cur["seq"]) if cur else 0, "app_version": __version__,
                "client_time": F.iso(ts.effective)}

    def check(self, *, actor: str = "sistema") -> OnlineResult:
        lic = self.svc.installed_license()
        if lic is None or lic.type == "demo":
            raise ValidationError("Nenhuma licença comercial instalada.")
        policy = F.license_policy({"policy": lic.extra.get("policy")} if lic.extra.get("policy") is not None else {})
        if policy["validation"] != "online":
            raise ValidationError("Esta licença é offline: a renovação é feita por arquivo (.vyauth).")
        url = (self.svc.get("licensing.server_url_override") or policy["server_url"] or "").strip()
        if not url:
            raise ValidationError("A licença não informa o endereço do License Server.")
        nonce = secrets.token_hex(16)
        body = self.request_body(nonce)
        assert tuple(sorted(body)) == tuple(sorted(REQUEST_FIELDS))
        try:
            status, data = self._post(url, body, pin=policy.get("server_pin"),
                                      ca_file=self.svc.get("licensing.server_ca_file") or None,
                                      proxy=self.svc.get("licensing.proxy") or None)
        except OnlineError as exc:
            return self.svc.record_online(exc.kind, str(exc), actor=actor)
        try:
            resp = json.loads(data or b"{}")
        except ValueError:
            resp = {}
        if status >= 500:
            return self.svc.record_online("server_unavailable", f"License Server com erro interno (HTTP {status}).",
                                          actor=actor)
        if status != 200:
            return self.svc.record_online("rejected", str(resp.get("error") or f"HTTP {status}")[:300], actor=actor)
        doc = resp.get("authorization")
        if not isinstance(doc, str):
            return self.svc.record_online("invalid_response", "Resposta do servidor sem autorização.", actor=actor)
        try:
            p = self.svc.apply_authorization(doc, actor=actor, source="online", expected_nonce=nonce)
        except ValidationError as exc:
            return self.svc.record_online("invalid_response", str(exc), actor=actor)
        return self.svc.record_online("ok", "Autorização online recebida.", actor=actor, authorization=p)
