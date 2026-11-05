# A02 — PACS/DICOM — Relatório final Missão 4 (05/11/2026)

**Atividades executadas por mim (A02):** revisão do fase_a3_full.js contra o código 0.3.1 (correção da linha 6: `nodes.nodes`);
teste **local** (Linux, PostgreSQL de teste, motor simulado MemoryBackend — não Orthanc) do gerador DICOM e do STOW
(200, duplicado 0xB007, conciliação, QIDO/WADO, nó 201/409, eco 422); especificação PACS-01..22; análise do export.
**Não executei nada na instância do PC.** Os resultados reais abaixo foram coletados pelo coordenador; eu só os confrontei com o export.

## Estudos DEMO (export VYONIX_DEMO_EXPORT_20261105.json: qido + series)
| Acc. | Paciente | Mod | Sér | Inst | Study UID |
|---|---|---|---|---|---|
| O01 | DEMO-P01 | US | 2 | 4 | 2.25.215841522083267391817773762746358634308 |
| O02 | DEMO-P01 | CR | 2 | 4 | 2.25.281617941656179792711665157653426397988 |
| O03 | DEMO-P02 | CT | 2 | 4 | 2.25.88040400870485546917068463342800247644 |
| O04 | DEMO-P03 | CR | 2 | 4 | 2.25.137965392897247651995292323685686149399 |
| O05 | DEMO-P04 | CT | 2 | 4 | 2.25.199029235797520010529106478785471696424 |
| O06 | DEMO-P05 | US | 2 | 4 | 2.25.9429034989661032783620860247176761163 |
| O07 | DEMO-P06 | US | 2 | 4 | 2.25.256614410791250945606081602079485184880 |
| O08 | DEMO-P07 | DX | 2 | 4 | 2.25.4467605157873201968565678748353728166 |
| O09 | DEMO-P09 | CR | 2 | 4 | 2.25.115155062964800956184625165386692327390 |
| O10 | DEMO-P10 | MG | 1 | 4 | 2.25.66574255922018908977862559143896167042 |
| O11 | DEMO-P11 | MR | 2 | 4 | 2.25.329933417969882423133357301952701309973 |
| O12 | DEMO-P12 | US | 2 | 4 | 2.25.119436179640803419047955478543033777975 |
| O13 | DEMO-P13 | CR | 2 | 4 | 2.25.103754821280846903531870179131072165853 |
| O14 | DEMO-P14 | CT | 2 | 4 | 2.25.205166237282526309341884003454284638080 |
| O15 | DEMO-P15 | US | 2 | 4 | 2.25.209401286260703525119158519951899204316 |
| O16 | DEMO-P07 | US | 1 | 2 | 2.25.226415326585573240842487165294148423890 (UID do agendamento) |
| X08 | DEMO-P08 | US | 1 | 2 | 2.25.41641652847086794289812480202046815117 |
| A01 | DEMO-P04 | CT 2024-03-10 | 1 | 2 | 2.25.186680997619560313330758636551797927363 |
| A02 | DEMO-P04 | CR 2025-01-20 | 1 | 2 | 2.25.333622069109547229196501150752199415054 |
| A03 | DEMO-P01 | US 2025-08-15 | 1 | 2 | 2.25.268400098809440202939920563846679795529 |
Series UIDs completos: chave `series` e `ids.uids` do export. Fora do DEMO: 1 estudo do proprietário (PatientID 1475, 1×8), não tocado.
Conferência: DEMO = 70 instâncias (+8 do proprietário = 78 = pacs_status.index.instances = 78 `pacs.instance.store` na auditoria) → o reenvio duplicado **não** criou cópia; 0 `pacs.instance.reject`.
`study.reconcile` = 17 (O01–O16 automáticos + X08 manual); A01–A03 sem pedido (esperado). audit_verify ok=true.

## Status por teste (instância real, coletado pelo coordenador)
| Teste | Status |
|---|---|
| STOW 1ª tentativa (503 motor não configurado) → M4-INST-01 | REPROVADO (instalação) — P1 |
| STOW 19 estudos + O16 (UID MWL) | APROVADO |
| Duplicidade 0xB007 sem cópia (PACS-12) | APROVADO |
| Conciliação automática O01–O16 (PACS-16) | APROVADO |
| Conciliação manual X08 + negativos 409 (PACS-17) | APROVADO |
| QIDO P04 = 3; séries O05 = 2; contagens/UIDs (PACS-02..06) | APROVADO |
| WADO-RS instância (PACS-09) | APROVADO |
| Permissões negativas recepção/financeiro/suporte/coord (PACS-18/19) | APROVADO |
| Qualidade (PACS-22); auditoria íntegra (PACS-15) | APROVADO |
| Auditoria de WADO (PACS-14): 10 `pacs.study.open` no export | APROVADO (parcial: só contagem, sem detalhe por purpose) |
| C-ECHO nó sem porta 422 / VYONIX→Orthanc ok | APROVADO |
| Unidade dos estudos (F1, site_id nulo) / isolamento técnico (PACS-20) | REPROVADO como requisito — P1 (V-03) |
| Médico 02 lê metadata fora do escopo (T-UNI-MED02-04) | REPROVADO como requisito — P1 (viewer.access=organization) |
| WADO-URI (PACS-11) | BLOQUEADO (exige fluxo Weasis) |
| C-STORE / C-ECHO de entrada / C-FIND-C-MOVE (4242/4243) | BLOQUEADO (sem DCMTK no PC) |

## Recomendações
1. P1 M4-INST-01: o instalador não deve habilitar o módulo PACS sem o motor configurado; o health deveria apontar `pacs_orthanc_url` ausente.
2. P1 F1/V-03: gravar a unidade na entrada (nó/AE → unidade, ou herdar do atendimento na conciliação) e depois retirar a exceção V-03.
3. P1: decidir a política `pacs/viewer.access=linked` para médicos com vínculo restrito à unidade (o padrão atual expõe imagens de toda a organização).
4. P2: o proprietário roda `echoscu`/`storescu` (AE CT_DEMO_01 → VYONIX_PACS 127.0.0.1:4242) e `findscu` (→ VYONIX_QR 4243) com arquivos sintéticos.
5. P3: desativar (PATCH enabled:false) o nó auxiliar VYONIX_PACS após a homologação. Os nós simulados ficam "never" (sem contato).
