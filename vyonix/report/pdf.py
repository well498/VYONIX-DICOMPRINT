"""PDF do laudo liberado (impressão e entrega), gerado a partir das versões imutáveis e da identidade visual
(TELELAUDO T2) registrada na liberação.

Traz a instituição, o paciente, o estudo, o texto liberado, os adendos, quem liberou (identificação profissional),
quando, o SHA-256 de cada versão e o aviso de que a liberação não é assinatura digital ICP-Brasil (BLK-14). A mesma
função gera a pré-visualização da identidade (dados fictícios). Não liberado para uso clínico.
"""

from __future__ import annotations

import io
import os
from datetime import timedelta, timezone
from typing import Any
from xml.sax.saxutils import escape

BRT = timezone(timedelta(hours=-3))
_FONT_FILES = {
    "Sans": [("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
             ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")],
    "Serif": [("C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesbd.ttf"),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf")],
}
_BUILTIN = {"Sans": ("Helvetica", "Helvetica-Bold"), "Serif": ("Times-Roman", "Times-Bold")}


def _fonts(family: str = "Sans") -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    family = family if family in _FONT_FILES else "Sans"
    for reg, bold in _FONT_FILES[family]:
        if os.path.exists(reg) and os.path.exists(bold):
            names = (f"VXL{family}R", f"VXL{family}B")
            try:
                if names[0] not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(names[0], reg))
                    pdfmetrics.registerFont(TTFont(names[1], bold))
                return names
            except Exception:  # noqa: BLE001
                continue
    return _BUILTIN[family]


def _when(iso: str) -> str:
    from datetime import datetime
    return datetime.fromisoformat(iso).astimezone(BRT).strftime("%d/%m/%Y %H:%M")


def render(report: dict[str, Any], *, patient: dict[str, Any], study: dict[str, Any], institution: dict[str, Any],
           branding: dict[str, Any] | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    b = branding or {}
    cfg = dict(b.get("settings") or {})
    reg, bold = _fonts(cfg.get("font", "Sans"))
    size = float(cfg.get("font_size", 10.5))
    accent = colors.HexColor(cfg.get("accent_color", "#12313F"))
    grey = colors.HexColor("#4a5a66")
    st = {"h": ParagraphStyle("h", fontName=bold, fontSize=size + 2.5, leading=size + 6, textColor=accent),
          "s": ParagraphStyle("s", fontName=reg, fontSize=size - 2, leading=size + 0.5, textColor=grey),
          "b": ParagraphStyle("b", fontName=reg, fontSize=size, leading=size * 1.45),
          "k": ParagraphStyle("k", fontName=bold, fontSize=size - 0.5, leading=size + 2.5, textColor=accent),
          "w": ParagraphStyle("w", fontName=bold, fontSize=size - 0.5, leading=size + 2.5,
                              textColor=colors.HexColor("#9a3412"))}

    def para(text: str, style: str = "b") -> Paragraph:
        return Paragraph(escape(text or "").replace("\n", "<br/>"), st[style])

    logo = b.get("logo")
    letterhead = b.get("letterhead")
    logo_h = float(cfg.get("logo_height_mm", 14)) * mm
    header_text, footer_text = cfg.get("header_text") or "", cfg.get("footer_text") or ""
    page_numbers = bool(cfg.get("page_numbers", True))
    mt, mb = float(cfg.get("margin_top_mm", 16)) * mm, float(cfg.get("margin_bottom_mm", 16)) * mm
    ml, mr = float(cfg.get("margin_left_mm", 18)) * mm, float(cfg.get("margin_right_mm", 18)) * mm
    pw, ph = A4

    class Numbered(rl_canvas.Canvas):
        """Fundo (papel timbrado), cabeçalho, rodapé e "Página X de Y" em todas as páginas."""

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._pages: list[dict] = []

        def showPage(self):  # noqa: N802 - API do ReportLab
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for n, state in enumerate(self._pages, start=1):
                self.__dict__.update(state)
                self._decorate(n, total)
                super().showPage()
            super().save()

        def _decorate(self, n: int, total: int) -> None:
            self.saveState()
            if header_text:
                self.setFont(reg, size - 2)
                self.setFillColor(grey)
                self.drawRightString(pw - mr, ph - mt / 2, header_text[:150])
            self.setFont(reg, size - 2.5)
            self.setFillColor(grey)
            if footer_text:
                self.drawString(ml, mb / 2, footer_text[:160])
            if page_numbers:
                self.drawRightString(pw - mr, mb / 2, f"Página {n} de {total}")
            self.restoreState()

    inst = institution.get("display_name") or "Instituição"
    extra = " · ".join(x for x in (institution.get("document") and f"CNPJ {institution['document']}",
                                   institution.get("address"), institution.get("phone")) if x)
    head: list[Any] = [para(inst, "h")]
    if extra:
        head.append(para(extra, "s"))
    story: list[Any] = []
    if logo is not None:
        from reportlab.platypus import Image as RLImage
        ratio = logo.width / max(logo.height, 1)
        img = RLImage(io.BytesIO(logo.data), width=logo_h * ratio, height=logo_h)
        t = Table([[img, head]], colWidths=[logo_h * ratio + 4 * mm, None])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(t)
    else:
        story += head
    story += [Spacer(1, 3 * mm), HRFlowable(width="100%", color=accent), Spacer(1, 3 * mm)]
    rows = [["Paciente", patient.get("name") or "—", "Nascimento", patient.get("birth_date") or "—"],
            ["Identificação", patient.get("identifier") or "—", "Sexo", patient.get("sex") or "—"],
            ["Exame", f"{study.get('modality') or ''} {study.get('description') or ''}".strip() or "—",
             "Data do exame", study.get("study_date") or "—"],
            ["Número de acesso", study.get("accession") or "—", "Solicitante", study.get("requester") or "—"]]
    width = pw - ml - mr
    t = Table([[para(a, "k"), para(c1), para(c, "k"), para(d)] for a, c1, c, d in rows],
              colWidths=[width * 0.19, width * 0.36, width * 0.18, width * 0.27])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story += [t, Spacer(1, 5 * mm)]
    for v in report["versions"]:
        title = "Laudo" if v["kind"] == "final" else f"Adendo (versão {v['version']})"
        story.append(para(title, "k"))
        if v["critical"]:
            story.append(para("Achado crítico", "w"))
        story += [Spacer(1, 1.5 * mm), para(v["body"]), Spacer(1, 2 * mm)]
        if v.get("signature_image"):                         # elemento visual autorizado pelo médico (não é assinatura)
            from reportlab.platypus import Image as RLImage
            data_, w_, h_ = v["signature_image"]
            hh = 14 * mm
            story.append(RLImage(io.BytesIO(data_), width=hh * w_ / max(h_, 1), height=hh, hAlign="LEFT"))
        story += [para(f"Liberado por {v['signed_by']} em {_when(v['signed_at'])} · SHA-256 {v['sha256']}", "s"),
                  Spacer(1, 4 * mm)]
    story += [HRFlowable(width="100%", color=colors.HexColor("#c8d0d6")), Spacer(1, 2 * mm),
              para("Liberação registrada no VYONIX com confirmação de senha do médico. Não é assinatura digital "
                   "ICP-Brasil. A integridade de cada versão pode ser conferida pelo SHA-256 no sistema. "
                   "Documento gerado por software não liberado para uso clínico.", "s")]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=ml, rightMargin=mr, topMargin=mt, bottomMargin=mb,
                            title=f"Laudo {study.get('accession') or ''}".strip(), author=inst, creator="VYONIX REPORT")
    def background(cv, _doc):                         # papel timbrado por baixo do conteúdo
        if letterhead is not None:
            cv.saveState()
            cv.drawImage(ImageReader(io.BytesIO(letterhead.data)), 0, 0, width=pw, height=ph,
                         preserveAspectRatio=False, mask="auto")
            cv.restoreState()
    doc.build(story, onFirstPage=background, onLaterPages=background, canvasmaker=Numbered)
    return buf.getvalue()


def preview(branding: dict[str, Any], institution: dict[str, Any], *, pages: int = 1, body: str | None = None) -> bytes:
    """Pré-visualização A4 (identidade ou modelo) com dados fictícios (sem dados de pacientes)."""
    sample = ("Técnica: exame realizado com protocolo padrão (texto de exemplo).\nAchados: texto de exemplo para "
              "conferir margens, fontes, cores, cabeçalho, rodapé e quebra de página.\nConclusão: exemplo.")
    text = body if body is not None else "\n\n".join([sample] * (6 * pages))
    rep = {"versions": [{"version": 1, "kind": "final", "body": text, "critical": False,
                         "signed_by": "Dr(a). Exemplo — CRM 000000/UF", "signed_at": "2026-01-01T12:00:00+00:00",
                         "sha256": "0" * 64}]}
    return render(rep, patient={"name": "PACIENTE DE EXEMPLO", "identifier": "000000", "sex": "—",
                                "birth_date": "01/01/1970"},
                  study={"modality": "XX", "description": "Exame de exemplo", "study_date": "01/01/2026",
                         "accession": "EXEMPLO", "requester": "Dr(a). Solicitante"},
                  institution=institution, branding=branding)
