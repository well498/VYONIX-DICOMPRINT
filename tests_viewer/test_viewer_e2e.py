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


class OutageSwitch:
    """Interruptor de queda em volta do motor REAL (Orthanc): com ``down`` ligado, toda chamada falha como falharia
    com o motor parado. Só para o teste de falha de comunicação."""

    def __init__(self, real) -> None:
        self.real, self.down, self.name = real, False, real.name

    def __getattr__(self, attr):
        fn = getattr(self.real, attr)
        if not callable(fn):
            return fn

        def call(*a, **kw):
            if self.down:
                from vyonix.pacs.backend import BackendUnavailable
                raise BackendUnavailable("motor DICOM parado (teste de queda)")
            return fn(*a, **kw)
        return call


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
                                                       pixel_spacing=(0.5, 0.5),
                                                       patient_id=cls.patient_id, patient_name="VIEWER^SINTETICO"),
                            actor="teste")
            for i in range(1, 4):                              # segunda série: outro conteúdo (gradiente invertido)
                pacs.ingest(s, cls.backend, make_dicom(study=cls.study, series=uid(n, 7, 2), sop=uid(n, 7, 2, i),
                                                       rows=64, cols=64, fill=3000 - i * 400, instance_number=i,
                                                       series_number=2, pixel_spacing=(0.5, 0.5),
                                                       patient_id=cls.patient_id, patient_name="VIEWER^SINTETICO"),
                            actor="teste")
        # exame anterior do mesmo paciente (outra data e outro conteúdo) para a comparação lado a lado
        cls.prior = uid(n, 8)
        with db.session(cls.tenant) as s:
            for i in range(1, 4):
                pacs.ingest(s, cls.backend, make_dicom(study=cls.prior, series=uid(n, 8, 1), sop=uid(n, 8, 1, i),
                                                       rows=64, cols=64, fill=200 + i * 900, instance_number=i,
                                                       pixel_spacing=(0.5, 0.5), study_date="20250315",
                                                       description="Anterior sintético",
                                                       # outro PatientID DICOM só para não mudar o painel de séries
                                                       # dos outros testes; o vínculo é o paciente do cadastro
                                                       patient_id=cls.patient_id + "-A", patient_name="VIEWER^SINTETICO"),
                            actor="teste")
            from datetime import date as _date
            from vyonix.clinical import service as clinical
            pat = clinical.create_patient(s, name="Viewer Sintetico", identifiers=[("DICOM", cls.patient_id)],
                                          actor="teste")
            for su, d in ((cls.study, _date(2026, 10, 20)), (cls.prior, _date(2025, 3, 15))):
                st = clinical.register_study(s, study_instance_uid=su, modality="CT", study_date=d, actor="teste")
                st.patient_id = pat.id
        cfg = Config(data_dir=cls.tmp / "data", default_organization=cls.code)
        cfg.data_dir.mkdir(parents=True)
        plat = build(cfg, licensing=lic, db=db)
        cls.switch = OutageSwitch(cls.backend)
        plat.options["pacs_backend"] = cls.switch
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
        # O tour guiado do OHIF fica desligado na configuração do VYONIX (viewer/vyonix.js)
        self.assertEqual(page.locator(".shepherd-modal-is-visible, .shepherd-element").count(), 0,
                         "o tour guiado do OHIF apareceu (deveria estar desligado em viewer/vyonix.js)")
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

        # Ferramentas básicas (sem validação clínica): cada ação deve mudar o que está desenhado
        self.check_tools(page, canvas)

        # Auditoria da abertura e política de conteúdo
        from vyonix.audit import service as audit
        with db.session(self.tenant) as s:
            self.assertTrue(audit.query(s, action="pacs.study.open"))
        self.assertEqual([p for p in problems if "Content Security Policy" in p], [], problems)

    def session_page(self):
        ctx = self.browser.new_context(ignore_https_errors=True, viewport={"width": 1600, "height": 900})
        self.addCleanup(ctx.close)
        self.diag = []
        page = ctx.new_page()
        page.on("console", lambda m: self.diag.append(f"console.{m.type}: {m.text[:300]}")
                if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: self.diag.append(f"pageerror: {str(e)[:300]}"))
        page.on("response", lambda r: self.diag.append(f"HTTP {r.status} {r.request.method} {r.url[:200]}")
                if r.status >= 400 else None)
        r = ctx.request.post(self.base + "/api/v1/auth/login", data={"username": "admin", "password": ADMIN_PW})
        self.assertEqual(r.status, 200, r.text())
        self.page = page
        return page

    def open_study(self, page):
        page.goto(f"{self.base}/viewer/viewer?StudyInstanceUIDs={self.study}", wait_until="domcontentloaded")
        canvas = page.locator("canvas.cornerstone-canvas").first
        self.wait(canvas, "viewport do estudo", 90000)
        page.wait_for_function("""() => {
            const c = document.querySelector('canvas.cornerstone-canvas');
            return c && c.width > 0 && c.height > 0;
        }""", timeout=60000)
        page.wait_for_timeout(3000)
        return canvas

    def test_multi_series_navigation(self):
        """Estudo com duas séries: o painel lista as duas; carregar cada série muda o viewport."""
        page = self.session_page()
        canvas = self.open_study(page)
        thumbs = page.locator('[data-cy="study-browser-thumbnail"], [data-cy="study-browser-thumbnail-no-image"]')
        self.wait(thumbs.nth(1), "duas séries no painel do estudo")
        self.assertEqual(thumbs.count(), 2)
        series1 = canvas.screenshot()
        page.locator('[data-series="2"]').first.dblclick()
        page.wait_for_timeout(3000)
        series2 = canvas.screenshot()
        self.assertNotEqual(series1, series2, "carregar a série 2 não mudou o viewport")
        self.assertGreater(self.distinct_levels(series2), 4, "série 2 sem imagem desenhada")
        page.locator('[data-series="1"]').first.dblclick()
        page.wait_for_timeout(3000)
        self.assertNotEqual(canvas.screenshot(), series2, "voltar para a série 1 não mudou o viewport")
        self.shot(page, "duas-series")

    def test_compare_current_and_prior_side_by_side(self):
        """Lançador do VYONIX com o protocolo de comparação: atual e anterior do mesmo paciente lado a lado
        (``@ohif/hpCompare``), cada quadro com imagem desenhada e identificação (data, modalidade e exame)."""
        page = self.session_page()
        r = page.context.request.get(self.base + "/api/v1/pacs/viewer/launch",
                                     params={"study_uid": self.study, "layout": "compare"})
        self.assertEqual(r.status, 200, r.text())
        d = r.json()
        self.assertEqual((d["layout"], d["prior"]["study_instance_uid"]), ("compare", self.prior))
        page.goto(self.base + d["url"], wait_until="domcontentloaded")
        page.wait_for_function("""() => {
            const cs = [...document.querySelectorAll('canvas.cornerstone-canvas')];
            return cs.length >= 2 && cs.every(c => c.width > 0 && c.height > 0);
        }""", timeout=90000)
        page.wait_for_timeout(4000)
        canvases = page.locator("canvas.cornerstone-canvas")
        self.assertGreaterEqual(canvases.count(), 2, "comparação sem dois quadros")
        left, right = canvases.nth(0).screenshot(), canvases.nth(1).screenshot()
        for png, what in ((left, "atual"), (right, "anterior")):
            self.assertGreater(self.distinct_levels(png), 4, f"quadro {what} sem imagem desenhada")
        self.assertNotEqual(left, right, "os dois quadros mostram a mesma imagem")
        body = page.locator("body").inner_text()
        for want in ("Estudo sintético", "Anterior sintético"):                # identificação do exame (vyonix.js)
            self.assertIn(want, body, f"identificação “{want}” ausente nos quadros")
        self.shot(page, "comparacao")

    def test_engine_outage_and_recovery(self):
        """Motor parado: a lista de estudos continua (vem do índice); abrir o estudo recebe 503 sem quebrar a página;
        motor de volta: o estudo abre e a imagem é desenhada."""
        page = self.session_page()
        self.switch.down = True
        try:
            page.goto(self.base + "/viewer/", wait_until="domcontentloaded")
            self.wait(page.get_by_text(self.patient_id, exact=False).first, "lista de estudos com o motor parado")
            statuses = []
            page.on("response", lambda r: statuses.append(r.status) if "/metadata" in r.url else None)
            page.goto(f"{self.base}/viewer/viewer?StudyInstanceUIDs={self.study}", wait_until="domcontentloaded")
            for _ in range(60):
                if 503 in statuses:
                    break
                page.wait_for_timeout(500)
            self.assertIn(503, statuses, "metadados com o motor parado deveriam responder 503")
            # a página continua de pé (erros internos do OHIF ficam no diagnóstico; o código do OHIF não é alterado)
            self.assertGreater(page.evaluate("document.querySelector('#root')?.childElementCount ?? 0"), 0,
                               "o Viewer deixou de ser exibido com o motor parado\n" + "\n".join(self.diag[-20:]))
            self.shot(page, "motor-parado")
        finally:
            self.switch.down = False
        page.reload(wait_until="domcontentloaded")
        canvas = self.open_study(page)
        self.assertGreater(self.distinct_levels(canvas.screenshot()), 4, "sem imagem depois da volta do motor")
        self.shot(page, "motor-de-volta")

    def drag(self, page, canvas, dx: int, dy: int) -> None:
        b = canvas.bounding_box()
        x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        for k in range(1, 11):
            page.mouse.move(x + dx * k / 10, y + dy * k / 10)
        page.mouse.up()
        page.wait_for_timeout(800)

    def tool(self, page, names: list[str]):
        """Botão da barra do OHIF pelo ``data-cy`` (nomes da versão 3.x); falha com a lista do que existe."""
        for n in names:
            loc = page.locator(f'[data-cy="{n}"]').first
            if loc.count():
                return loc
        found = page.eval_on_selector_all("[data-cy]", "els => els.map(e => e.getAttribute('data-cy'))")
        self.fail(f"Botão {names} não encontrado na barra do Viewer. data-cy disponíveis: {sorted(set(found))[:80]}")

    def check_tools(self, page, canvas) -> None:
        steps = []
        before = canvas.screenshot()
        self.drag(page, canvas, 120, 60)                               # janela/nível: ferramenta padrão
        after = canvas.screenshot()
        self.assertNotEqual(before, after, "arrastar com a ferramenta padrão (janela/nível) não mudou a imagem")
        steps.append("janela/nível")
        self.tool(page, ["Zoom"]).click()
        before = canvas.screenshot()
        self.drag(page, canvas, 0, -120)
        after = canvas.screenshot()
        self.assertNotEqual(before, after, "zoom não mudou a imagem")
        steps.append("zoom")
        for item, label in (("invert", "inverter"), ("rotate-right", "girar")):
            # "Mais ferramentas" (OHIF 3.13: seção MoreTools do toolbarButtonsCustomization)
            before = canvas.screenshot()                              # antes de abrir o menu (que pode cobrir a imagem)
            self.tool(page, ["MoreTools-split-button-secondary"]).click()
            self.tool(page, [item]).click()
            page.keyboard.press("Escape")                             # garante o menu fechado antes de comparar
            page.mouse.move(1, 1)
            page.wait_for_timeout(800)
            self.assertNotEqual(before, canvas.screenshot(), f"{label} não mudou a imagem")
            steps.append(label)
        self.check_length(page, canvas)
        steps.append("medição de distância")
        self.shot(page, "ferramentas")
        self.tools_checked = steps

    def check_length(self, page, canvas) -> None:
        """Medição de distância (Length, ferramenta principal de MeasurementTools no OHIF 3.13). As imagens têm
        Pixel Spacing de 0,5 mm; o painel de medições deve mostrar o valor em mm."""
        import re
        mm = re.compile(r"\d+(?:[.,]\d+)?\s*mm")
        before = page.get_by_text(mm).count()
        self.tool(page, ["MeasurementTools-split-button-primary", "Length"]).click()
        b = canvas.bounding_box()
        x0, y0 = b["x"] + b["width"] * 0.35, b["y"] + b["height"] * 0.5
        page.mouse.click(x0, y0)
        page.mouse.click(x0 + b["width"] * 0.3, y0)
        page.wait_for_timeout(1000)
        # Modo padrão (longitudinal): a primeira medição pergunta se a série deve ser acompanhada
        prompt = page.get_by_role("button", name="Yes")
        if prompt.count():
            prompt.first.click()
            page.wait_for_timeout(1000)
        deadline = 30
        while page.get_by_text(mm).count() <= before and deadline:
            page.wait_for_timeout(1000)
            deadline -= 1
        if page.get_by_text(mm).count() <= before:
            self.wait(page.locator("text=__nunca__"), "valor da medição em mm (nenhum novo valor apareceu)", 1000)
        # o rótulo da medição sobre a imagem é <text> de SVG: innerText vem nulo, textContent não
        values = [t for t in (loc.text_content() for loc in page.get_by_text(mm).all()) if t]
        # 30 % da largura do viewport, 64 px de imagem com 0,5 mm: valor positivo e plausível (até 32 mm)
        nums = [float(m.replace(",", ".")) for t in values for m in re.findall(r"(\d+(?:[.,]\d+)?)\s*mm", t)]
        self.assertTrue(any(0 < n <= 32.5 for n in nums), f"valores medidos: {values}")

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
