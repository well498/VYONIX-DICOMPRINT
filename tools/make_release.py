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
    ("Declaracao_Conformidade_DICOM", "Declaração de Conformidade DICOM"),
    ("Licenciamento_e_Ativacao", "Licenciamento e Ativação"),
    ("Funcionalidades", "Funcionalidades Implementadas e Pendentes"),
    ("Roteiro_Testes_Manuais", "Roteiro de Testes Manuais"),
]
# Pacote administrativo (NÃO vai ao cliente).
LM_DOCS = [
    ("Manual_License_Manager", "Manual do VYONIX License Manager"),
    ("Licenciamento_e_Ativacao", "Licenciamento e Ativação"),
]

# Matriz dos 35 testes obrigatórios (prompt definitivo, seção 20): testes automatizados (padrões nos
# nomes dos casos do pytest) e verificações no Windows (IDs de tools/ci_validate.ps1).
REQUIRED_TESTS = [
    (1, "Equipamentos da mesma modalidade com regras diferentes", [r"two_ct_devices"], []),
    (2, "Alterações isoladas por equipamento", [r"two_ct_devices|versions_restore_duplicate"], []),
    (3, "Controles de brilho, contraste e gama", [r"test_math|pipeline_uses_same_transform"], []),
    (4, "Incrementos de 0,5 e ajuste fino", [r"scale_steps"], []),
    (5, "Pré-visualização", [r"preview_equals_printed"], []),
    (6, "Impressão de nove imagens", [r"sheet_page_has_nine|matrix_values"], []),
    (7, "Seleção e salvamento de calibração", [r"progressive_rounds"], []),
    (8, "Impressão A4 e A3", [r"a4_and_a3|layout_a4_a3|letter_legal"], ["INS-06"]),
    (9, "BMP de 3000 × 206 pixels", [r"default_templates|custom_bmp"], []),
    (10, "Preservação das artes após atualização", [r"template_survives_update"], ["INS-07"]),
    (11, "Geração de Hardware ID", [r"t11_"], ["LIC-01"]),
    (12, "Geração de Installation ID", [r"t12_"], ["LIC-01"]),
    (13, "Emissão de licença assinada", [r"t13_"], ["LM-01"]),
    (14, "Ativação offline", [r"t14_"], ["LIC-03", "LM-01"]),
    (15, "Rejeição de licença adulterada", [r"t15_"], ["LIC-05"]),
    (16, "Rejeição em outro computador", [r"t16_"], []),
    (17, "Rejeição em outra instalação", [r"t17_"], []),
    (18, "Validação por TPM, quando disponível", [r"t18_"], ["LIC-02"]),
    (19, "Desinstalação e reinstalação", [r"t19_"], ["INS-08", "LIC-07"]),
    (20, "Exigência de nova ativação", [r"t20_|t19_t20"], ["LIC-07"]),
    (21, "Atualização oficial sem perda da licença", [r"t21_"], ["INS-07", "LIC-06"]),
    (22, "Substituição de HD", [r"t22_"], []),
    (23, "Troca de placa-mãe", [r"t23_"], []),
    (24, "Reativação administrativa", [r"t24_|t22_disk_replacement_and_t24"], ["LM-01"]),
    (25, "DEMO de 120 horas", [r"t25_"], ["LIC-04"]),
    (26, "Reinicialização durante a DEMO", [r"t26_"], ["LIC-06"]),
    (27, "Tentativa de retrocesso do relógio", [r"t27_"], []),
    (28, "Alteração de data futura", [r"t28_"], []),
    (29, "Correção legítima de horário", [r"t29_"], []),
    (30, "Vencimento de licença comercial", [r"t30_"], []),
    (31, "Licença permanente", [r"t31_"], []),
    (32, "Execução portátil do License Manager", [], ["LM-01"]),
    (33, "Instalação opcional do License Manager", [], ["LM-02"]),
    (34, "Proteção da chave privada", [r"t34_"], ["LM-01", "LM-03"]),
    (35, "Backup e restauração", [r"t35_|backup_restore_roundtrip"], ["LM-01"]),
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
    lines += ["", "## 3A. Matriz dos 35 testes obrigatórios", "",
              "Cada linha relaciona o requisito aos casos automatizados (pytest, com relógio, hardware e TPM "
              "simulados quando indicado) e às verificações executadas no Windows com os executáveis reais.", "",
              "| Nº | Teste obrigatório | Casos automatizados (aprovados/total) | Verificação no Windows | Situação |",
              "|---|---|---|---|---|"]
    by_id = {r["id"]: r for r in v_results}
    for num, title, pats, ci_ids in REQUIRED_TESTS:
        cases = [c for c in junit["cases"] if any(re.search(p, c["name"], re.I) for p in pats)]
        ok_cases = [c for c in cases if c["status"] == "Aprovado"]
        ci = [by_id[i] for i in ci_ids if i in by_id]
        ci_txt = ", ".join(f"{r['id']} {'aprovado' if r['ok'] else 'FALHOU'}" for r in ci) or "—"
        not_verifiable = any("NÃO VERIFICÁVEL" in (r.get("detail") or "") for r in ci)
        failed = any(c["status"] != "Aprovado" for c in cases if c["status"] not in ("Ignorado",)) or \
            any(not r["ok"] for r in ci)
        if failed:
            sit = "**Falhou**"
        elif not cases and not ci:
            sit = "**Sem evidência**"
        elif not_verifiable:
            sit = "Aprovado em simulação; hardware real indisponível no CI"
        else:
            sit = "Aprovado"
        lines.append(f"| {num} | {title} | {len(ok_cases)}/{len(cases)} | {ci_txt} | {sit} |")
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
        "| Windows 10 e 11 em estações reais | O pipeline executa em Windows Server 2022 (mesmo núcleo do Windows 10/11). |",
        "| TPM 2.0 físico | Se o runner não tiver TPM utilizável, LIC-02 registra a camada como não verificável; a "
        "prova de posse foi testada com TPM simulado (mesmo formato de chave do Windows). |",
        "| Troca real de disco/placa-mãe e alteração manual do relógio | Simuladas nos testes automatizados (relógio "
        "e hardware simulados), conforme o prompt; não executadas em hardware real. |",
        "| Ativação com a chave de produção | O pipeline não tem acesso à chave privada oficial; usa uma chave gerada "
        "no autoteste e comprova que licenças de chaves não oficiais são recusadas (LIC-05). |",
        "| Usuário sem privilégios administrativos | O pipeline executa como administrador. |",
        "| Aparência visual da interface | O smoke test verifica funcionamento, não a aparência. |",
        "| Recepção e impressão DICOM com equipamentos reais | Verificadas apenas com equipamento simulado (pynetdicom). |",
        "| Impressão em papel em impressoras físicas | Não verificada: o CI usa a impressora Microsoft Print to PDF. |",
        "| Assinatura digital de código | Não aplicada nesta compilação. |",
    ]
    return "\n".join(lines) + "\n"


