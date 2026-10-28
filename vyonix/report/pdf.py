"""PDF do laudo liberado (impressão e entrega). Gerado na hora a partir das versões imutáveis.

Traz a instituição, o paciente, o estudo, o texto liberado, os adendos, quem liberou, quando, o SHA-256 de cada
versão e o aviso de que a liberação não é assinatura digital ICP-Brasil (BLK-14). Não liberado para uso clínico.
"""

from __future__ import annotations

import io
import os
from datetime import timezone, timedelta
from typing import Any
from xml.sax.saxutils import escape

BRT = timezone(timedelta(hours=-3))


def _fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for reg, bold in (("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
                      ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                       "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
        if os.path.exists(reg) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("VXLR", reg))
                pdfmetrics.registerFont(TTFont("VXLB", bold))
                return "VXLR", "VXLB"
            except Exception:  # noqa: BLE001
                continue
    return "Helvetica", "Helvetica-Bold"


def _when(iso: str) -> str:
    from datetime import datetime
    return datetime.fromisoformat(iso).astimezone(BRT).strftime("%d/%m/%Y %H:%M")


def render(report: dict[str, Any], *, patient: dict[str, Any], study: dict[str, Any], institution: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    reg, bold = _fonts()
    st = {"h": ParagraphStyle("h", fontName=bold, fontSize=13, leading=16),
          "s": ParagraphStyle("s", fontName=reg, fontSize=8.5, leading=11, textColor=colors.HexColor("#4a5a66")),
          "b": ParagraphStyle("b", fontName=reg, fontSize=10.5, leading=15),
          "k": ParagraphStyle("k", fontName=bold, fontSize=10, leading=13),
          "w": ParagraphStyle("w", fontName=bold, fontSize=10, leading=13, textColor=colors.HexColor("#9a3412"))}

    def para(text: str, style: str = "b") -> Paragraph:
        return Paragraph(escape(text or "").replace("\n", "<br/>"), st[style])

    inst = institution.get("display_name") or "Instituição"
    extra = " · ".join(x for x in (institution.get("document") and f"CNPJ {institution['document']}",
                                   institution.get("address"), institution.get("phone")) if x)
    story: list[Any] = [para(inst, "h")]
    if extra:
        story.append(para(extra, "s"))
    story += [Spacer(1, 3 * mm), HRFlowable(width="100%", color=colors.HexColor("#c8d0d6")), Spacer(1, 3 * mm)]
    rows = [["Paciente", patient.get("name") or "—", "Nascimento", patient.get("birth_date") or "—"],
            ["Identificação", patient.get("identifier") or "—", "Sexo", patient.get("sex") or "—"],
            ["Exame", f"{study.get('modality') or ''} {study.get('description') or ''}".strip() or "—",
             "Data do exame", study.get("study_date") or "—"],
            ["Número de acesso", study.get("accession") or "—", "Solicitante", study.get("requester") or "—"]]
    t = Table([[para(a, "k"), para(b), para(c, "k"), para(d)] for a, b, c, d in rows],
              colWidths=[32 * mm, 62 * mm, 30 * mm, 46 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story += [t, Spacer(1, 5 * mm)]
    for v in report["versions"]:
        title = "Laudo" if v["kind"] == "final" else f"Adendo (versão {v['version']})"
        story.append(para(title, "k"))
        if v["critical"]:
            story.append(para("Achado crítico", "w"))
        story += [Spacer(1, 1.5 * mm), para(v["body"]), Spacer(1, 2 * mm),
                  para(f"Liberado por {v['signed_by']} em {_when(v['signed_at'])} · SHA-256 {v['sha256']}", "s"),
                  Spacer(1, 4 * mm)]
    story += [HRFlowable(width="100%", color=colors.HexColor("#c8d0d6")), Spacer(1, 2 * mm),
              para("Liberação registrada no VYONIX com confirmação de senha do médico. Não é assinatura digital "
                   "ICP-Brasil. A integridade de cada versão pode ser conferida pelo SHA-256 no sistema. "
                   "Documento gerado por software não liberado para uso clínico.", "s")]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"Laudo {study.get('accession') or ''}".strip(),
                            author=inst, creator="VYONIX REPORT")
    doc.build(story)
    return buf.getvalue()
