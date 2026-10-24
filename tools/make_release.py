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
    ("Manual_VYONIX_Reception", "Manual do VYONIX Reception"),
    ("Notas_da_Versao", "Notas da Versão"),
    ("Declaracao_Conformidade_DICOM", "Declaração de Conformidade DICOM"),
    ("Licenciamento_e_Ativacao", "Licenciamento e Ativação"),
    ("Funcionalidades", "Funcionalidades Implementadas e Pendentes"),
    ("Roteiro_Testes_Manuais", "Roteiro de Testes Manuais"),
]
# Pacote administrativo (NÃO vai ao cliente).
LM_DOCS = [
    ("Manual_License_Manager", "Manual do VYONIX License Manager"),
    ("Manual_Licenciamento_Comercial", "Licenciamento Comercial por Assinatura"),
    ("Licenciamento_e_Ativacao", "Licenciamento e Ativação"),
]
# Servidor central de licenças (NÃO vai ao cliente).
LS_DOCS = [
    ("Manual_License_Server", "Manual do VYONIX License Server"),
    ("Manual_Licenciamento_Comercial", "Licenciamento Comercial por Assinatura"),
    ("Integracao_Banco_Inter", "Integração com o Banco Inter"),
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


# Testes da arquitetura DICOM simplificada e do VYONIX Reception (prompt de desenvolvimento, seção 20).
RECEPTION_TESTS = [
    (1, "Criação de regra sem IP do equipamento", [r"r01_"], []),
    (2, "Associação usando Called AE Title correto", [r"r02_"], []),
    (3, "Rejeição ou tratamento de AE Title desconhecido", [r"r03_"], []),
    (4, "Duas regras com AE Titles diferentes na mesma porta", [r"r04_"], []),
    (5, "Mesmo Called AE Title e Calling AE Titles diferentes", [r"r05_"], []),
    (6, "Tratamento de regras ambíguas", [r"r06_"], []),
    (7, "Mudança de IP do equipamento sem editar a regra", [r"r07_"], []),
    (8, "Restrição opcional por IP", [r"r08_"], []),
    (9, "Restrição opcional por Calling AE Title", [r"r09_"], []),
    (10, "Recepção C-STORE", [r"r10_"], []),
    (11, "Recepção DICOM Print", [r"r11_|printer_status_and_full_film"], []),
    (12, "C-ECHO", [r"r12_|dedicated_listener"], ["SRV-02"]),
    (13, "Impressão automática", [r"r10_r13"], ["INS-06"]),
    (14, "Impressão sob demanda", [r"r14_"], []),
    (15, "Calibração individual", [r"r15_|two_ct_devices"], []),
    (16, "Impressão 3 × 3", [r"r15_r16|sheet_page_has_nine"], []),
    (17, "Cabeçalho e rodapé", [r"r16_r17|default_templates"], []),
    (18, "Pesquisa na recepção", [r"r18_"], ["RCP-01"]),
    (19, "Prevenção de duplicidade", [r"r19_"], []),
    (20, "Reimpressão", [r"r19_r20"], []),
    (21, "Controle de retirada", [r"r21_"], []),
    (22, "Recuperação após reinicialização", [r"r22_|recovery_after_crash"], []),
    (23, "Atualização sem perda de configuração", [r"r23_"], ["INS-07", "LIC-06"]),
    (24, "Validação de licença", [r"r24_|t14_"], ["LIC-04", "LIC-05"]),
]


# Licenciamento comercial por assinatura (prompt consolidado, seção 22).
COMMERCIAL_TESTS = [
    (1, "Licença mensal ativa", [r"c01_"], ["LM-01"]),
    (2, "Aviso antes do vencimento", [r"c02_"], []),
    (3, "Pagamento em atraso", [r"c03_"], []),
    (4, "Carência", [r"c04_"], []),
    (5, "Suspensão programada", [r"c05_"], []),
    (6, "Suspensão efetiva", [r"c06_"], []),
    (7, "Reativação online", [r"c07_"], ["LS-01"]),
    (8, "Reativação offline", [r"c08_"], ["LM-01"]),
    (9, "Falta de internet", [r"c09_"], []),
    (10, "Servidor de licenças indisponível", [r"c10_"], []),
    (11, "Pagamento confirmado", [r"c11_"], ["LM-01"]),
    (12, "Boleto emitido, mas não pago", [r"c12_"], []),
    (13, "Notificação bancária duplicada", [r"c13_"], []),
    (14, "Tentativa de reutilizar autorização antiga", [r"c14_"], ["LS-01"]),
    (15, "Licença adulterada", [r"c15_"], ["LIC-05"]),
    (16, "Alteração do relógio", [r"c16_"], []),
    (17, "Reinstalação", [r"c17_"], ["LIC-07"]),
    (18, "Atualização oficial", [r"c18_|database_upgrade"], ["INS-07", "LIC-06"]),
    (19, "Alteração legítima de hardware", [r"c19_"], []),
    (20, "Cópia da instalação para outro computador", [r"c20_"], []),
    (21, "Preservação de imagens", [r"c21_"], []),
    (22, "Exportação de dados durante suspensão", [r"c22_"], []),
    (23, "Trabalhos em andamento no momento da suspensão", [r"c23_"], []),
    (24, "Recuperação após reinicialização", [r"c24_"], []),
    (25, "Compatibilidade com as regras DICOM", [r"c25_"], ["SRV-02"]),
    (26, "Impressão automática", [r"c26_"], []),
    (27, "Impressão sob demanda", [r"c27_"], []),
    (28, "Controle de retirada", [r"c28_"], ["RCP-01"]),
    (29, "Auditoria administrativa", [r"c29_"], ["LM-01"]),
    (30, "Segurança das APIs", [r"c30_"], ["LS-01", "LS-02", "RCP-01"]),
]


def matrix(title: str, intro: str, items, junit: dict, by_id: dict) -> list[str]:
    lines = ["", title, "", intro, "",
             "| Nº | Teste obrigatório | Casos automatizados (aprovados/total) | Verificação no Windows | Situação |",
             "|---|---|---|---|---|"]
    for num, name, pats, ci_ids in items:
        cases = [c for c in junit["cases"] if any(re.search(p, c["name"], re.I) for p in pats)]
        ok_cases = [c for c in cases if c["status"] == "aprovado"]
        ci = [by_id[i] for i in ci_ids if i in by_id]
        ci_txt = ", ".join(f"{r['id']} {dict(aprovado='aprovado', nao_verificavel='não verificável', falhou='FALHOU')[v_status(r)]}"
                           for r in ci) or "—"
        not_verifiable = any("NÃO VERIFICÁVEL" in (r.get("detail") or "") for r in ci)
        failed = any(c["status"] in ("falhou", "erro") for c in cases) or any(not r["ok"] for r in ci)
        if failed:
            sit = "**Falhou**"
        elif not ok_cases and not ci:
            sit = "**Sem evidência**"
        elif not_verifiable:
            sit = "Comportamento verificado em simulação; **não verificável** com hardware real no CI"
        else:
            sit = "Aprovado"
        lines.append(f"| {num} | {name} | {len(ok_cases)}/{len(cases)} | {ci_txt} | {sit} |")
    return lines


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


def v_status(r: dict) -> str:
    """Situação de uma verificação: resultados antigos (sem ``status``) são reclassificados pelo detalhe."""
    if r.get("status"):
        return r["status"]
    if not r["ok"]:
        return "falhou"
    return "nao_verificavel" if "NÃO VERIFICÁVEL" in (r.get("detail") or "") else "aprovado"


V_LABEL = {"aprovado": "Aprovado", "nao_verificavel": "**Não verificável neste ambiente**", "falhou": "**FALHOU**"}


def validation_report(version: str, commit: str, build_date: str, installer: Path,
                      digest: str, junit: dict, validation: dict, env_text: str,
                      perf: dict | None = None) -> str:
    v_results = validation["results"]
    v_ok = sum(1 for r in v_results if v_status(r) == "aprovado")
    v_nv = sum(1 for r in v_results if v_status(r) == "nao_verificavel")
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
        f"| Validação do executável e do instalador | {v_ok} aprovadas, {v_nv} não verificáveis neste ambiente, "
        f"{len(v_results) - v_ok - v_nv} falhas (de {len(v_results)}) |",
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
                     f"{V_LABEL[v_status(r)]} | {md_escape(r['detail'])} |")
    by_id = {r["id"]: r for r in v_results}
    lines += matrix("## 3A. Matriz dos 30 testes do licenciamento comercial por assinatura",
                    "Prompt consolidado, seção 22. License Manager e License Server reais (HTTPS local com "
                    "certificado fixado); relógio, hardware e TPM simulados nos testes 1–20; aplicativo completo "
                    "(recepção DICOM, fila e Reception) nos testes 21–28. A API do Banco Inter é reproduzida "
                    "localmente com TLS mútuo (tests/inter_fake.py): o adaptador não foi testado contra o banco real.",
                    COMMERCIAL_TESTS, junit, by_id)
    lines += matrix("## 3B. Matriz dos 24 testes da arquitetura DICOM simplificada e do VYONIX Reception",
                    "Prompt de desenvolvimento (regras DICOM sem IP, Reception), seção 20.", RECEPTION_TESTS, junit, by_id)
    lines += matrix("## 3C. Matriz dos 35 testes do licenciamento (prompt definitivo)",
                    "Casos automatizados (pytest, com relógio, hardware e TPM simulados quando indicado) e "
                    "verificações com os executáveis reais no Windows.", REQUIRED_TESTS, junit, by_id)
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
        "| API real do Banco Inter (sandbox ou produção) | Exige conta PJ, credenciais e certificado da aplicação; o "
        "adaptador foi testado contra uma reprodução local da API com TLS mútuo. |",
        "| License Server publicado na internet (DNS, certificado de autoridade pública, firewall) | Testado em "
        "127.0.0.1 com certificado autoassinado fixado (LS-01/LS-02). |",
        "| Chave de produção do License Server (vyx-srv-2026-01) | O pipeline não tem a chave privada; o servidor foi "
        "testado com chaves geradas no teste. |",
    ]
    return "\n".join(lines) + "\n"