README = """VYONIX DICOM Print {version}
Precisão em cada imagem.
======================================================================

VERSÃO PARA HOMOLOGAÇÃO ({phase}).
NÃO VALIDADA PARA USO CLÍNICO. Declaração de conformidade DICOM de homologação incluída.

Conteúdo
  Instalador\\{installer}
  Documentacao\\Manual_Instalacao.pdf
  Documentacao\\Manual_Usuario.pdf
  Documentacao\\Guia_Configuracao_DICOM.pdf
  Documentacao\\Notas_da_Versao.pdf
  Documentacao\\Declaracao_Conformidade_DICOM.pdf
  Documentacao\\Licenciamento_e_Ativacao.pdf
  Documentacao\\Funcionalidades.pdf
  Documentacao\\Roteiro_Testes_Manuais.pdf
  Testes\\Relatorio_de_Validacao.pdf
  Integridade\\SHA256SUMS.txt

Instalação
  1. Confira o SHA-256 do instalador (PowerShell):
       Get-FileHash .\\Instalador\\{installer} -Algorithm SHA256
     Valor esperado:
       {digest}
  2. Execute o instalador e siga o assistente (requer administrador).
  3. Abra "VYONIX DICOM Print" pelo menu Iniciar.

Ativação: na primeira abertura, inicie a demonstração de 5 dias (120 horas) ou
exporte a solicitação de ativação e envie ao administrador — veja
Licenciamento_e_Ativacao.pdf. Este pacote NÃO contém o VYONIX License Manager.

Compilação: {build_date} · commit {commit}
"""


