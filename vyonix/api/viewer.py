"""Entrega do VYONIX VIEWER (OHIF 3.13, MIT) em ``/viewer/``, na mesma origem da API.

O pacote do OHIF é gerado pelo CI (``.github/workflows/viewer.yml``) com ``viewer/vyonix.js`` e fica em
``viewer/dist`` (desenvolvimento) ou ``<pacote>/viewer`` (instalado). Sem o pacote, ``/viewer/``
responde 404 com o motivo — nada de tela de fachada.

Política de conteúdo própria do Viewer: o OHIF usa web workers, WebAssembly (decodificadores) e
scripts embutidos no ``index.html``. Os scripts embutidos são liberados um a um pelo SHA-256 calculado
na partida (sem ``'unsafe-inline'`` para scripts); WebAssembly só com ``'wasm-unsafe-eval'``.
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

VIEWER_DIST = (Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "viewer" if getattr(sys, "frozen", False)
               else Path(__file__).resolve().parents[2] / "viewer" / "dist")
mimetypes.add_type("application/wasm", ".wasm")      # o Windows nem sempre conhece
mimetypes.add_type("text/javascript", ".mjs")
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def csp_for(index_html: str) -> str:
    hashes = sorted({"'sha256-" + base64.b64encode(hashlib.sha256(m.encode("utf-8")).digest()).decode() + "'"
                     for m in INLINE_SCRIPT.findall(index_html)})
    return ("default-src 'self'; script-src 'self' 'wasm-unsafe-eval' " + " ".join(hashes) + "; "
            "worker-src 'self' blob:; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "font-src 'self' data:; connect-src 'self'; manifest-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'")


def mount(app: FastAPI, dist: Path | None = None) -> bool:
    root = (dist or VIEWER_DIST)
    index = root / "index.html"
    if not index.exists():
        @app.get("/viewer/{path:path}", include_in_schema=False)
        def missing(path: str):
            return JSONResponse({"error": "not_found", "message": "VYONIX VIEWER não instalado neste servidor.",
                                 "details": {}}, status_code=404)
        return False
    root = root.resolve()
    csp = csp_for(index.read_text(encoding="utf-8"))
    headers = {"Content-Security-Policy": csp, "Cache-Control": "no-cache"}

    @app.get("/viewer", include_in_schema=False)
    @app.get("/viewer/{path:path}", include_in_schema=False)
    def viewer(path: str = ""):
        f = (root / path).resolve()
        if path and f.is_file() and root in f.parents:
            h = {"Content-Security-Policy": csp}
            if f.suffix in (".js", ".wasm", ".css", ".woff2", ".png", ".svg") and f.name not in (
                    "app-config.js", "sw.js", "init-service-worker.js"):
                h["Cache-Control"] = "public, max-age=86400"
            return FileResponse(f, headers=h)
        return FileResponse(index, headers=headers)        # rotas do próprio OHIF
    return True
