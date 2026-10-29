"""Minha Produção: laudos liberados por médico, por dia, mês, período, unidade e modalidade; pendências; tempo médio
de conclusão; exportação CSV (abre no Excel) e PDF.

* **Contagem:** cada laudo liberado conta uma vez, na data da primeira liberação (versão ``final``); adendos aparecem
  à parte e não somam como laudo.
* **Tempo de conclusão:** da chegada do estudo ao cadastro clínico (recepção no PACS) até a liberação.
* **Pendências:** exames atribuídos ao médico ainda abertos na fila e rascunhos dele não liberados.
* **Privacidade:** um médico vê só a própria produção (``report.production.own``); a de outros exige
  ``report.production.all``. Valores financeiros só com ``report.production.financial`` e só se a instituição tiver
  configurado a tabela de valores (``report/production``). Sem dados de pacientes na exportação.
"""

from __future__ import annotations

import csv
import io
import statistics
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from vyonix.errors import NotFound, ValidationFailed

BRT = timezone(timedelta(hours=-3))
MAX_DAYS = 400


def _period(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    today = datetime.now(BRT).date()
    d1 = date_to or today
    d0 = date_from or d1.replace(day=1)
    if d0 > d1:
        raise ValidationFailed("A data inicial é depois da data final.")
    if (d1 - d0).days > MAX_DAYS:
        raise ValidationFailed(f"Período longo demais (máximo {MAX_DAYS} dias).")
    return d0, d1


def physician_of_user(s: Session, user_id: uuid.UUID):
    from vyonix.report.models import Physician
    return s.execute(select(Physician).where(Physician.user_id == user_id)).scalars().first()


def values_table(s: Session) -> dict[str, int]:
    from vyonix.settings import service as settings
    try:
        rows = settings.get(s, "report", "production").get("values", [])
    except Exception:  # noqa: BLE001
        return {}
    return {r["modality"].upper(): int(r["value_cents"]) for r in rows}


def compute(s: Session, physician_id: uuid.UUID, *, date_from: date | None = None, date_to: date | None = None,
            financial: bool = False) -> dict[str, Any]:
    from vyonix.clinical.models import Study
    from vyonix.report.models import Assignment, Physician, Report, ReportVersion
    from vyonix.tenancy.models import Site
    ph = s.get(Physician, physician_id)
    if ph is None:
        raise NotFound("Médico não encontrado.")
    d0, d1 = _period(date_from, date_to)
    t0 = datetime.combine(d0, time.min, BRT)
    t1 = datetime.combine(d1 + timedelta(days=1), time.min, BRT)
    first = (select(ReportVersion.report_id, func.min(ReportVersion.signed_at).label("signed_at"))
             .where(ReportVersion.kind == "final", ReportVersion.signed_by_id == ph.user_id)
             .group_by(ReportVersion.report_id).subquery())
    rows = s.execute(
        select(first.c.report_id, first.c.signed_at, Study.modality, Study.site_id, Study.created_at)
        .join(Report, Report.id == first.c.report_id).join(Study, Study.id == Report.study_id)
        .where(and_(first.c.signed_at >= t0, first.c.signed_at < t1))
        .order_by(first.c.signed_at)).all()
    addenda = s.execute(select(func.count()).select_from(ReportVersion).where(
        ReportVersion.kind == "addendum", ReportVersion.signed_by_id == ph.user_id,
        ReportVersion.signed_at >= t0, ReportVersion.signed_at < t1)).scalar() or 0
    sites = {x.id: x.name for x in s.execute(select(Site)).scalars()}
    prices = values_table(s) if financial else {}
    by_day: Counter = Counter()
    by_month: Counter = Counter()
    by_site: Counter = Counter()
    by_mod: Counter = Counter()
    value_mod: dict[str, int] = defaultdict(int)
    hours: list[float] = []
    items = []
    for rid, signed_at, modality, site_id, received in rows:
        local = signed_at.astimezone(BRT)
        mod = (modality or "—").upper()
        site = sites.get(site_id, "Toda a instituição") if site_id else "Sem unidade"
        by_day[local.date().isoformat()] += 1
        by_month[local.strftime("%Y-%m")] += 1
        by_site[site] += 1
        by_mod[mod] += 1
        h = max(0.0, (signed_at - received).total_seconds() / 3600) if received else None
        if h is not None:
            hours.append(h)
        v = prices.get(mod) if financial else None
        if v is not None:
            value_mod[mod] += v
        items.append({"report_id": str(rid), "signed_at": signed_at.isoformat(), "modality": mod, "site": site,
                      "hours": round(h, 1) if h is not None else None, **({"value_cents": v} if financial else {})})
    pending_assigned = s.execute(select(func.count()).select_from(Assignment).where(
        Assignment.physician_id == ph.id, Assignment.status == "open")).scalar() or 0
    pending_drafts = s.execute(select(func.count()).select_from(Report).where(
        Report.status == "draft", Report.author == _username(s, ph.user_id))).scalar() or 0
    out: dict[str, Any] = {
        "physician": {"id": str(ph.id), "name": ph.full_name, "crm": f"{ph.crm}/{ph.crm_uf}"},
        "period": {"from": d0.isoformat(), "to": d1.isoformat()},
        "finalized": len(rows), "addenda": int(addenda),
        "pending": {"assigned": int(pending_assigned), "drafts": int(pending_drafts)},
        "turnaround_hours": {"mean": round(statistics.fmean(hours), 1) if hours else None,
                             "median": round(statistics.median(hours), 1) if hours else None},
        "by_day": sorted(by_day.items()), "by_month": sorted(by_month.items()),
        "by_site": sorted(by_site.items(), key=lambda x: (-x[1], x[0])),
        "by_modality": sorted(by_mod.items(), key=lambda x: (-x[1], x[0])),
        "items": items, "financial": financial,
    }
    if financial:
        out["values"] = {"configured": bool(prices), "total_cents": sum(value_mod.values()),
                         "by_modality": sorted(value_mod.items()),
                         "missing": sorted(m for m in by_mod if m not in prices)}
    return out


def _username(s: Session, user_id: uuid.UUID) -> str | None:
    from vyonix.auth.models import User
    u = s.get(User, user_id)
    return u.username if u else None


def to_csv(data: dict[str, Any]) -> bytes:
    """CSV com separador ";" e BOM UTF-8 (abre direto no Excel em português)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    p = data["physician"]
    w.writerow(["Produção médica", p["name"], f"CRM {p['crm']}"])
    w.writerow(["Período", data["period"]["from"], data["period"]["to"]])
    w.writerow(["Laudos liberados", data["finalized"], "Adendos", data["addenda"]])
    w.writerow(["Pendentes atribuídos", data["pending"]["assigned"], "Rascunhos", data["pending"]["drafts"]])
    th = data["turnaround_hours"]
    w.writerow(["Tempo médio de conclusão (h)", _num(th["mean"]), "Mediana (h)", _num(th["median"])])
    w.writerow([])
    head = ["Liberado em", "Modalidade", "Unidade", "Tempo de conclusão (h)"]
    if data["financial"]:
        head.append("Valor (R$)")
    w.writerow(head)
    for it in data["items"]:
        row = [datetime.fromisoformat(it["signed_at"]).astimezone(BRT).strftime("%d/%m/%Y %H:%M"), it["modality"],
               it["site"], _num(it["hours"])]
        if data["financial"]:
            row.append(_money(it.get("value_cents")))
        w.writerow(row)
    if data["financial"]:
        w.writerow([])
        w.writerow(["Total (R$)", _money(data["values"]["total_cents"])])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _num(v) -> str:
    return "" if v is None else f"{v:.1f}".replace(".", ",")


def _money(cents) -> str:
    if cents is None:
        return ""
    return f"{cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def to_pdf(data: dict[str, Any], *, institution: str) -> bytes:
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from vyonix.report.pdf import _fonts
    reg, bold = _fonts("Sans")
    st = ParagraphStyle("b", fontName=reg, fontSize=9.5, leading=13)
    h1 = ParagraphStyle("h1", parent=st, fontName=bold, fontSize=14, leading=18)
    h2 = ParagraphStyle("h2", parent=st, fontName=bold, fontSize=11, leading=15, spaceBefore=6)
    p = data["physician"]
    th = data["turnaround_hours"]
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title="Produção médica", author="VYONIX")
    d0 = date.fromisoformat(data["period"]["from"]).strftime("%d/%m/%Y")
    d1 = date.fromisoformat(data["period"]["to"]).strftime("%d/%m/%Y")
    story = [Paragraph(escape(institution), st), Paragraph("Produção médica", h1),
             Paragraph(escape(f"{p['name']} — CRM {p['crm']} · período {d0} a {d1}"), st), Spacer(1, 6)]

    def table(rows, widths=None, head=True):
        t = Table(rows, colWidths=widths, hAlign="LEFT")
        style = [("FONT", (0, 0), (-1, -1), reg, 9), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9d3db")),
                 ("VALIGN", (0, 0), (-1, -1), "TOP")]
        if head:
            style += [("FONT", (0, 0), (-1, 0), bold, 9), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6f0f2"))]
        t.setStyle(TableStyle(style))
        return t
    summary = [["Laudos liberados", str(data["finalized"])], ["Adendos", str(data["addenda"])],
               ["Pendentes atribuídos", str(data["pending"]["assigned"])],
               ["Rascunhos não liberados", str(data["pending"]["drafts"])],
               ["Tempo médio de conclusão", f"{_num(th['mean'])} h" if th["mean"] is not None else "—"],
               ["Mediana", f"{_num(th['median'])} h" if th["median"] is not None else "—"]]
    if data["financial"]:
        summary.append(["Valor total (tabela da instituição)", f"R$ {_money(data['values']['total_cents'])}"])
    story += [table(summary, [70 * mm, 50 * mm], head=False)]
    for title, key in (("Por modalidade", "by_modality"), ("Por unidade", "by_site"), ("Por mês", "by_month"),
                       ("Por dia", "by_day")):
        if data[key]:
            label = {"by_month": "Mês", "by_day": "Dia", "by_site": "Unidade", "by_modality": "Modalidade"}[key]
            rows = [[label, "Laudos"]] + [[_fmt_key(key, k), str(v)] for k, v in data[key]]
            story += [Paragraph(title, h2), table(rows, [70 * mm, 30 * mm])]
    story += [Spacer(1, 8), Paragraph("Relatório gerado pelo VYONIX. Contagem de laudos liberados (primeira liberação); "
                                      "não contém dados de pacientes.", st)]
    doc.build(story)
    return out.getvalue()


def _fmt_key(key: str, k: str) -> str:
    if key == "by_day":
        return date.fromisoformat(k).strftime("%d/%m/%Y")
    if key == "by_month":
        y, m = k.split("-")
        return f"{m}/{y}"
    return k
