"""Autoteste de ponta a ponta do License Server (usado no CI e pelo administrador após instalar).

Pasta temporária, chaves descartáveis geradas na hora, servidor HTTPS real em 127.0.0.1, consulta de
autorização pelo mesmo código do VYONIX DICOM Print (``app.licensing.online``) com conferência da
impressão digital do certificado, da assinatura e do número de uso único; API administrativa com
login; repetição de consulta recusada.
"""

from __future__ import annotations

import http.client
import json
import secrets
import ssl
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _admin(port: int, method: str, path: str, body=None, token=None) -> tuple[int, dict]:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    c = http.client.HTTPSConnection("127.0.0.1", port, timeout=15, context=ctx)
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
    r = c.getresponse()
    data = json.loads(r.read() or b"{}")
    c.close()
    return r.status, data


def run() -> dict:
    from vyonix_protocol import crypto
    from vyonix_protocol import formats as F

    from app.licensing.online import _post
    from license_server.core import ServerCore
    from license_server.http import LicenseHTTPServer, certificate_pin, ensure_certificate

    rep: dict = {"ok": False, "steps": []}
    with tempfile.TemporaryDirectory(prefix="vyx-ls-selftest-") as tmp:
        data = Path(tmp)
        lic_key, srv_key = crypto.generate_ed25519(), crypto.generate_ed25519()
        lic_pub = crypto.public_hex(lic_key)
        srv_pub = crypto.public_hex(srv_key)
        core = ServerCore(data, signer=("selftest-srv", srv_key), license_keys={"selftest-lic": lic_pub},
                          license_key_scopes={"selftest-lic": ("license",)})
        core.create_user(None, "admin", "Administrador", "admin", "Autoteste-Senha-123")
        cert, key = ensure_certificate(data / "tls", ["127.0.0.1"])
        pin = certificate_pin(cert)
        srv = LicenseHTTPServer(("127.0.0.1", 0), core, cert=cert, key=key)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            now = datetime.now(timezone.utc)
            hw = {"uuid": "a" * 64, "system": "b" * 64}
            payload = {"v": 2, "license_id": "VYX-SELFTEST-0001", "product_id": F.PRODUCT_ID, "product": F.PRODUCT_NAME,
                       "type": "monthly", "edition": "Profissional", "customer": {"name": "Autoteste"},
                       "hardware_id": F.hardware_id(hw), "hw": hw, "installation_id": "VYXI-SELFTEST",
                       "issued_at": F.iso(now), "starts_at": F.iso(now), "expires_at": F.iso(now + timedelta(days=30)),
                       "features": list(F.FEATURES),
                       "policy": {"validation": "online", "warn_days": 5, "grace_days": 7, "online_tolerance_days": 10,
                                  "server_url": f"https://127.0.0.1:{port}", "server_pin": pin}}
            doc = F.build_signed(F.LICENSE_FORMAT, payload, "selftest-lic", lic_key.sign)
            st, login = _admin(port, "POST", "/v1/admin/login", {"username": "admin", "password": "Autoteste-Senha-123"})
            assert st == 200, login
            tok = login["token"]
            rep["steps"].append("login administrativo (HTTPS)")
            st, reg = _admin(port, "POST", "/v1/admin/licenses", {"document": doc, "price_cents": 49900}, tok)
            assert st == 200 and reg["state"] == "active", reg
            rep["steps"].append("licença registrada: assinatura ATIVA")
            st, unauth = _admin(port, "GET", "/v1/admin/subscriptions")
            assert st == 401, unauth
            rep["steps"].append("API administrativa sem token: 401")
            nonce = secrets.token_hex(16)
            body = {"v": 2, "product_id": F.PRODUCT_ID, "license_id": payload["license_id"],
                    "installation_id": payload["installation_id"], "hardware_id": payload["hardware_id"],
                    "nonce": nonce, "known_seq": 0, "app_version": "selftest", "client_time": F.iso(now)}
            status, raw = _post(f"https://127.0.0.1:{port}", body, pin=pin, ca_file=None, proxy=None)
            assert status == 200, raw
            auth = F.parse_signed(json.loads(raw)["authorization"], F.AUTHORIZATION_FORMAT)
            assert crypto.verify_ed25519(srv_pub, auth.signed, auth.signature), "assinatura"
            assert auth.payload["nonce"] == nonce and auth.payload["commercial"]["state"] == "active"
            rep["steps"].append("autorização online assinada, número de uso único conferido (certificado fixado)")
            status, raw = _post(f"https://127.0.0.1:{port}", body, pin=pin, ca_file=None, proxy=None)
            assert status == 409, raw
            rep["steps"].append("consulta repetida recusada (409)")
            try:
                _post(f"https://127.0.0.1:{port}", body, pin="00" * 32, ca_file=None, proxy=None)
                raise AssertionError("certificado divergente aceito")
            except Exception as exc:  # noqa: BLE001
                assert getattr(exc, "kind", "") == "invalid_response", exc
            rep["steps"].append("certificado diferente do fixado: recusado")
            st, subs = _admin(port, "GET", "/v1/admin/subscriptions", token=tok)
            assert st == 200 and subs["items"][0]["last_contact_at"], subs
            rep["steps"].append("contato registrado na assinatura")
            assert not core.db.verify_audit()
            rep["steps"].append("auditoria encadeada íntegra")
            rep["ok"] = True
            rep["tls_pin"] = pin
            rep["signing_key_fingerprint"] = crypto.fingerprint(srv_pub)
        except AssertionError as exc:
            rep["error"] = f"falhou: {exc}"
        finally:
            srv.shutdown()
            srv.server_close()
            core.close()
    return rep
