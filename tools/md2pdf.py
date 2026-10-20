"""Conversor Markdown → PDF (subconjunto) com identidade VYONIX, usando ReportLab.

Suporta: títulos (#, ##, ###), parágrafos, listas (- e 1.), tabelas (| a | b |),
blocos de código (```), **negrito**, *itálico* e `código`.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, ListFlowable, ListItem, Paragraph, Preformatted,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

BLUE = colors.HexColor("#1460F2")
NAVY = colors.HexColor("#0A1A33")
MUTED = colors.HexColor("#5B6B7F")
LINE = colors.HexColor("#D7DEE7")
ALT = colors.HexColor("#EEF2F6")

_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/consola.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/cour.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
]


def _fonts() -> tuple[str, str, str]:
    for regular, bold, mono in _FONT_CANDIDATES:
        if all(Path(p).exists() for p in (regular, bold, mono)):
            pdfmetrics.registerFont(TTFont("VX", regular))
            pdfmetrics.registerFont(TTFont("VX-Bold", bold))
            pdfmetrics.registerFont(TTFont("VX-Mono", mono))
            pdfmetrics.registerFontFamily("VX", normal="VX", bold="VX-Bold",
                                          italic="VX", boldItalic="VX-Bold")
            return "VX", "VX-Bold", "VX-Mono"
    return "Helvetica", "Helvetica-Bold", "Courier"


FONT, BOLD, MONO = _fonts()

S = {
    "h1": ParagraphStyle("h1", fontName=BOLD, fontSize=20, leading=25, textColor=NAVY,
                         spaceAfter=4),
    "h2": ParagraphStyle("h2", fontName=BOLD, fontSize=13.5, leading=18, textColor=BLUE,
                         spaceBefore=12, spaceAfter=5),
    "h3": ParagraphStyle("h3", fontName=BOLD, fontSize=11, leading=15, textColor=NAVY,
                         spaceBefore=8, spaceAfter=3),
    "p": ParagraphStyle("p", fontName=FONT, fontSize=9.8, leading=14, alignment=TA_LEFT,
                        spaceAfter=5),
    "cell": ParagraphStyle("cell", fontName=FONT, fontSize=8.6, leading=11),
    "cellh": ParagraphStyle("cellh", fontName=BOLD, fontSize=8.6, leading=11),
    "code": ParagraphStyle("code", fontName=MONO, fontSize=8.3, leading=11, backColor=ALT,
                           borderPadding=6, spaceBefore=4, spaceAfter=8),
}

if FONT == "Helvetica":  # fonte sem cobertura Unicode ampla
    _FALLBACK = {"→": "->", "✅": "OK", "❌": "X", "⚠": "!", "×": "x", "≥": ">=", "≤": "<="}
else:
    _FALLBACK = {"✅": "OK", "❌": "FALHOU", "⚠": "!"}


def _clean(text: str) -> str:
    for k, v in _FALLBACK.items():
        text = text.replace(k, v)
    return text


def inline(text: str) -> str:
    text = html.escape(_clean(text), quote=False)
    text = re.sub(r"`([^`]+)`", lambda m: f'<font face="{MONO}">{m[1]}</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![*\w])\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    return text


def _table(rows: list[list[str]], width: float):
    data = [[Paragraph(inline(c), S["cellh" if i == 0 else "cell"]) for c in r]
            for i, r in enumerate(rows)]
    ncols = max(len(r) for r in rows)
    lens = [max(len(r[c]) if c < len(r) else 0 for r in rows) for c in range(ncols)]
    total = sum(max(n, 6) for n in lens)
    widths = [width * max(n, 6) / total for n in lens]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ALT),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def parse(md: str, width: float) -> list:
    flow: list = []
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    para: list[str] = []

    def flush() -> None:
        if para:
            flow.append(Paragraph(inline(" ".join(para)), S["p"]))
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(_clean(lines[i]))
                i += 1
            flow.append(Preformatted("\n".join(block), S["code"]))
        elif s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            flow.append(_table(rows, width))
            flow.append(Spacer(1, 6))
            continue
        elif re.match(r"^(-|\*|\d+\.)\s+", s):
            flush()
            ordered = bool(re.match(r"^\d+\.", s))
            items = []
            while i < len(lines) and re.match(r"^(-|\*|\d+\.)\s+", lines[i].strip()):
                text = re.sub(r"^(-|\*|\d+\.)\s+", "", lines[i].strip())
                i += 1
                while i < len(lines) and lines[i].startswith("  ") and lines[i].strip() \
                        and not re.match(r"^(-|\*|\d+\.)\s+", lines[i].strip()):
                    text += " " + lines[i].strip()
                    i += 1
                items.append(ListItem(Paragraph(inline(text), S["p"]), leftIndent=14))
            flow.append(ListFlowable(items, bulletType="1" if ordered else "bullet",
                                     start="1" if ordered else None, leftIndent=14,
                                     bulletFontName=FONT, bulletFontSize=8.5))
            continue
        elif s.startswith("### "):
            flush()
            flow.append(Paragraph(inline(s[4:]), S["h3"]))
        elif s.startswith("## "):
            flush()
            flow.append(Paragraph(inline(s[3:]), S["h2"]))
        elif s.startswith("# "):
            flush()
            flow.append(Paragraph(inline(s[2:]), S["h1"]))
        elif s.startswith(">"):
            flush()
            flow.append(Paragraph(inline(s.lstrip("> ")), ParagraphStyle(
                "q", parent=S["p"], textColor=MUTED, leftIndent=8, borderPadding=4)))
        elif not s:
            flush()
        else:
            para.append(s)
        i += 1
    flush()
    return flow


def convert(src: Path, dst: Path, *, title: str, version: str) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)

    def frame(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFillColor(BLUE)
        canvas.rect(0, A4[1] - 6 * mm, A4[0], 6 * mm, stroke=0, fill=1)
        canvas.setFont(BOLD, 8.5)
        canvas.setFillColor(NAVY)
        canvas.drawString(18 * mm, A4[1] - 13 * mm, "VYONIX DICOM Print")
        canvas.setFont(FONT, 8)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 13 * mm, f"{title} · versão {version}")
        canvas.drawString(18 * mm, 10 * mm, "Precisão em cada imagem.")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Página {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(dst), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=20 * mm, bottomMargin=18 * mm, title=title,
                            author="VYONIX", subject=f"VYONIX DICOM Print {version}")
    story = parse(src.read_text(encoding="utf-8"), A4[0] - 36 * mm)
    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    return dst


if __name__ == "__main__":
    convert(Path(sys.argv[1]), Path(sys.argv[2]), title=sys.argv[3], version=sys.argv[4])