LM_README = """VYONIX License Manager {lm_version} — USO ADMINISTRATIVO
======================================================================

NÃO DISTRIBUIR AOS CLIENTES. Este pacote emite licenças do VYONIX DICOM Print.

Conteúdo
  Programa\\VYONIX_License_Manager.exe        (portátil: duplo clique, sem instalação)
  Instalador\\VYONIX_License_Manager_Setup.exe (instalação opcional, mesmas funções)
  Documentacao\\Manual_License_Manager.pdf
  Documentacao\\Licenciamento_e_Ativacao.pdf
  Testes\\Relatorio_de_Validacao.pdf
  Integridade\\SHA256SUMS.txt

A chave privada de emissão NÃO está no programa: gere-a ou importe-a (arquivo .pem
cifrado + frase-senha) em Segurança → Chaves de emissão. Somente licenças assinadas pela
chave cuja parte pública está no VYONIX DICOM Print são aceitas.

SHA-256
  VYONIX_License_Manager.exe        {exe_sha}
  VYONIX_License_Manager_Setup.exe  {setup_sha}

Compilação: {build_date} · commit {commit}
"""


def build_lm_package(a, build_date: str, commit: str, report_pdf: Path) -> dict:
    from license_manager import __version__ as lm_version
    name = f"VYONIX_LICENSE_MANAGER_{lm_version}"
    rel = a.out / name
    if rel.exists():
        shutil.rmtree(rel)
    for sub in ("Programa", "Instalador", "Documentacao", "Testes", "Integridade"):
        (rel / sub).mkdir(parents=True)
    exe = rel / "Programa" / a.lm_exe.name
    shutil.copy2(a.lm_exe, exe)
    setup = None
    if a.lm_installer and a.lm_installer.exists():
        setup = rel / "Instalador" / a.lm_installer.name
        shutil.copy2(a.lm_installer, setup)
    tmp = a.out / "_docs_lm"
    tmp.mkdir(parents=True, exist_ok=True)
    for stem, title in LM_DOCS:
        text = (ROOT / "docs" / "release" / f"{stem}.md").read_text(encoding="utf-8")
        text = text.replace("{VERSION}", a.version).replace("{LM_VERSION}", lm_version).replace("{COMMIT}", commit)
        (tmp / f"{stem}.md").write_text(text, encoding="utf-8")
        convert(tmp / f"{stem}.md", rel / "Documentacao" / f"{stem}.pdf", title=title, version=lm_version)
    shutil.rmtree(tmp, ignore_errors=True)
    if report_pdf.exists():
        shutil.copy2(report_pdf, rel / "Testes" / report_pdf.name)
    exe_sha = sha256(exe)
    setup_sha = sha256(setup) if setup else "—"
    (rel / "LEIA-ME.txt").write_text(LM_README.format(lm_version=lm_version, exe_sha=exe_sha, setup_sha=setup_sha,
                                                     build_date=build_date, commit=commit), encoding="utf-8-sig")
    files = sorted(p for p in rel.rglob("*") if p.is_file() and p.parent.name != "Integridade")
    (rel / "Integridade" / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(p)} *{p.relative_to(rel).as_posix()}\n" for p in files), encoding="utf-8")
    zip_path = a.out / f"{name}.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(rel.rglob("*")):
            if p.is_file():
                z.write(p, f"{name}/{p.relative_to(rel).as_posix()}")
    return {"lm_version": lm_version, "lm_exe": exe.name, "lm_exe_sha256": exe_sha, "lm_exe_size": exe.stat().st_size,
            "lm_installer": setup.name if setup else None, "lm_installer_sha256": setup_sha,
            "lm_installer_size": setup.stat().st_size if setup else None, "lm_zip": zip_path.name,
            "lm_zip_sha256": sha256(zip_path)}


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
    ap.add_argument("--lm-exe", type=Path, help="VYONIX_License_Manager.exe (pacote administrativo separado)")
    ap.add_argument("--lm-installer", type=Path, help="VYONIX_License_Manager_Setup.exe")
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

    lm = build_lm_package(a, build_date, commit, rel / "Testes" / "Relatorio_de_Validacao.pdf") \
        if a.lm_exe and a.lm_exe.exists() else {}
    summary = {"installer": installer.name, "installer_sha256": digest, **lm,
               "installer_size": installer.stat().st_size, "zip": zip_path.name,
               "zip_sha256": sha256(zip_path), "zip_size": zip_path.stat().st_size,
               "tests": junit["totals"], "validation_passed": sum(r["ok"] for r in validation["results"]),
               "validation_total": len(validation["results"]), "phase": PHASE}
    (a.out / "release-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