README = """VYONIX DICOM Print {version}
Precisão em cada imagem.
======================================================================

RELEASE CANDIDATA À HOMOLOGAÇÃO — NÃO LIBERADA PARA USO CLÍNICO ({phase}).
NÃO VALIDADA PARA USO CLÍNICO. Declaração de conformidade DICOM de homologação incluída.

Conteúdo
  Instalador\\{installer}
  Documentacao\\Manual_Instalacao.pdf
  Documentacao\\Manual_Usuario.pdf
  Documentacao\\Guia_Configuracao_DICOM.pdf
  Documentacao\\Manual_VYONIX_Reception.pdf
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


LS_README = """VYONIX License Server {ls_version} — SERVIDOR CENTRAL DE LICENÇAS (ADMINISTRATIVO)
======================================================================

NÃO DISTRIBUIR AOS CLIENTES. Validação online, assinaturas, cobrança e auditoria.

Conteúdo
  Programa\\VYONIX_License_Server.exe   (console; também roda do código-fonte: python -m license_server)
  Documentacao\\Manual_License_Server.pdf
  Documentacao\\Manual_Licenciamento_Comercial.pdf
  Documentacao\\Integracao_Banco_Inter.pdf
  Integridade\\SHA256SUMS.txt

Primeiros passos (detalhes no manual)
  VYONIX_License_Server.exe init --data D:\\VYONIX-LS --admin comercial --hostname licencas.suaempresa.com.br ^
      --key-file vyx-srv-2026-01.private.pem --key-id vyx-srv-2026-01
  set VYONIX_LS_KEY_PASSPHRASE=...   (ou signing_passphrase_file em server.json)
  VYONIX_License_Server.exe serve --data D:\\VYONIX-LS

