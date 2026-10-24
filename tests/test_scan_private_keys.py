"""Varredura de chaves privadas nos pacotes: acusa chave privada em qualquer formato e não acusa um
arquivo de certificados públicos (ex.: ``certifi/cacert.pem``)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import scan_private_keys as scan  # noqa: E402


class ScanPrivateKeys(unittest.TestCase):
    def check(self, name, data: bytes) -> int:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / name).write_bytes(data)
            return scan.main([d])

    def test_detects_private_keys(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
        pem = ed25519.Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        self.assertEqual(self.check("chave.bin", b"lixo" + pem), 1)            # embutida em outro arquivo
        self.assertEqual(self.check("x.pem", pem), 1)
        self.assertEqual(self.check("x.key", b"qualquer coisa"), 1)             # .key sempre acusa
        self.assertEqual(self.check("x.pem", b"-----BEGIN ENCRYPTED PRIVATE KEY-----\nAA"), 1)
        self.assertEqual(self.check("x.pem", b"conteudo desconhecido"), 1)      # .pem sem certificado

    def test_public_ca_bundle_is_not_a_key(self):
        cert = (b"# Issuer: CN=Teste\n-----BEGIN CERTIFICATE-----\n" + b"A" * 64 + b"\n-----END CERTIFICATE-----\n") * 3
        self.assertEqual(self.check("cacert.pem", cert), 0)
        self.assertEqual(self.check("leia.txt", b"sem chave"), 0)


if __name__ == "__main__":
    unittest.main()
