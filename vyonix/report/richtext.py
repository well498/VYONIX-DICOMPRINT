"""Texto rico dos laudos e modelos: um subconjunto **seguro** de HTML.

* **Permitido:** parágrafos, quebras, títulos (``h3``/``h4``), negrito, itálico, sublinhado, listas com marcadores e
  numeradas, tabelas simples (``colspan``/``rowspan`` até 10). Nada mais: sem estilos, classes, links, imagens,
  scripts ou atributos de evento. Tudo fora disso é descartado (o texto de dentro é mantido, exceto em ``script``,
  ``style`` e semelhantes, cujo conteúdo é removido).
* **Por quê:** o mesmo conteúdo aparece no navegador, no PDF e nas exportações; a lista fechada evita injeção de
  código e mantém o PDF fiel ao que o médico vê.
* **Saídas:** HTML limpo (armazenado), texto simples (FHIR/HL7, busca e compatibilidade) e elementos do ReportLab
  (PDF), sem interpretar nada além da lista permitida.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from vyonix.errors import ValidationFailed

MAX_HTML = 400_000
BLOCK = {"p", "h3", "h4", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td"}
INLINE = {"strong", "em", "u", "br"}
ALIAS = {"b": "strong", "i": "em", "h1": "h3", "h2": "h3", "h5": "h4", "h6": "h4", "div": "p", "section": "p",
         "article": "p", "blockquote": "p", "caption": "p", "tfoot": "tbody"}
DROP_CONTENT = {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math", "head",
                "title", "textarea", "select", "button", "form"}
VOID = {"br"}
FORMATS = ("text", "html")


class _Clean(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        tag = ALIAS.get(tag.lower(), tag.lower())
        if tag in DROP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in BLOCK | INLINE:
            return
        if tag in VOID:
            self.out.append("<br>")
            return
        extra = ""
        if tag in ("td", "th"):
            for k, v in attrs:
                if k in ("colspan", "rowspan") and (v or "").isdigit() and 1 < int(v) <= 10:
                    extra += f' {k}="{int(v)}"'
        self.stack.append(tag)
        self.out.append(f"<{tag}{extra}>")

    def handle_startendtag(self, tag, attrs):
        tag = ALIAS.get(tag.lower(), tag.lower())
        if not self.skip and tag in VOID:
            self.out.append("<br>")

    def handle_endtag(self, tag):
        tag = ALIAS.get(tag.lower(), tag.lower())
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in self.stack:
            return
        while self.stack:
            t = self.stack.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def sanitize(value: str) -> str:
    """HTML recebido (editor, colagem, importação) → HTML da lista permitida."""
    if len(value or "") > MAX_HTML:
        raise ValidationFailed("Laudo grande demais.")
    p = _Clean()
    p.feed(value or "")
    p.close()
    return p.result().strip()


def from_text(text: str) -> str:
    """Texto simples (laudos e modelos antigos) → HTML equivalente (parágrafos e quebras)."""
    paras = re.split(r"\n{2,}", (text or "").strip())
    return "".join("<p>" + html.escape(p, quote=False).replace("\n", "<br>") + "</p>" for p in paras if p.strip())


def to_text(value: str, fmt: str = "html") -> str:
    """Conteúdo → texto simples legível (listas com marcador, tabelas com " | ")."""
    if fmt != "html":
        return value or ""

    class T(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.buf, self.ol, self.cell = [], [], False

        def handle_starttag(self, tag, attrs):
            if tag in ("p", "h3", "h4", "table"):
                self.buf.append("\n\n")
            elif tag == "br":
                self.buf.append("\n")
            elif tag == "ol":
                self.ol.append(0)
                self.buf.append("\n")
            elif tag == "ul":
                self.ol.append(None)
                self.buf.append("\n")
            elif tag == "li":
                if self.ol and self.ol[-1] is not None:
                    self.ol[-1] += 1
                    self.buf.append(f"\n{self.ol[-1]}. ")
                else:
                    self.buf.append("\n• ")
            elif tag == "tr":
                self.buf.append("\n")
                self.cell = False
            elif tag in ("td", "th"):
                if self.cell:
                    self.buf.append(" | ")
                self.cell = True

        def handle_endtag(self, tag):
            if tag in ("ol", "ul") and self.ol:
                self.ol.pop()
                self.buf.append("\n")

        def handle_data(self, data):
            self.buf.append(data)
    t = T()
    t.feed(value or "")
    t.close()
    txt = "".join(t.buf)
    txt = re.sub(r"[ \t]+\n", "\n", txt)
    return re.sub(r"\n{3,}", "\n\n", txt).strip()


def normalize(body: str, fmt: str | None) -> tuple[str, str]:
    """(conteúdo, formato) validados para gravar."""
    fmt = fmt or "text"
    if fmt not in FORMATS:
        raise ValidationFailed("Formato do texto inválido.")
    return (sanitize(body), "html") if fmt == "html" else (body or "", "text")


# --------------------------------------------------------------------------- PDF (ReportLab)

def to_flowables(value: str, fmt: str, styles: dict, *, width: float):
    """Conteúdo → lista de elementos do ReportLab. ``styles``: ``b`` (corpo), ``h3``, ``h4`` (opcionais)."""
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, Spacer, Table, TableStyle
    body = styles["b"]
    if fmt != "html":
        return [Paragraph(escape(value or "").replace("\n", "<br/>"), body)]
    h3, h4 = styles.get("h3", body), styles.get("h4", body)

    class B(HTMLParser):
        """Monta blocos: [("p"|"h3"|"h4", markup)], ("list", ordered, [markup]), ("table", [[(markup, colspan)]])."""

        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.blocks, self.cur, self.kind = [], None, None
            self.lists, self.table, self.row = [], None, None

        def _flush(self):
            if self.cur is not None and self.kind in ("p", "h3", "h4"):
                self.blocks.append((self.kind, "".join(self.cur)))
            self.cur, self.kind = None, None

        def handle_starttag(self, tag, attrs):
            if tag in ("p", "h3", "h4") and self.table is None and not self.lists:
                self._flush()
                self.cur, self.kind = [], tag
            elif tag in ("ul", "ol"):
                self._flush()
                self.lists.append((tag == "ol", []))
            elif tag == "li" and self.lists:
                self.lists[-1][1].append([])
            elif tag == "table":
                self._flush()
                self.table = []
            elif tag == "tr" and self.table is not None:
                self.row = []
                self.table.append(self.row)
            elif tag in ("td", "th") and self.row is not None:
                span = next((int(v) for k, v in attrs if k == "colspan" and str(v).isdigit()), 1)
                self.row.append([[], span, tag == "th"])
            elif tag in ("strong", "em", "u"):
                self._emit({"strong": "<b>", "em": "<i>", "u": "<u>"}[tag])
            elif tag == "br":
                self._emit("<br/>")

        def handle_endtag(self, tag):
            if tag in ("p", "h3", "h4") and self.kind == tag:
                self._flush()
            elif tag in ("ul", "ol") and self.lists:
                ordered, items = self.lists.pop()
                block = ("list", ordered, ["".join(x) for x in items])
                if self.lists and self.lists[-1][1]:
                    self.lists[-1][1][-1].append("<br/>" + "<br/>".join("• " + x for x in block[2]))
                else:
                    self.blocks.append(block)
            elif tag == "table" and self.table is not None:
                self.blocks.append(("table", [[("".join(c[0]), c[1], c[2]) for c in r] for r in self.table]))
                self.table, self.row = None, None
            elif tag in ("strong", "em", "u"):
                self._emit({"strong": "</b>", "em": "</i>", "u": "</u>"}[tag])

        def _emit(self, s):
            if self.table is not None:
                if self.row:
                    self.row[-1][0].append(s)
                return                                       # espaços entre linhas/células
            if self.lists:
                if self.lists[-1][1]:
                    self.lists[-1][1][-1].append(s)
                return                                       # espaços entre itens
            else:
                if self.cur is None:
                    self.cur, self.kind = [], "p"
                self.cur.append(s)

        def handle_data(self, data):
            self._emit(escape(data))

        def close(self):
            super().close()
            self._flush()
    b = B()
    b.feed(value or "")
    b.close()
    out = []
    for blk in b.blocks:
        if blk[0] in ("p", "h3", "h4"):
            out.append(Paragraph(blk[1] or "&nbsp;", {"p": body, "h3": h3, "h4": h4}[blk[0]]))
        elif blk[0] == "list":
            items = [ListItem(Paragraph(x or "&nbsp;", body)) for x in blk[2]]
            out.append(ListFlowable(items, bulletType="1" if blk[1] else "bullet", start=1 if blk[1] else None,
                                    leftIndent=14, bulletFontSize=body.fontSize))
        elif blk[0] == "table":
            rows = blk[1]
            ncol = max((sum(c[1] for c in r) for r in rows), default=1)
            data, spans, head = [], [], []
            for ri, r in enumerate(rows):
                line, ci = [], 0
                for text, span, is_h in r:
                    line.append(Paragraph(f"<b>{text}</b>" if is_h else (text or "&nbsp;"), body))
                    if span > 1:
                        spans.append(("SPAN", (ci, ri), (ci + span - 1, ri)))
                        line += [""] * (span - 1)
                    if is_h:
                        head.append(("BACKGROUND", (ci, ri), (ci + span - 1, ri), colors.HexColor("#eef2f5")))
                    ci += span
                data.append(line + [""] * (ncol - len(line)))
            t = Table(data, colWidths=[width / ncol] * ncol, hAlign="LEFT")
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa9b5")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"), *spans, *head]))
            out += [t, Spacer(1, 4)]
    return out or [Paragraph("&nbsp;", body)]
