"""Monta o pacote ``VYONIX_RELEASE_<versão>`` a partir dos resultados REAIS do build.

Entradas (geradas pelo pipeline):
  --installer   instalador .exe produzido pelo Inno Setup
  --junit       resultado do pytest (JUnit XML)
  --validation  pasta com results.json e relatórios de tools/ci_validate.ps1
  --env         arquivo texto com versões das ferramentas (pip freeze etc.)

Saída:
  dist/VYONIX_RELEASE_<v>/{Instalador,Documentacao,Testes,Integridade}/ + README.txt
  dist/VYONIX_RELEASE_<v>.zip
O relatório de validação é escrito apenas com o que os arquivos de entrada contêm.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from md2pdf import convert  # noqa: E402

DOCS = [
    ("Manual_Instalacao", "Manual de Instalação"),
    ("Manual_Usuario", "Manual do Usuário"),
    ("Guia_Configuracao_DICOM", "Guia de Configuração DICOM"),
    ("Notas_da_Versao", "Notas da Versão"),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mb(path: Path) -> str:
    return f"{path.stat().st_size / 1_048_576:.1f} MB"


def parse_junit(path: Path) -> dict:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    cases = []
    for suite in suites:
        for case in suite.iter("testcase"):
            status = "aprovado"
            detail = ""
            for tag, label in (("failure", "falhou"), ("error", "erro"), ("skipped", "ignorado")):
                el = case.find(tag)
                if el is not None:
                    status = label
                    detail = (el.get("message") or "")[:160]
            cases.append({"classname": case.get("classname", ""), "name": case.get("name", ""),
                          "time": float(case.get("time") or 0), "status": status,
                          "detail": detail})
    totals = {s: sum(1 for c in cases if c["status"] == s)
              for s in ("aprovado", "falhou", "erro", "ignorado")}
    return {"cases": cases, "totals": totals, "total": len(cases)}


def md_escape(text: str) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def perf_section(perf: dict | None) -> list[str]:
    if not perf:
        return []
    ui = perf.get("ui_first_start", {})
    d = perf.get("disk", {})
    fmt = lambda v: f"{v:.1f}".replace(".", ",")  # noqa: E731
    rows = [
        ("Pasta instalada", f"{fmt(d['onedir_mb'])} MB ({d['onedir_files']} arquivos)"),
        ("Instalador", f"{fmt(d['installer_mb'])} MB"),
        ("Memória em uso com a janela aberta (working set, média de 30 s)", f"{fmt(ui['working_set_mb_avg'])} MB"),
        ("Memória privada com a janela aberta", f"{fmt(ui['private_mb_avg'])} MB"),
        ("CPU com a janela ociosa (30 s)", f"{fmt(ui['cpu_percent_of_one_core'])}% de um núcleo"),
        ("Tempo até a janela aparecer (mediana; 4 núcleos / 1 núcleo)",
         f"{perf['ui_window_ms_all_cores_median']} ms / {perf['ui_window_ms_one_core_median']} ms"),
        ("Tempo do --check (mediana de 5)", f"{perf['check_ms_median']} ms"),
    ]
    out = ["## 4. Desempenho medido", "",
           f"Medido no executável final, na mesma máquina ({perf.get('cpu', '').strip()}, "
           f"{perf.get('cores')} núcleos, {fmt(perf.get('ram_gb', 0))} GB, SSD). Em PCs antigos com HDD, "
           "os tempos tendem a ser maiores; tamanho e memória variam pouco entre máquinas.", "",
           "| Medida | Valor |", "|---|---|"]
    out += [f"| {a} | {b} |" for a, b in rows]
    return out + [""]


def validation_report(version: str, commit: str, build_date: str, installer: Path,
                      digest: str, junit: dict, validation: dict, env_text: str,
                      perf: dict | None = None) -> str:
    v_results = validation["results"]
    v_ok = sum(1 for r in v_results if r["ok"])
    t = junit["totals"]
    lines = [
        "# Relatório de Validação",
        "",
        f"**VYONIX DICOM Print {version}** · commit `{commit}` · gerado em {build_date}",
        "",
        "> Este relatório é gerado automaticamente a partir dos resultados do pipeline de "
        "compilação. Ele registra testes técnicos de software. **Não constitui validação "
        "clínica, homologação regulatória nem declaração de conformidade DICOM.**",
        "",
        "## 1. Resumo",
        "",
        "| Etapa | Resultado |",
        "|---|---|",
        f"| Testes automatizados (pytest) | {t['aprovado']} aprovados, {t['falhou']} falhas, "
        f"{t['erro']} erros, {t['ignorado']} ignorados (total {junit['total']}) |",
        f"| Validação do executável e do instalador | {v_ok} de {len(v_results)} verificações aprovadas |",
        f"| Instalador | `{installer.name}` ({mb(installer)}) |",
        f"| SHA-256 do instalador | `{digest}` |",
        "",
        "## 2. Ambiente de teste",
        "",
        "| Item | Valor |",
        "|---|---|",
    ]
    for k, label in (("os", "Sistema operacional"), ("build", "Build do Windows"),
                     ("arch", "Arquitetura"), ("runner", "Máquina"), ("is_admin", "Executado como administrador")):
        lines.append(f"| {label} | {md_escape(validation['machine'].get(k, ''))} |")
    lines += ["", "Versões de ferramentas e bibliotecas usadas no build:", "", "```",
              env_text.strip(), "```", "",
              "## 3. Validação do executável e do instalador", "",
              "| ID | Área | Verificação | Resultado | Evidência |", "|---|---|---|---|---|"]
    for r in v_results:
        lines.append(f"| {r['id']} | {r['area']} | {md_escape(r['name'])} | "
                     f"{'Aprovado' if r['ok'] else '**FALHOU**'} | {md_escape(r['detail'])} |")
    lines += [""] + perf_section(perf)
    n = 5 if perf else 4
    lines += [f"## {n}. Testes automatizados", "",
              "| Módulo | Teste | Resultado |", "|---|---|---|"]
    for c in junit["cases"]:
        mod = c["classname"].replace("tests.", "")
        res = c["status"] + (f" — {md_escape(c['detail'])}" if c["detail"] else "")
        lines.append(f"| {md_escape(mod)} | {md_escape(c['name'])} | {res} |")
    lines += [
        "", f"## {n + 1}. Não verificado neste relatório", "",
        "Os itens abaixo não podem ser verificados pelo pipeline automatizado e devem ser "
        "registrados na homologação manual:", "",
        "| Item | Motivo |", "|---|---|",
        "| Instalação em Windows limpo sem Python instalado | O runner possui Python; o teste "
        "INS-05 apenas remove o Python do PATH do processo. Requer VM limpa. |",
        "| Windows 7 SP1 64 bits (requisito mínimo) | Não há máquinas Windows 7 no GitHub Actions. O executável usa Python 3.8 e Qt 5.15, compatíveis com Windows 7, mas o teste em Windows 7 real é obrigatório na homologação. |",
        "| Windows 10 e 11 | O pipeline executa em Windows Server 2022 (mesmo núcleo do Windows 10/11). |",
        "| Usuário sem privilégios administrativos | O pipeline executa como administrador. |",
        "| Aparência visual da interface | O smoke test verifica funcionamento, não a aparência. |",
        "| Recepção e impressão DICOM com equipamentos reais | Verificadas apenas com equipamento simulado (pynetdicom). |",
        "| Impressão em papel em impressoras físicas | Não verificada: o CI usa a impressora Microsoft Print to PDF. |",
        "| Licenciamento | Funcionalidade não implementada nesta versão (Fase 8). |",
        "| Assinatura digital de código | Não aplicada nesta compilação. |",
    ]
    return "\n".join(lines) + "\n"


README = """VYONIX DICOM Print {version}
Precisão em cada imagem.
======================================================================

