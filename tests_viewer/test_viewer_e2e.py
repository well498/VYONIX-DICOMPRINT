"""Ponta a ponta do VYONIX VIEWER: OHIF 3.13 compilado (``viewer/dist``), CORE em HTTPS (uvicorn),
PostgreSQL real, Orthanc real e Chromium (Playwright).

Fluxo: estudo sintético de 5 imagens enviado ao PACS → lista de estudos do Viewer (QIDO-RS) → estudo
aberto (metadados e frames WADO-RS) → imagem desenhada → navegação para outra imagem → abertura
registrada na auditoria → nenhuma violação da política de conteúdo.

Roda só no CI ``viewer.yml`` (que falha se algum teste for pulado). Sem os pré-requisitos é pulado com
motivo. Dados sintéticos; não é validação clínica do Viewer.
"""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tests_platform.pacs_support import make_dicom, uid
from tests_platform.support import ADMIN_PW, new_org, require_db

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "viewer" / "dist"
SHOTS = Path(os.environ["VYONIX_E2E_SHOTS"]) if os.environ.get("VYONIX_E2E_SHOTS") else None
URL = os.environ.get("VYONIX_TEST_ORTHANC_URL", "")


def setUpModule():
    global db
    if not (DIST / "index.html").exists():
        raise unittest.SkipTest("viewer/dist ausente (o OHIF é compilado pelo CI viewer.yml).")
    if not URL:
        raise unittest.SkipTest("VYONIX_TEST_ORTHANC_URL não definida (Orthanc de teste).")
    db = require_db()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ViewerE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uvicorn
        from tests.licensing_support import Computer, make_manager
        from tests_platform.test_licensing import Base
        from vyonix.api.app import create_app
        from vyonix.cli import ensure_tls
        from vyonix.config import Config
        from vyonix.context import build
        from vyonix.modules import registry
        from vyonix.pacs import service as pacs
        from vyonix.pacs.orthanc import OrthancBackend
        cls.tmp = Path(tempfile.mkdtemp(prefix="vyx-viewer-"))
        cls.pc = Computer()
        lm, lm_admin, keys, cid = make_manager(cls.tmp / "lm", clock=lambda: cls.pc.clock.wall)
        cls.lm = lm
        helper = Base.__new__(Base)
        helper.keys, helper.lm, helper.admin, helper.cid = keys, lm, lm_admin, cid
        lic = helper.licensing(cls.pc)
        helper.lic = lic
        cls.code = f"viewer-{int(time.time())}"
        cls.tenant = new_org(db, cls.code)
        doc = helper.issue("annual", modules={"core": {"kind": "contract"}, "pacs": {"kind": "contract"}})
        with db.session(cls.tenant) as s:
            lic.install(s, doc["document"], actor="admin")
            registry.enable(s, "pacs", actor="admin", license_check=lic.module_ok)
        cls.backend = OrthancBackend(URL, username=os.environ.get("VYONIX_TEST_ORTHANC_USER"),
                                     password=os.environ.get("VYONIX_TEST_ORTHANC_PASSWORD"))
        n = int(time.time()) % 10**8
        cls.study = uid(n, 7)
        cls.patient_id = f"VYX-E2E-{n}"
        with db.session(cls.tenant) as s:
            for i in range(1, 6):
                pacs.ingest(s, cls.backend, make_dicom(study=cls.study, series=uid(n, 7, 1), sop=uid(n, 7, 1, i),
                                                       rows=64, cols=64, fill=i * 600, instance_number=i,
                                                       patient_id=cls.patient_id, patient_name="VIEWER^SINTETICO"),
                            actor="teste")
        cfg = Config(data_dir=cls.tmp / "data", default_organization=cls.code)
        cfg.data_dir.mkdir(parents=True)
        plat = build(cfg, licensing=lic, db=db)
        plat.options["pacs_backend"] = cls.backend
        cert, key = ensure_tls(cfg)
        cls.port = free_port()
        cls.server = uvicorn.Server(uvicorn.Config(create_app(plat, viewer_dist=DIST), host="127.0.0.1",
                                                   port=cls.port, ssl_certfile=cert, ssl_keyfile=key,
                                                   log_level="warning"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.1)
        cls.base = f"https://127.0.0.1:{cls.port}"
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.should_exit = True
        cls.thread.join(10)
        cls.backend.close()
        cls.lm.close()
        shutil.rmtree(cls.tmp, True)

    def shot(self, page, name):
        if SHOTS:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / f"viewer-{name}.png"))

    def test_open_study_render_and_navigate(self):
        ctx = self.browser.new_context(ignore_https_errors=True, viewport={"width": 1600, "height": 900})
        self.addCleanup(ctx.close)
        problems: list[str] = []
        self.diag: list[str] = []
        page = ctx.new_page()
        page.on("console", lambda m: (problems.append(m.text) if "Content Security Policy" in m.text else None,
                                      self.diag.append(f"console.{m.type}: {m.text[:300]}")
                                      if m.type in ("error", "warning") else None))
        page.on("pageerror", lambda e: self.diag.append(f"pageerror: {str(e)[:300]}"))
        page.on("response", lambda r: self.diag.append(f"HTTP {r.status} {r.request.method} {r.url[:200]}")
                if r.status >= 400 else None)
        page.on("requestfailed", lambda r: self.diag.append(f"falhou {r.method} {r.url[:200]}: {r.failure}"))
        self.page = page
        r = ctx.request.post(self.base + "/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PW})
        self.assertEqual(r.status, 200, r.text())

        # Sem sessão, a API recusa (o Viewer não abre dados de imagem sem login)
        anon = self.browser.new_context(ignore_https_errors=True)
        self.addCleanup(anon.close)
        self.assertEqual(anon.request.get(self.base + "/api/v1/pacs/dicomweb/studies").status, 401)

        # Lista de estudos (QIDO-RS)
        page.goto(self.base + "/viewer/", wait_until="domcontentloaded")
        self.wait(page.get_by_text(self.patient_id, exact=False).first, "lista de estudos com o paciente sintético")
        self.shot(page, "lista")

        # Estudo aberto: imagem desenhada no viewport
        page.goto(f"{self.base}/viewer/viewer?StudyInstanceUIDs={self.study}", wait_until="domcontentloaded")
        canvas = page.locator("canvas.cornerstone-canvas").first
        self.wait(canvas, "viewport do estudo", 90000)
        page.wait_for_function("""() => {
            const c = document.querySelector('canvas.cornerstone-canvas');
            return c && c.width > 0 && c.height > 0;
        }""", timeout=60000)
        page.wait_for_timeout(3000)
        before = canvas.screenshot()
        self.assertGreater(self.distinct_levels(before), 4, "viewport sem imagem desenhada")
        self.shot(page, "estudo")

        # Navegação: rolar para a imagem seguinte muda o que está desenhado
        canvas.hover()
        for _ in range(3):
            page.mouse.wheel(0, 120)
            page.wait_for_timeout(400)
        page.wait_for_timeout(1500)
        after = canvas.screenshot()
        self.assertNotEqual(before, after, "a navegação entre imagens não mudou o viewport")
        self.shot(page, "navegacao")

        # Auditoria da abertura e política de conteúdo
        from vyonix.audit import service as audit
        with db.session(self.tenant) as s:
            self.assertTrue(audit.query(s, action="pacs.study.open"))
        self.assertEqual([p for p in problems if "Content Security Policy" in p], [], problems)

    def wait(self, locator, what: str, timeout: int = 60000) -> None:
        from playwright.sync_api import TimeoutError as PwTimeout
        try:
            locator.wait_for(timeout=timeout)
        except PwTimeout:
            self.shot(self.page, "falha")
            try:
                text = self.page.inner_text("body")[:1500]
            except Exception as exc:  # noqa: BLE001
                text = f"(sem texto: {exc})"
            self.fail(f"Não apareceu: {what}. URL: {self.page.url}\nTexto visível: {text!r}\n"
                      "Diagnóstico do navegador:\n" + "\n".join(self.diag[-40:]))

    @staticmethod
    def distinct_levels(png: bytes) -> int:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(png)).convert("L")
        return len(set(im.getdata()))


if __name__ == "__main__":
    unittest.main()
