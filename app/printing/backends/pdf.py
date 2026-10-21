"""Impressora virtual "VYONIX PDF" — grava cada trabalho como arquivo PDF.

É uma saída real (não simulação): o arquivo é gravado de forma atômica (temporário + fsync +
renomeação), relido para conferir o número de páginas e só então o trabalho é dado como
concluído. Útil para homologação, arquivamento e para enviar a impressão por outros meios.

O tamanho físico das páginas no PDF corresponde ao papel escolhido (resolução gravada no
arquivo), portanto uma régua de 10 cm no padrão de teste mede 10 cm quando impressa a 100 %.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from app.core.contracts import PrinterInfo, SpoolRequest, SpoolResult, SpoolStatus
from app.printing.paper import PAPER_SIZES
from app.utils.logging_setup import get_logger

log = get_logger("printing.pdf")

PDF_PRINTER = "VYONIX PDF (arquivo)"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str, limit: int = 80) -> str:
    return (_SAFE.sub("_", name).strip("._") or "documento")[:limit]


def count_pdf_pages(path: Path) -> int:
    """Número de páginas segundo a árvore de páginas mais recente (o Pillow grava cada página
    acrescentada como atualização incremental, reescrevendo o nó /Pages com o novo /Count)."""
    data = path.read_bytes()
    counts = re.findall(rb"/Count\s+(\d+)", data)
    return int(counts[-1]) if counts else 0


class PdfFileBackend:
    name = "pdf"

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)

    def list_printers(self) -> list[PrinterInfo]:
        return [PrinterInfo(name=PDF_PRINTER, driver="VYONIX (PDF)", is_default=False,
                            paper_sizes=tuple(PAPER_SIZES), resolutions_dpi=(150, 200, 300, 600),
                            supports_color=True, status_text=f"Grava arquivos em {self.output_dir}",
                            backend=self.name, port=str(self.output_dir))]

    def submit(self, request: SpoolRequest) -> SpoolResult:
        from PIL import Image

        self.output_dir.mkdir(parents=True, exist_ok=True)
        final = self.output_dir / f"{safe_filename(request.document_name)}.pdf"
        n = 2
        while final.exists():
            final = self.output_dir / f"{safe_filename(request.document_name)}_{n}.pdf"
            n += 1
        tmp = final.with_suffix(".pdf.part")
        written = 0
        try:
            for page in request.pages():   # uma página por vez: memória constante
                img = Image.fromarray(page.pixels)
                img.save(tmp, "PDF", resolution=float(page.dpi), append=written > 0,
                         title=request.document_name, creator="VYONIX DICOM Print")
                written += 1
            if written == 0:
                raise ValueError("nenhuma página foi gerada")
            with open(tmp, "rb+") as fh:
                os.fsync(fh.fileno())
            os.replace(tmp, final)
        except Exception as exc:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
            log.exception("Falha ao gravar PDF")
            return SpoolResult(accepted=False, spool_job_id=None, error=f"Falha ao gravar o PDF: {exc}")
        pages = count_pdf_pages(final)
        if pages != written:
            return SpoolResult(accepted=True, spool_job_id=None, confirmed=False, output_path=str(final),
                               error=f"PDF gravado com {pages} página(s); esperadas {written}.")
        detail = f"{written} página(s) gravada(s) em {final.name}"
        if request.copies > 1:
            detail += " (arquivo único; cópias não se aplicam a PDF)"
        return SpoolResult(accepted=True, spool_job_id=None, confirmed=True, output_path=str(final), detail=detail)

    def job_status(self, printer: str, spool_job_id: int) -> SpoolStatus:
        return SpoolStatus("printed", "arquivo gravado")
