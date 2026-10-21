"""Relatório PDF e manifesto JSON de cada execução.

* ``VYONIX_Relatorio_Implantacao_<InstallationID>_<AAAAMMDD-HHMMSS>.pdf`` (ReportLab) e
  ``VYONIX_Manifesto_<InstallationID>_<AAAAMMDD-HHMMSS>.json`` em ``Deploy\\relatorios``; nunca
  sobrescritos (o nome leva data e hora; se já existir, a geração recusa).
* O manifesto (esquema ``vyonix-deploy-manifest/1``) registra o estado desejado e o observado de cada
  item gerenciado, o SHA-256 do PDF e o SHA-256 do manifesto anterior (cadeia). O SHA-256 do
  manifesto e do PDF fica também no banco do DEPLOY: alterações feitas fora do VYONIX são detectadas.
* Redação antes da geração; se algum padrão proibido escapar, nada é gravado.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vyonix_deploy import __version__, redact
from vyonix_deploy.db import DeployDB, now
from vyonix_deploy.engine import CATEGORIES
from vyonix_deploy.errors import DeployError

SCHEMA = "vyonix-deploy-manifest/1"
RESULT_LABEL = {"done": "Aplicado e conferido", "already": "Já estava conforme", "failed": "Falhou",
                "rolled_back": "Revertido", "rollback_failed": "Reversão falhou", "not_approved": "Não aprovado",
                "pending": "Não executado", "applying": "Interrompido", "planned": "Não executado",
                "diag_ok": "Conforme", "diag_problem": "Divergente"}
TEST_LABELS = ("Aprovado", "Reprovado", "Não executado", "Não aplicável", "Pendente de intervenção manual")
RUN_LABEL = {"succeeded": "Concluída", "rolled_back": "Falhou — alterações revertidas", "failed": "Falhou",
             "planned": "Plano não aprovado", "approved": "Aprovada, não iniciada", "running": "Interrompida",
             "diagnosed": "Diagnóstico (somente leitura)"}


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _installation_id(paths) -> str:
    try:
        from vyonix.licensing.service import Machine
        return Machine.build(paths.licensing, isolated=bool(os.environ.get("VYONIX_DEPLOY_ROOT"))) \
            .installation.current().installation_id
    except Exception:  # noqa: BLE001 - relatório sai mesmo sem o cofre
        return "VYXI-INDISPONIVEL"


def build_tests(run: dict, steps: list[dict], extra: list[dict] | None = None) -> list[dict]:
    tests = []
    for s in steps:
        res = {"done": "Aprovado", "already": "Aprovado", "failed": "Reprovado", "rolled_back": "Não executado",
               "rollback_failed": "Pendente de intervenção manual", "not_approved": "Não executado",
               "applying": "Pendente de intervenção manual", "diag_ok": "Aprovado",
               "diag_problem": "Reprovado"}.get(s["status"], "Não executado")
        tests.append({"name": f"Conferência: {s['title']}", "result": res, "detail": s.get("verify_msg") or s.get("error")
                      or RESULT_LABEL.get(s["status"], s["status"])})
    tests.append({"name": "Testes com modalidades DICOM", "result": "Não aplicável",
                  "detail": "Nenhum módulo DICOM da plataforma habilitado nesta versão."})
    return tests + (extra or [])


def future_interventions(run: dict, steps: list[dict], cfg: dict, observed: dict[str, Any]) -> list[str]:
    out = []
    cert = observed.get("https.certificate") or {}
    if cert.get("self_signed"):
        out.append("Pendência de segurança: o HTTPS usa certificado autoassinado. Instale o certificado da instituição "
                   "(Reconfigurar servidor) para eliminar o aviso dos navegadores.")
    if cert.get("not_after"):
        out.append(f"Renovar o certificado HTTPS antes de {cert['not_after'][:10]}.")
    for s in steps:
        if s["status"] in ("failed", "rollback_failed", "applying"):
            out.append(f"Resolver: {s['title']} — {(s.get('error') or '')[:200]}")
    if cfg.get("network", {}).get("mode") == "keep":
        out.append("O IP do servidor não foi alterado. Recomenda-se reserva de IP no DHCP para que estações e "
                   "equipamentos encontrem o servidor sempre no mesmo endereço.")
    out.append("Configurar a rotina de backup do banco (pasta Backups) e conferir a restauração periodicamente.")
    return out


def generate(db: DeployDB, paths, run_id: str, *, observed: dict[str, Any] | None = None,
             desired: dict[str, Any] | None = None, findings: list[dict] | None = None,
             extra_tests: list[dict] | None = None, secrets: list[str] | None = None) -> dict[str, str]:
    run = db.run(run_id)
    if run is None:
        raise DeployError("Execução inexistente.")
    steps = db.steps(run_id)
    cfg = json.loads(run["config_json"])
    inv = json.loads(run["inventory_json"] or "{}")
    plan = {p["id"]: p for p in json.loads(run["plan_json"] or "[]")}
    approval = json.loads(run["approval_json"]) if run["approval_json"] else None
    observed = observed or {}
    desired = desired or {}
    iid = _installation_id(paths)
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    paths.reports.mkdir(parents=True, exist_ok=True)
    pdf = paths.reports / f"VYONIX_Relatorio_Implantacao_{iid}_{stamp}.pdf"
    man = paths.reports / f"VYONIX_Manifesto_{iid}_{stamp}.json"
    if pdf.exists() or man.exists():
        raise DeployError("Relatório com o mesmo horário já existe; aguarde um segundo e gere de novo.")
    prev = db.x("SELECT sha256 FROM reports WHERE kind = 'manifest' ORDER BY id DESC LIMIT 1").fetchone()
    prev_sha = prev["sha256"] if prev else None
    items = []
    for s in steps:
        p = plan.get(s["step_id"], {})
        items.append({"id": s["step_id"], "category": s["category"], "title": s["title"],
                      "status": s["status"], "result": RESULT_LABEL.get(s["status"], s["status"]),
                      "before": json.loads(s["before_json"]) if s.get("before_json") else p.get("current"),
                      "proposed": p.get("proposed"), "desired": desired.get(s["step_id"], p.get("proposed")),
                      "observed": observed.get(s["step_id"], json.loads(s["after_json"]) if s.get("after_json") else None),
                      "verify": s.get("verify_msg"), "error": s.get("error"), "reboot": bool(p.get("reboot")),
                      "how_to_check": p.get("how_to_check") or "", "approved": bool(s.get("approved")),
                      "started_at": s.get("started_at"), "finished_at": s.get("finished_at")})
    tests = build_tests(run, steps, extra_tests)
    manifest = {
        "schema": SCHEMA, "installation_id": iid, "run_id": run_id, "kind": run["kind"], "status": run["status"],
        "status_label": RUN_LABEL.get(run["status"], run["status"]), "message": run.get("message"),
        "created_at": now(), "deploy_version": __version__, "host": socket.gethostname(),
        "os_user": run["os_user"], "approval": approval, "config": cfg, "compatibility": findings
        or json.loads(run["compat_json"] or "[]"),
        "inventory_summary": _inv_summary(inv), "items": items, "tests": tests,
        "future_interventions": future_interventions(run, steps, cfg, observed),
        "previous_manifest_sha256": prev_sha,
    }
    manifest = redact.value(manifest, secrets)
    _render_pdf(pdf, manifest, inv)
    manifest["pdf"] = {"file": pdf.name, "sha256": sha256_file(pdf)}
    body = json.dumps(manifest, ensure_ascii=False, indent=2, default=str)
    hits = redact.forbidden_hits(body, secrets)
    pdf_text = _pdf_text(pdf)
    hits += redact.forbidden_hits(pdf_text, secrets)
    if hits:
        pdf.unlink(missing_ok=True)
        raise DeployError(f"Relatório recusado pela redação (padrões proibidos: {', '.join(sorted(set(hits)))}).")
    man.write_text(body, encoding="utf-8")
    msha = sha256_file(man)
    db.x("INSERT INTO reports(run_id, kind, path, sha256, prev_sha256, created_at) VALUES (?,?,?,?,?,?)",
         (run_id, "pdf", str(pdf), manifest["pdf"]["sha256"], None, now()))
    db.x("INSERT INTO reports(run_id, kind, path, sha256, prev_sha256, created_at) VALUES (?,?,?,?,?,?)",
         (run_id, "manifest", str(man), msha, prev_sha, now()))
    for p in (pdf, man):
        try:
            os.chmod(p, 0o640)
        except OSError:
            pass
    return {"pdf": str(pdf), "manifest": str(man), "manifest_sha256": msha, "pdf_sha256": manifest["pdf"]["sha256"]}


def verify_chain(db: DeployDB) -> list[str]:
    """Relatórios alterados, apagados ou fora da cadeia (vazio = íntegros)."""
    problems = []
    prev = None
    for r in db.x("SELECT * FROM reports ORDER BY id").fetchall():
        p = Path(r["path"])
        if not p.exists():
            problems.append(f"{p.name}: arquivo ausente")
            continue
        if sha256_file(p) != r["sha256"]:
            problems.append(f"{p.name}: conteúdo alterado fora do VYONIX")
        if r["kind"] == "manifest":
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                problems.append(f"{p.name}: manifesto ilegível")
                continue
            if m.get("previous_manifest_sha256") != prev:
                problems.append(f"{p.name}: cadeia de manifestos rompida")
            prev = r["sha256"]
    return problems


def latest_manifest(db: DeployDB, *, kinds=("install", "repair", "update", "reconfigure", "activate")) -> dict | None:
    q = ",".join("?" * len(kinds))
    r = db.x(f"SELECT rp.path FROM reports rp JOIN runs ru ON ru.id = rp.run_id WHERE rp.kind = 'manifest' "
             f"AND ru.kind IN ({q}) AND ru.status = 'succeeded' ORDER BY rp.id DESC LIMIT 1", kinds).fetchone()
    if r is None:
        return None
    return json.loads(Path(r["path"]).read_text(encoding="utf-8"))


def _inv_summary(inv: dict) -> dict:
    return {"os": inv.get("os"), "computer": {k: v for k, v in (inv.get("computer") or {}).items()},
            "cpu": inv.get("cpu"), "disks": inv.get("disks"), "admin": inv.get("admin"),
            "nics": [{k: n.get(k) for k in ("alias", "status", "ipv4", "gateway", "dns", "dhcp", "virtual")}
                     for n in inv.get("nics") or []],
            "listening_ports": sorted({p["port"] for p in inv.get("ports") or []}),
            "services": inv.get("services"), "firewall_profiles": inv.get("firewall_profiles"),
            "firewall_rules_vyonix": inv.get("firewall_rules"), "certificates": inv.get("certificates"),
            "previous": inv.get("previous"), "reboot_pending": inv.get("reboot_pending")}


# ------------------------------------------------------------------------------------------- PDF

def _fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for reg, bold in (("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
                      ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                       "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
        if os.path.exists(reg) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("VXR", reg))
                pdfmetrics.registerFont(TTFont("VXB", bold))
                return "VXR", "VXB"
            except Exception:  # noqa: BLE001
                continue
    return "Helvetica", "Helvetica-Bold"


def _join(v: Any) -> str:
    return ", ".join(str(x) for x in (v or []) if x not in (None, "")) or "—"


def _plain(v: Any) -> str:
    if isinstance(v, bool):
        return "sim" if v else "não"
    if v is None:
        return "—"
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_plain(x)}" for k, x in v.items())
    if isinstance(v, (list, tuple)):
        return ", ".join(_plain(x) for x in v) or "—"
    return str(v)


def _fmt(v: Any, limit: int = 600) -> str:
    if v is None or v == {} or v == []:
        return "—"
    s = _plain(v)
    return s if len(s) <= limit else s[:limit] + " …"


def _render_pdf(path: Path, m: dict, inv: dict) -> None:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    reg, bold = _fonts()
    ink, muted, accent = colors.HexColor("#1b2a3a"), colors.HexColor("#4a5d70"), colors.HexColor("#0f7c86")
    st = {
        "h1": ParagraphStyle("h1", fontName=bold, fontSize=17, leading=21, textColor=ink, spaceAfter=4),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=12.5, leading=16, textColor=accent, spaceBefore=10,
                             spaceAfter=4),
        "p": ParagraphStyle("p", fontName=reg, fontSize=9, leading=12, textColor=ink, alignment=TA_LEFT),
        "s": ParagraphStyle("s", fontName=reg, fontSize=7.6, leading=9.6, textColor=ink),
        "sm": ParagraphStyle("sm", fontName=reg, fontSize=7.6, leading=9.6, textColor=muted),
        "th": ParagraphStyle("th", fontName=bold, fontSize=7.8, leading=9.8, textColor=colors.white),
    }

    def P(t, s="p"):
        return Paragraph(escape(str(t)).replace("\n", "<br/>"), st[s])

    def table(head, rows, widths):
        data = [[P(h, "th") for h in head]] + [[c if hasattr(c, "wrap") else P(_fmt(c), "s") for c in r] for r in rows]
        t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123047")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c9d4dc")),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6f8")]),
                               ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
        return t

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(reg, 7)
        canvas.setFillColor(muted)
        canvas.drawString(15 * mm, 9 * mm, f"VYONIX DEPLOY {m['deploy_version']} · {m['installation_id']} · "
                                           f"execução {m['run_id']}")
        canvas.drawRightString(195 * mm, 9 * mm, f"página {doc.page}")
        canvas.restoreState()

    kind = {"install": "Nova instalação", "repair": "Reparo", "update": "Atualização", "uninstall": "Desinstalação",
            "diagnose": "Diagnóstico", "reconfigure": "Reconfiguração", "activate": "Ativação de módulo"}
    story = [P("Relatório técnico de implantação — VYONIX", "h1"),
             P(f"{kind.get(m['kind'], m['kind'])} · {m['status_label']} · {m['created_at']}", "sm"),
             Spacer(1, 4),
             P("Documento gerado automaticamente a partir do estado real lido do Windows. Não contém senhas, tokens, "
               "chaves privadas nem dados de pacientes. Não declara conformidade regulatória nem adequação para uso "
               "clínico.", "sm")]
    story += [P("1. Identificação", "h2"),
              table(["Item", "Valor"], [
                  ["Installation ID", m["installation_id"]], ["Execução", m["run_id"]], ["Servidor", m["host"]],
                  ["Executado por", m.get("os_user")], ["Resultado", m.get("message") or m["status_label"]],
                  ["Aprovação", (f"{m['approval']['user']} em {m['approval']['at']} ({m['approval']['summary']}; "
                                 f"plano {m['approval']['plan_sha'][:16]}…)") if m.get("approval") else "—"],
                  ["Organização", f"{m['config'].get('organization')} — {m['config'].get('organization_name')}"],
                  ["Manifesto anterior (SHA-256)", m.get("previous_manifest_sha256") or "primeiro manifesto"]],
                  [45, 135])]
    i = m["inventory_summary"]
    os_ = i.get("os") or {}
    comp = i.get("computer") or {}
    story += [P("2. Inventário do servidor", "h2"),
              table(["Item", "Valor"], [
                  ["Sistema", f"{os_.get('caption')} · build {os_.get('build')} · {os_.get('arch')}"],
                  ["Computador", f"{comp.get('name')} · domínio {comp.get('domain') or '—'}"],
                  ["CPU / memória", f"{(i.get('cpu') or {}).get('name')} · {(i.get('cpu') or {}).get('logical')} "
                                    f"núcleos lógicos · {int(comp.get('memory') or 0) / 1024 ** 3:.1f} GB"],
                  ["Discos", "; ".join(f"{d.get('drive')} {int(d.get('free') or 0) / 1024 ** 3:.1f} GB livres de "
                                       f"{int(d.get('size') or 0) / 1024 ** 3:.0f} GB" for d in i.get("disks") or [])],
                  ["Portas em escuta", ", ".join(map(str, i.get("listening_ports") or [])) or "—"],
                  ["Reinicialização pendente", "sim" if i.get("reboot_pending") else "não"]], [45, 135])]
    story += [P("Compatibilidade", "h2"),
              table(["Resultado", "Item", "Detalhe"],
                    [[{"ok": "Atendido", "alert": "Alerta", "blocker": "Impeditivo", "info": "Informação"}
                      .get(f["level"], f["level"]), f["title"], f["detail"]] for f in m.get("compatibility") or []],
                    [22, 45, 113])]
    story += [P("3. Rede", "h2"),
              table(["Interface", "Estado", "IPv4", "Gateway", "DNS", "DHCP"],
                    [[n.get("alias"), n.get("status"), ", ".join(f"{a.get('ip')}/{a.get('prefix')}"
                                                                 for a in n.get("ipv4") or [] if a),
                      _join(n.get("gateway")), _join(n.get("dns")), n.get("dhcp")]
                     for n in i.get("nics") or []] or [["—"] * 6], [32, 18, 38, 30, 42, 20]),
              P("Escolha de rede: " + ("manter o IP atual (nenhuma alteração)" if m["config"]["network"]["mode"] == "keep"
                                       else f"IP fixo {m['config']['network'].get('ip')}/{m['config']['network'].get('prefix')}"),
                "sm")]
    story += [PageBreak(), P("4. Alterações", "h2"),
              P("Para cada item: estado anterior, proposto, estado final verificado no sistema e como conferir.", "sm")]
    rows = []
    for it in m["items"]:
        rows.append([P(f"{it['title']}\n[{CATEGORIES.get(it['category'], it['category'])}]", "s"),
                     P(it["result"] + ("\nexige reinicialização" if it["reboot"] else ""), "s"),
                     _fmt(it["before"], 350), _fmt(it["observed"] if it["observed"] is not None else it["proposed"], 350),
                     P(_fmt(it.get("verify") or it.get("error"), 220) + ("\nConferir: " + it["how_to_check"]
                                                                          if it.get("how_to_check") else ""), "s")])
    story.append(table(["Item", "Resultado", "Antes", "Final verificado", "Verificação"], rows, [36, 24, 42, 42, 36]))
    by_cat = lambda c: [it for it in m["items"] if it["category"] == c]  # noqa: E731
    for num, (cat, title) in enumerate((("firewall", "Firewall"), ("servico", "Serviços"), ("https", "Segurança e HTTPS")),
                                       start=5):
        its = by_cat(cat)
        story += [P(f"{num}. {title}", "h2")]
        story += [table(["Item", "Resultado", "Estado verificado"],
                        [[it["title"], it["result"], _fmt(it["observed"], 500)] for it in its], [55, 30, 95])] if its \
            else [P("Nenhum item desta categoria nesta execução.", "sm")]
    story += [P("8. DICOM", "h2"), P("Não aplicável nesta versão: nenhum módulo DICOM da plataforma está habilitado. "
                                    "O VYONIX DICOM Print, se instalado, não é alterado pelo DEPLOY.", "p")]
    story += [P("9. Testes", "h2"),
              table(["Teste", "Resultado", "Detalhe"], [[t["name"], t["result"], t.get("detail")] for t in m["tests"]],
                    [70, 30, 80])]
    story += [P("10. Intervenções futuras", "h2")] + [P("• " + x) for x in m["future_interventions"]]
    story += [Spacer(1, 6), P("Integridade: o SHA-256 deste PDF consta do manifesto JSON gerado junto, e o do manifesto "
                              "fica no banco do DEPLOY; os manifestos formam uma cadeia pelo resumo do anterior.", "sm")]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=15 * mm, title="Relatório técnico de implantação — VYONIX",
                            author="VYONIX DEPLOY", subject=m["run_id"])
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def _pdf_text(path: Path) -> str:
    """Texto extraído do PDF (para o teste de redação). Usa o próprio conteúdo dos streams."""
    import zlib
    raw = path.read_bytes()
    out = []
    import re
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        data = m.group(1)
        try:
            data = zlib.decompress(data)
        except zlib.error:
            pass
        out.append(data.decode("latin-1", "ignore"))
    return "\n".join(out)
