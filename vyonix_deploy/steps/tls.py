"""Certificado HTTPS do VYONIX Core.

Usa o certificado da instituição (arquivo .pfx), com cadeia validada pelo Windows, ou gera um
autoassinado (ECDSA P-256, 825 dias) e registra isso como pendência de segurança. A chave privada
fica só na pasta de dados do Core (permissão restrita); nunca no banco do DEPLOY nem nos relatórios."""

from __future__ import annotations

import base64
import ipaddress
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vyonix_deploy.engine import Context, Step
from vyonix_deploy.errors import DeployError
from vyonix_deploy.sysrun import IS_WINDOWS, powershell

RENEW_BEFORE = timedelta(days=30)


def cert_info(path: Path) -> dict | None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    try:
        c = x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError, ValueError):
        return None
    try:
        san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = [str(n.value) for n in san]
    except x509.ExtensionNotFound:
        names = []
    return {"subject": c.subject.rfc4514_string(), "issuer": c.issuer.rfc4514_string(),
            "not_after": c.not_valid_after_utc.isoformat(), "self_signed": c.subject == c.issuer,
            "san": names, "sha256": c.fingerprint(hashes.SHA256()).hex()}


class TlsCertificateStep(Step):
    category = "https"
    id = "https.certificate"
    title = "Certificado HTTPS do VYONIX"

    def __init__(self, data_dir: Path, pfx: str | None = None) -> None:
        self.dir = Path(data_dir) / "tls"
        self.cert = self.dir / "server.crt"
        self.key = self.dir / "server.key"
        self.pfx = pfx

    def desired(self, ctx: Context) -> dict:
        return {"cert": str(self.cert), "source": "instituição (.pfx)" if self.pfx else "autoassinado",
                "valid_for_days_min": RENEW_BEFORE.days, "hosts": [socket.gethostname(), "localhost", "127.0.0.1"]}

    def observe(self, ctx: Context) -> dict:
        info = cert_info(self.cert) if self.cert.exists() else None
        return {"cert": str(self.cert), "exists": info is not None, **(info or {}),
                "key_exists": self.key.exists()}

    def describe(self, ctx: Context) -> dict:
        return {"current": self.observe(ctx), "proposed": self.desired(ctx),
                "impact": ("Instala o certificado da instituição." if self.pfx else
                           "Gera um certificado autoassinado: os navegadores mostram aviso até ele ser trocado pelo "
                           "da instituição (pendência registrada no relatório)."),
                "undo": "Restaura o certificado anterior (guardado com sufixo .anterior)."}

    def check(self, ctx: Context) -> bool:
        o = self.observe(ctx)
        if not (o["exists"] and o["key_exists"]):
            return False
        if datetime.fromisoformat(o["not_after"]) - datetime.now(timezone.utc) < RENEW_BEFORE:
            return False
        if self.pfx and o.get("self_signed"):
            return False
        return True

    def capture(self, ctx: Context) -> dict:
        o = self.observe(ctx)
        return {"existed": o["exists"], "sha256": o.get("sha256")}

    def apply(self, ctx: Context) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        if self.cert.exists():                         # guarda o anterior (sem expor a chave em lugar nenhum)
            os.replace(self.cert, self.cert.with_suffix(".crt.anterior"))
            if self.key.exists():
                os.replace(self.key, self.key.with_suffix(".key.anterior"))
        if self.pfx:
            self._import_pfx(ctx)
        else:
            self._self_signed()
        try:
            os.chmod(self.key, 0o600)
        except OSError:
            pass

    def _self_signed(self) -> None:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
        k = ec.generate_private_key(ec.SECP256R1())
        host = socket.gethostname()
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"VYONIX {host}"),
                          x509.NameAttribute(NameOID.ORGANIZATION_NAME, "VYONIX (autoassinado)")])
        now = datetime.now(timezone.utc)
        alt = [x509.DNSName(host), x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
        try:
            fqdn = socket.getfqdn()
            if fqdn and fqdn != host:
                alt.append(x509.DNSName(fqdn))
        except OSError:
            pass
        c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
             .not_valid_after(now + timedelta(days=825))
             .add_extension(x509.SubjectAlternativeName(alt), critical=False)
             .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
             .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
             .sign(k, hashes.SHA256()))
        self.key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()))
        self.cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))

    def _import_pfx(self, ctx: Context) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.serialization import pkcs12
        pw = (ctx.extra.get("pfx_password") or "").encode() or None
        try:
            key, cert, chain = pkcs12.load_key_and_certificates(Path(self.pfx).read_bytes(), pw)
        except (OSError, ValueError) as exc:
            raise DeployError(f"Certificado .pfx ilegível ou senha incorreta: {exc}") from None
        if key is None or cert is None:
            raise DeployError("O .pfx não contém o certificado e a chave privada.")
        if cert.not_valid_after_utc - datetime.now(timezone.utc) < RENEW_BEFORE:
            raise DeployError("O certificado da instituição vence em menos de 30 dias.")
        if IS_WINDOWS:
            ok = powershell(r"""$c = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(,[Convert]::FromBase64String($A.der))
$ch = New-Object System.Security.Cryptography.X509Certificates.X509Chain
$ok = $ch.Build($c); [pscustomobject]@{ ok=$ok; status=@($ch.ChainStatus | ForEach-Object { [string]$_.StatusInformation }) }""",
                            {"der": base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()})
            if not ok.get("ok"):
                raise DeployError("A cadeia do certificado não é confiável neste Windows: "
                                  + "; ".join(x.strip() for x in (ok.get("status") or []) if x)[:400])
        pem = cert.public_bytes(serialization.Encoding.PEM) + b"".join(
            c.public_bytes(serialization.Encoding.PEM) for c in (chain or []))
        self.key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        self.cert.write_bytes(pem)

    def rollback(self, ctx: Context, before: dict) -> None:
        prev_c, prev_k = self.cert.with_suffix(".crt.anterior"), self.key.with_suffix(".key.anterior")
        if before.get("existed") and prev_c.exists():
            os.replace(prev_c, self.cert)
            if prev_k.exists():
                os.replace(prev_k, self.key)
        elif not before.get("existed"):
            for p in (self.cert, self.key):
                if p.exists():
                    p.unlink()

    def how_to_check(self) -> str:
        return f"certutil -dump \"{self.cert}\""
