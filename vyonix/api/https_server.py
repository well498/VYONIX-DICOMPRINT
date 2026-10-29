"""Servidor HTTPS do Core com redirecionamento de ``http://`` na **mesma porta**.

Relato da homologação (28/10/2026): quem digita ``http://IP:8444`` num servidor só HTTPS recebe "página não
encontrada" ou "conexão redefinida" — parece que o sistema não iniciou. Aqui cada conexão nova é inspecionada no
primeiro byte: handshake TLS (``0x16``) segue para o HTTPS normal do uvicorn; qualquer outra coisa recebe um
``301`` para ``https://<mesmo host>:<porta><caminho>`` e a conexão é encerrada. Nenhum dado é atendido sem TLS.

Usa a mesma pilha do uvicorn (protocolo HTTP e aplicativo inalterados); só a camada TLS passa a ser ligada por
conexão (``asyncio.sslproto.SSLProtocol``), em vez de pelo ``create_server``.
"""

from __future__ import annotations

import asyncio
import re
from asyncio import sslproto

TLS_HANDSHAKE = 0x16
HOST_RE = re.compile(r"^[A-Za-z0-9.\-]{1,253}$|^\[[0-9A-Fa-f:.]{2,45}\]$")
MAX_HEAD = 8192


class _Sniff(asyncio.Protocol):
    def __init__(self, loop, sslctx, make_app, port: int) -> None:
        self.loop, self.sslctx, self.make_app, self.port = loop, sslctx, make_app, port
        self.buf = b""
        self.t = None
        self.decided = False

    def connection_made(self, transport) -> None:
        self.t = transport

    def data_received(self, data: bytes) -> None:
        if self.decided:
            return
        self.buf += data
        if self.buf[0] == TLS_HANDSHAKE:
            self.decided = True
            try:
                self._tls()
            except Exception:  # noqa: BLE001 - falha ao ligar o TLS: encerra só esta conexão
                if self.t is not None:
                    self.t.abort()
        elif b"\r\n\r\n" in self.buf or len(self.buf) >= MAX_HEAD:
            self.decided = True
            self._redirect()

    def eof_received(self):
        return False

    def connection_lost(self, exc) -> None:
        self.t = None

    def _tls(self) -> None:
        app = self.make_app()
        sp = sslproto.SSLProtocol(self.loop, app, self.sslctx, None, server_side=True, ssl_handshake_timeout=60)
        self.t.set_protocol(sp)
        sp.connection_made(self.t)
        mv, self.buf = memoryview(self.buf), b""
        while len(mv):
            b = sp.get_buffer(len(mv))
            n = min(len(b), len(mv))
            b[:n] = mv[:n]
            sp.buffer_updated(n)
            mv = mv[n:]

    def _redirect(self) -> None:
        host, path = "localhost", "/"
        try:
            head = self.buf.split(b"\r\n\r\n", 1)[0].decode("latin-1")
            lines = head.split("\r\n")
            parts = lines[0].split(" ")
            if len(parts) == 3 and parts[1].startswith("/") and len(parts[1]) <= 2048 \
                    and not any(c in parts[1] for c in "\r\n\t "):
                path = parts[1]
            for ln in lines[1:]:
                k, _, v = ln.partition(":")
                if k.strip().lower() == "host":
                    h = v.strip()
                    h = h.rsplit(":", 1)[0] if not h.startswith("[") else h.split("]")[0] + "]"
                    if HOST_RE.match(h):
                        host = h
        except Exception:  # noqa: BLE001 - pedido malformado: manda para a raiz
            pass
        loc = f"https://{host}:{self.port}{path}"
        body = (f"<!doctype html><meta charset=utf-8><title>VYONIX</title><p>O VYONIX usa conexão segura. "
                f"Abra <a href=\"{loc}\">{loc}</a>.</p>").encode("utf-8")
        head = (f"HTTP/1.1 301 Moved Permanently\r\nLocation: {loc}\r\nContent-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n").encode("latin-1")
        try:
            self.t.write(head + body)
            self.t.close()
        except Exception:  # noqa: BLE001
            pass


def make_server(app, *, host: str, port: int, certfile: str, keyfile: str, redirect: bool = True, **kw):
    """``uvicorn.Server`` HTTPS que também redireciona ``http://`` da mesma porta para ``https://``.

    ``redirect=False`` (configuração ``http_redirect: false``) volta ao HTTPS puro do uvicorn."""
    import uvicorn
    cfg = uvicorn.Config(app, host=host, port=port, ssl_certfile=certfile, ssl_keyfile=keyfile, **kw)
    if not redirect:
        return uvicorn.Server(cfg)
    cfg.load()
    sslctx, real = cfg.ssl, cfg.http_protocol_class
    cfg.ssl = None                                             # TLS ligado por conexão em _Sniff

    def factory(config, server_state, app_state, _loop=None):
        loop = _loop or asyncio.get_event_loop()
        return _Sniff(loop, sslctx, lambda: real(config=config, server_state=server_state, app_state=app_state,
                                                 _loop=_loop), port)
    cfg.http_protocol_class = factory
    return uvicorn.Server(cfg)
