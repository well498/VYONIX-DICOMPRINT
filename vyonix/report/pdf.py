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
           branding: dict[str, Any] | None = None, block: dict[str, Any] | None = None) -> bytes:
    """Três situações distintas, nunca confundidas no documento:

    * **rascunho** (``report["draft"]``): marca d'água "RASCUNHO — NÃO FINALIZADO" em todas as páginas, sem bloco
      de assinatura, sem imagem e sem "Liberado por";
    * **liberado com confirmação de senha**, com ou sem a **imagem da assinatura manuscrita** (elemento visual,
      inserido só na versão liberada pelo próprio médico que autorizou o uso);
    * **assinado digitalmente (PAdES/ICP-Brasil)** — ainda não disponível (BLK-14); o texto do documento nunca o
      sugere.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import Flowable, HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from vyonix.report.templates import block_settings
    blk = block_settings(block)
    draft = bool(report.get("draft"))
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
            if draft:                                   # rascunho nunca aparenta estar assinado
                self.setFillColor(colors.HexColor("#b91c1c"))
                self.setFont(bold, size)
                self.drawCentredString(pw / 2, ph - mt / 2 - 3 * mm, "RASCUNHO — NÃO FINALIZADO — SEM VALIDADE")
                self.setFillAlpha(0.12)
                self.setFont(bold, 46)
                self.translate(pw / 2, ph / 2)
                self.rotate(45)
                self.drawCentredString(0, 0, "RASCUNHO")
                self.drawCentredString(0, -54, "NÃO FINALIZADO")
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
    align = {"left": 0, "center": 1, "right": 2}[blk["align"]]
    al_name = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}[blk["align"]]
    st["sig"] = ParagraphStyle("sig", parent=st["b"], alignment=align, leading=size * 1.3)
    st["sigs"] = ParagraphStyle("sigs", parent=st["s"], alignment=align)

    def signer_block(v: dict[str, Any]) -> list[Any]:
        """Bloco profissional configurado no modelo: imagem (se autorizada), nome, CRM/UF, especialidade, RQE."""
        from reportlab.platypus import Image as RLImage
        items: list[Any] = []
        if v.get("signature_image") and blk["show_image"]:
            data_, w_, h_ = v["signature_image"]
            hh = blk["height_mm"] * mm
            ww = min(hh * w_ / max(h_, 1), (pw - ml - mr) * 0.6)
            items.append(RLImage(io.BytesIO(data_), width=ww, height=ww * h_ / max(w_, 1), hAlign=al_name))
        sg = v.get("signer") or {}
        lines = []
        if blk["show_name"]:
            lines.append(sg.get("name") or v["signed_by"])
        if blk["show_crm"] and sg.get("crm"):
            lines.append(sg["crm"])
        if blk["show_specialty"] and sg.get("specialty"):
            lines.append(sg["specialty"])
        if blk["show_rqe"] and sg.get("rqe"):
            lines.append(f"RQE {sg['rqe']}")
        if lines:
            items.append(Paragraph("<br/>".join(escape(x) for x in lines), st["sig"]))
        how = ("imagem da assinatura manuscrita digitalizada (elemento visual) · liberado com confirmação de senha"
               if v.get("signature_image") and blk["show_image"] else "liberado com confirmação de senha")
        items.append(Paragraph(escape(f"{how} em {_when(v['signed_at'])} · SHA-256 {v['sha256']}"), st["sigs"]))
        return items

    class AtBottom(Flowable):
        """Bloco no rodapé da última página: ocupa o espaço restante e desenha o conteúdo encostado embaixo."""

        def __init__(self, items: list[Any]):
            super().__init__()
            self.t = Table([[x] for x in items], colWidths=[pw - ml - mr])
            self.t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), al_name), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                        ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

        def wrap(self, aw, ah):  # noqa: D401
            _w, self.h = self.t.wrap(aw, ah)
            return aw, (self.h if ah < self.h else max(self.h, ah - 1))

        def draw(self):
            self.t.drawOn(self.canv, 0, 0)

    footer_items: list[Any] = []
    for v in report["versions"]:
        title = {"final": "Laudo", "draft": "Laudo — RASCUNHO (não finalizado)"}.get(
            v["kind"], f"Adendo (versão {v['version']})")
        story.append(para(title, "k" if not draft else "w"))
        if v["critical"]:
            story.append(para("Achado crítico", "w"))
        story += [Spacer(1, 1.5 * mm), para(v["body"]), Spacer(1, 2 * mm)]
        if draft:
            continue
        items = signer_block(v)
        if blk["position"] == "footer" and v["kind"] == "final":
            footer_items = items
        else:
            from reportlab.platypus import KeepTogether
            story += [Spacer(1, 2 * mm), KeepTogether(items)]
        story.append(Spacer(1, 4 * mm))
    story += [HRFlowable(width="100%", color=colors.HexColor("#c8d0d6")), Spacer(1, 2 * mm)]
    if draft:
        story.append(para("RASCUNHO: documento não finalizado, sem liberação, sem assinatura e sem validade. "
                          "Documento gerado por software não liberado para uso clínico.", "w"))
    else:
        story.append(para("Liberação registrada no VYONIX com confirmação de senha do médico. Não é assinatura digital "
                          "ICP-Brasil. A imagem da assinatura manuscrita, quando presente, é apenas um elemento visual "
                          "autorizado pelo médico. A integridade de cada versão pode ser conferida pelo SHA-256 "
                          "no sistema. Documento gerado por software não liberado para uso clínico.", "s"))
    if footer_items:
        story.append(AtBottom(footer_items))
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


def sample_signature() -> tuple[bytes, int, int]:
    """Traço sintético (não é assinatura de ninguém) para a prévia do bloco de assinatura do modelo."""
    import math

    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (600, 180), (255, 255, 255, 0))
    d = ImageDraw.Draw(im)
    pts = [(30 + x * 5.4, 95 + 38 * math.sin(x / 9) * math.cos(x / 23)) for x in range(100)]
    d.line(pts, fill=(20, 40, 90, 255), width=5)
    d.text((440, 150), "EXEMPLO", fill=(150, 150, 150, 255))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue(), 600, 180


def preview(branding: dict[str, Any], institution: dict[str, Any], *, pages: int = 1, body: str | None = None,
            block: dict[str, Any] | None = None) -> bytes:
    """Pré-visualização A4 (identidade ou modelo) com dados fictícios (sem dados de pacientes)."""
    sample = ("Técnica: exame realizado com protocolo padrão (texto de exemplo).\nAchados: texto de exemplo para "
              "conferir margens, fontes, cores, cabeçalho, rodapé e quebra de página.\nConclusão: exemplo.")
    text = body if body is not None else "\n\n".join([sample] * (6 * pages))
    rep = {"versions": [{"version": 1, "kind": "final", "body": text, "critical": False,
                         "signed_by": "Dr(a). Exemplo — CRM 000000/UF", "signed_at": "2026-01-01T12:00:00+00:00",
                         "sha256": "0" * 64, "signature_image": sample_signature(),
                         "signer": {"name": "Dr(a). Exemplo", "crm": "CRM 000000/UF", "rqe": "00000",
                                    "specialty": "Especialidade de exemplo"}}]}
    return render(rep, patient={"name": "PACIENTE DE EXEMPLO", "identifier": "000000", "sex": "—",
                                "birth_date": "01/01/1970"},
                  study={"modality": "XX", "description": "Exame de exemplo", "study_date": "01/01/2026",
                         "accession": "EXEMPLO", "requester": "Dr(a). Solicitante"},
                  institution=institution, branding=branding, block=block)