VERSÃO DE DESENVOLVIMENTO PARA HOMOLOGAÇÃO ({phase}).
NÃO VALIDADA PARA USO CLÍNICO. SEM DECLARAÇÃO DE CONFORMIDADE DICOM.

Conteúdo
  Instalador\\{installer}
  Documentacao\\Manual_Instalacao.pdf
  Documentacao\\Manual_Usuario.pdf
  Documentacao\\Guia_Configuracao_DICOM.pdf
  Documentacao\\Notas_da_Versao.pdf
  Testes\\Relatorio_de_Validacao.pdf
  Integridade\\SHA256SUMS.txt

Instalação
  1. Confira o SHA-256 do instalador (PowerShell):
       Get-FileHash .\\Instalador\\{installer} -Algorithm SHA256
     Valor esperado:
       {digest}
  2. Execute o instalador e siga o assistente (requer administrador).
  3. Abra "VYONIX DICOM Print" pelo menu Iniciar.

Esta versão inclui a interface, o banco de dados, configurações, histórico e logs.
Recepção DICOM, processamento de imagens, impressão, regras, serviço Windows e
licenciamento ainda não estão implementados — veja Notas_da_Versao.pdf.

Compilação: {build_date} · commit {commit}
"""


def _phase() -> str:
    init = (Path(__file__).resolve().parent.parent / "app" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__phase__\s*=\s*"([^"]+)"', init)
    return m.group(1) if m else "fase não informada"


PHASE = _phase()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--installer", required=True, type=Path)
    ap.add_argument("--junit", required=True, type=Path)
    ap.add_argument("--validation", required=True, type=Path)
    ap.add_argument("--env", required=True, type=Path)
    ap.add_argument("--out", default=ROOT / "dist", type=Path)
    ap.add_argument("--perf", type=Path, help="JSON de tools/ci_profile.ps1 (opcional)")
    a = ap.parse_args()

    build_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    commit = a.commit[:12]
    name = f"VYONIX_RELEASE_{a.version}"
    rel = a.out / name
    if rel.exists():
        shutil.rmtree(rel)
    for sub in ("Instalador", "Documentacao", "Testes", "Integridade"):
        (rel / sub).mkdir(parents=True)

    installer = rel / "Instalador" / a.installer.name
    shutil.copy2(a.installer, installer)
    digest = sha256(installer)

    tmp = a.out / "_docs_md"
    tmp.mkdir(parents=True, exist_ok=True)
    for stem, title in DOCS:
        text = (ROOT / "docs" / "release" / f"{stem}.md").read_text(encoding="utf-8")
        text = (text.replace("{VERSION}", a.version).replace("{BUILD_DATE}", build_date)
                .replace("{COMMIT}", commit))
        src = tmp / f"{stem}.md"
        src.write_text(text, encoding="utf-8")
        convert(src, rel / "Documentacao" / f"{stem}.pdf", title=title, version=a.version)

    junit = parse_junit(a.junit)
    validation = json.loads((a.validation / "results.json").read_text(encoding="utf-8-sig"))
    report_md = validation_report(a.version, commit, build_date, installer, digest, junit,
                                  validation, a.env.read_text(encoding="utf-8", errors="replace"),
                                  json.loads(a.perf.read_text(encoding="utf-8-sig")) if a.perf and a.perf.exists() else None)
    (tmp / "Relatorio_de_Validacao.md").write_text(report_md, encoding="utf-8")
    convert(tmp / "Relatorio_de_Validacao.md", rel / "Testes" / "Relatorio_de_Validacao.pdf",
            title="Relatório de Validação", version=a.version)
    # Evidências brutas (JSON) junto do relatório.
    evid = rel / "Testes" / "evidencias"
    evid.mkdir()
    extra = [a.perf] if a.perf and a.perf.exists() else []
    for f in sorted(a.validation.glob("*.json")) + [a.junit] + extra:
        shutil.copy2(f, evid / f.name)

    (rel / "README.txt").write_text(
        README.format(version=a.version, phase=PHASE, installer=installer.name, digest=digest,
                      build_date=build_date, commit=commit), encoding="utf-8-sig")

    files = sorted(p for p in rel.rglob("*") if p.is_file() and p.parent.name != "Integridade")
    sums = "".join(f"{sha256(p)} *{p.relative_to(rel).as_posix()}\n" for p in files)
    (rel / "Integridade" / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")

    zip_path = a.out / f"{name}.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(rel.rglob("*")):
            if p.is_file():
                z.write(p, f"{name}/{p.relative_to(rel).as_posix()}")
    shutil.rmtree(tmp, ignore_errors=True)

    summary = {"installer": installer.name, "installer_sha256": digest,
               "installer_size": installer.stat().st_size, "zip": zip_path.name,
               "zip_sha256": sha256(zip_path), "zip_size": zip_path.stat().st_size,
               "tests": junit["totals"], "validation_passed": sum(r["ok"] for r in validation["results"]),
               "validation_total": len(validation["results"]), "phase": PHASE}
    (a.out / "release-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