A chave privada do servidor NÃO está no programa. A chave vyx-srv-2026-01 assina somente
autorizações de uso (não emite licenças).

SHA-256
  VYONIX_License_Server.exe  {exe_sha}

Compilação: {build_date} · commit {commit}
"""


def build_ls_package(a, build_date: str, commit: str) -> dict:
    from license_server import __version__ as ls_version
    name = f"VYONIX_LICENSE_SERVER_{ls_version}"
    rel = a.out / name
    if rel.exists():
        shutil.rmtree(rel)
    for sub in ("Programa", "Documentacao", "Integridade"):
        (rel / sub).mkdir(parents=True)
    exe = rel / "Programa" / a.ls_exe.name
    shutil.copy2(a.ls_exe, exe)
    tmp = a.out / "_docs_ls"
    tmp.mkdir(parents=True, exist_ok=True)
    for stem, title in LS_DOCS:
        text = (ROOT / "docs" / "release" / f"{stem}.md").read_text(encoding="utf-8")
        text = text.replace("{VERSION}", a.version).replace("{LS_VERSION}", ls_version).replace("{COMMIT}", commit)
        (tmp / f"{stem}.md").write_text(text, encoding="utf-8")
        convert(tmp / f"{stem}.md", rel / "Documentacao" / f"{stem}.pdf", title=title, version=ls_version)
    shutil.rmtree(tmp, ignore_errors=True)
    exe_sha = sha256(exe)
    (rel / "LEIA-ME.txt").write_text(LS_README.format(ls_version=ls_version, exe_sha=exe_sha, build_date=build_date,
                                                     commit=commit), encoding="utf-8-sig")
    files = sorted(p for p in rel.rglob("*") if p.is_file() and p.parent.name != "Integridade")
    (rel / "Integridade" / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(p)} *{p.relative_to(rel).as_posix()}\n" for p in files), encoding="utf-8")
    zip_path = a.out / f"{name}.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(rel.rglob("*")):
            if p.is_file():
                z.write(p, f"{name}/{p.relative_to(rel).as_posix()}")
    return {"ls_version": ls_version, "ls_exe": exe.name, "ls_exe_sha256": exe_sha, "ls_exe_size": exe.stat().st_size,
            "ls_zip": zip_path.name, "ls_zip_sha256": sha256(zip_path)}


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
    ap.add_argument("--ls-exe", type=Path, help="VYONIX_License_Server.exe (pacote administrativo separado)")
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
    ls = build_ls_package(a, build_date, commit) if a.ls_exe and a.ls_exe.exists() else {}
    summary = {"installer": installer.name, "installer_sha256": digest, **lm, **ls,
               "installer_size": installer.stat().st_size, "zip": zip_path.name,
               "zip_sha256": sha256(zip_path), "zip_size": zip_path.stat().st_size,
               "tests": junit["totals"], "validation_passed": sum(v_status(r) == "aprovado" for r in validation["results"]),
               "validation_not_verifiable": sum(v_status(r) == "nao_verificavel" for r in validation["results"]),
               "validation_total": len(validation["results"]), "phase": PHASE}
    (a.out / "release-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
