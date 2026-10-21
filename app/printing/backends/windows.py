"""Impressoras do Windows via spooler e GDI (pywin32).

* Lista impressoras locais e de rede com driver, porta, formatos, resoluções e cor.
* Configura o DEVMODE do trabalho (papel, orientação, cópias, agrupamento) sem alterar as
  preferências da impressora para outros programas.
* Desenha cada página em escala física: a página montada cobre o papel inteiro e é posicionada
  descontando a margem física não imprimível (PHYSICALOFFSET), de modo que 10 cm no layout
  correspondam a 10 cm no papel (antes da calibração geométrica, que corrige o restante).
* Impressoras cuja porta pediria um nome de arquivo (``PORTPROMPT:``/``FILE:``, ex.:
  "Microsoft Print to PDF") recebem um caminho automático — **nunca** se abre diálogo, o que
  travaria um serviço Windows (Fase 7).
* Envio aceito pelo spooler ≠ papel impresso: o trabalho fica "Enviado" e só é concluído se o
  spooler informar ``JOB_STATUS_PRINTED``/``COMPLETE`` (consulta posterior por ``job_status``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.core.contracts import PrinterInfo, SpoolRequest, SpoolResult, SpoolStatus
from app.printing.paper import DMPAPER
from app.printing.backends.pdf import safe_filename
from app.utils.logging_setup import get_logger

log = get_logger("printing.windows")

# wingdi.h / winspool.h
DC_PAPERS, DC_PAPERNAMES, DC_ENUMRESOLUTIONS, DC_COPIES, DC_COLORDEVICE = 2, 16, 13, 18, 32
PHYSICALWIDTH, PHYSICALHEIGHT, PHYSICALOFFSETX, PHYSICALOFFSETY = 110, 111, 112, 113
LOGPIXELSX, LOGPIXELSY = 88, 90
DM_ORIENTATION, DM_PAPERSIZE, DM_PAPERLENGTH, DM_PAPERWIDTH = 0x1, 0x2, 0x4, 0x8
DM_COPIES, DM_COLLATE = 0x100, 0x8000
DM_IN_BUFFER, DM_OUT_BUFFER = 8, 2
PRINTER_ENUM_LOCAL, PRINTER_ENUM_CONNECTIONS = 2, 4

JOB_STATUS = {0x1: "pausado", 0x2: "erro", 0x4: "sendo excluído", 0x8: "em spool", 0x10: "imprimindo",
              0x20: "impressora offline", 0x40: "sem papel", 0x80: "impresso", 0x100: "excluído",
              0x200: "fila bloqueada", 0x400: "requer intervenção do usuário", 0x800: "reiniciando",
              0x1000: "concluído"}
PRINTER_STATUS = {0x1: "pausada", 0x2: "erro", 0x8: "papel atolado", 0x10: "sem papel",
                  0x40: "problema de papel", 0x80: "offline", 0x400: "imprimindo", 0x1000: "não disponível",
                  0x4000: "sem toner", 0x100000: "intervenção necessária", 0x400000: "porta aberta"}
FILE_PORTS = ("PORTPROMPT:", "FILE:")


def available() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "impressão Windows disponível apenas no Windows"
    try:
        import win32print  # noqa: F401
        import win32ui  # noqa: F401
        import win32gui  # noqa: F401
    except ImportError as exc:
        return False, f"pywin32 indisponível: {exc}"
    return True, ""


def _flags_text(value: int, table: dict[int, str]) -> str:
    return ", ".join(t for bit, t in table.items() if value & bit)


class WindowsPrinterBackend:
    name = "windows"

    def __init__(self, auto_output_dir: Path) -> None:
        self.auto_output_dir = Path(auto_output_dir)

    # ---------------------------------------------------------------- consulta
    def list_printers(self) -> list[PrinterInfo]:
        import win32print
        try:
            default = win32print.GetDefaultPrinter()
        except Exception:  # noqa: BLE001 - nenhuma impressora padrão
            default = ""
        result = []
        for _flags, _desc, name, _comment in win32print.EnumPrinters(PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS,
                                                                     None, 1):
            try:
                result.append(self._info(name, default))
            except Exception as exc:  # noqa: BLE001 - impressora de rede inacessível, driver quebrado…
                log.warning("Impressora %s inacessível: %s", name, exc)
                result.append(PrinterInfo(name=name, driver="?", is_default=name == default, paper_sizes=(),
                                          resolutions_dpi=(), supports_color=None,
                                          status_text=f"inacessível: {exc}", available=False))
        return result

    def _info(self, name: str, default: str) -> PrinterInfo:
        import win32print
        h = win32print.OpenPrinter(name)
        try:
            info = win32print.GetPrinter(h, 2)
        finally:
            win32print.ClosePrinter(h)
        port = info.get("pPortName") or ""
        papers: list[str] = []
        res: list[int] = []
        color = None
        try:
            names = win32print.DeviceCapabilities(name, port, DC_PAPERNAMES)
            papers = [str(n).strip("\x00 ") for n in names if str(n).strip("\x00 ")]
            res = sorted({int(r["xdpi"] if isinstance(r, dict) else r[0])
                          for r in win32print.DeviceCapabilities(name, port, DC_ENUMRESOLUTIONS) or []})
            color = bool(win32print.DeviceCapabilities(name, port, DC_COLORDEVICE))
        except Exception as exc:  # noqa: BLE001 - alguns drivers não respondem a todas as consultas
            log.info("Capacidades parciais de %s: %s", name, exc)
        status = _flags_text(int(info.get("Status") or 0), PRINTER_STATUS) or "pronta"
        jobs = int(info.get("cJobs") or 0)
        if jobs:
            status += f" · {jobs} trabalho(s) na fila"
        return PrinterInfo(name=name, driver=info.get("pDriverName") or "", is_default=name == default,
                           paper_sizes=tuple(papers), resolutions_dpi=tuple(r for r in res if r > 0),
                           supports_color=color, status_text=status, backend=self.name, port=port)

    # ---------------------------------------------------------------- envio
    def submit(self, request: SpoolRequest) -> SpoolResult:
        import pywintypes
        import win32con
        import win32gui
        import win32print
        import win32ui
        from PIL import Image, ImageWin

        hprinter = None
        dc = None
        try:
            hprinter = win32print.OpenPrinter(request.printer)
            info = win32print.GetPrinter(hprinter, 2)
            port = (info.get("pPortName") or "").upper()
            devmode = info.get("pDevMode")
            if devmode is None:   # sem DEVMODE por impressora: usa o padrão global (nível 8)
                try:
                    devmode = win32print.GetPrinter(hprinter, 8).get("pDevMode")
                except Exception:  # noqa: BLE001
                    devmode = None
            copies_by_driver = 1
            if devmode is not None:
                code = DMPAPER.get(request.paper)
                if code:
                    devmode.PaperSize = code
                    devmode.Fields |= DM_PAPERSIZE
                else:   # formato de filme/personalizado: dimensões em décimos de mm
                    devmode.PaperSize = 0
                    devmode.PaperWidth = round(min(request.width_mm, request.height_mm) * 10)
                    devmode.PaperLength = round(max(request.width_mm, request.height_mm) * 10)
                    devmode.Fields |= DM_PAPERWIDTH | DM_PAPERLENGTH
                devmode.Orientation = 2 if request.orientation == "landscape" else 1
                devmode.Fields |= DM_ORIENTATION
                max_copies = 1
                try:
                    max_copies = int(win32print.DeviceCapabilities(request.printer, info.get("pPortName") or "",
                                                                   DC_COPIES) or 1)
                except Exception:  # noqa: BLE001
                    pass
                if max_copies >= request.copies > 1:
                    devmode.Copies = request.copies
                    devmode.Collate = 1
                    devmode.Fields |= DM_COPIES | DM_COLLATE
                    copies_by_driver = request.copies
                win32print.DocumentProperties(0, hprinter, request.printer, devmode, devmode,
                                              DM_IN_BUFFER | DM_OUT_BUFFER)
            hdc = win32gui.CreateDC("WINSPOOL", request.printer, devmode)
            dc = win32ui.CreateDCFromHandle(hdc)
            output = None
            if any(port.startswith(p) for p in FILE_PORTS) or "PRINT TO PDF" in (info.get("pDriverName") or "").upper():
                self.auto_output_dir.mkdir(parents=True, exist_ok=True)
                output = str(self.auto_output_dir / f"{safe_filename(request.document_name)}.pdf")
            job_id = dc.StartDoc(request.document_name, output) if output else dc.StartDoc(request.document_name)
            phys_w, phys_h = dc.GetDeviceCaps(PHYSICALWIDTH), dc.GetDeviceCaps(PHYSICALHEIGHT)
            off_x, off_y = dc.GetDeviceCaps(PHYSICALOFFSETX), dc.GetDeviceCaps(PHYSICALOFFSETY)
            dpi_x, dpi_y = dc.GetDeviceCaps(LOGPIXELSX), dc.GetDeviceCaps(LOGPIXELSY)
            # Dimensões da página montada (já orientada) em pixels do dispositivo:
            target_w = round(request.width_mm / 25.4 * dpi_x)
            target_h = round(request.height_mm / 25.4 * dpi_y)
            mismatch = abs(target_w - phys_w) > dpi_x * 0.12 or abs(target_h - phys_h) > dpi_y * 0.12
            pages = 0
            repeats = max(1, request.copies // copies_by_driver)
            for _ in range(repeats):
                for page in request.pages():
                    img = Image.fromarray(page.pixels)
                    if img.mode not in ("L", "RGB"):
                        img = img.convert("RGB")
                    dc.StartPage()
                    ImageWin.Dib(img).draw(dc.GetHandleOutput(), (-off_x, -off_y, target_w - off_x, target_h - off_y))
                    dc.EndPage()
                    pages += 1
                    del img
            dc.EndDoc()
            detail = (f"{pages} página(s) enviada(s) ao spooler · {dpi_x} dpi no driver · "
                      f"área física {phys_w}×{phys_h} px")
            if mismatch:
                detail += (" · ATENÇÃO: o papel configurado no driver difere do solicitado "
                           f"({request.paper}); verifique o formato na impressora")
            if output:
                detail += f" · arquivo: {output}"
            return SpoolResult(accepted=True, spool_job_id=int(job_id) if job_id and int(job_id) > 0 else None,
                               confirmed=False, output_path=output, detail=detail)
        except pywintypes.error as exc:
            msg = f"{exc.strerror} (código {exc.winerror})" if hasattr(exc, "winerror") else str(exc)
            log.error("Falha no spooler: %s", msg)
            if dc is not None:
                try:
                    dc.AbortDoc()
                except Exception:  # noqa: BLE001
                    pass
            return SpoolResult(accepted=False, spool_job_id=None, error=f"Spooler do Windows: {msg}")
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha ao imprimir")
            if dc is not None:
                try:
                    dc.AbortDoc()
                except Exception:  # noqa: BLE001
                    pass
            return SpoolResult(accepted=False, spool_job_id=None, error=f"Falha ao imprimir: {exc}")
        finally:
            if dc is not None:
                try:
                    dc.DeleteDC()
                except Exception:  # noqa: BLE001
                    pass
            if hprinter is not None:
                win32print.ClosePrinter(hprinter)
            _ = win32con  # importado para garantir que o PyInstaller inclua o módulo

    def job_status(self, printer: str, spool_job_id: int) -> SpoolStatus:
        import pywintypes
        import win32print
        try:
            h = win32print.OpenPrinter(printer)
        except pywintypes.error as exc:
            return SpoolStatus("unknown", f"impressora inacessível: {exc.strerror}")
        try:
            job = win32print.GetJob(h, spool_job_id, 1)
        except pywintypes.error:
            return SpoolStatus("gone", "o trabalho saiu da fila do Windows")
        finally:
            win32print.ClosePrinter(h)
        st = int(job.get("Status") or 0)
        text = _flags_text(st, JOB_STATUS) or "na fila"
        if st & 0x100 or st & 0x4:
            return SpoolStatus("deleted", text)
        if st & 0x80 or st & 0x1000:
            return SpoolStatus("printed", text)
        if st & (0x2 | 0x20 | 0x40 | 0x200 | 0x400):
            return SpoolStatus("error", text)
        if st & 0x10:
            return SpoolStatus("printing", text)
        return SpoolStatus("queued", text)

