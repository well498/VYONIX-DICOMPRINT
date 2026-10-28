# VYONIX — Rastreabilidade de requisitos

Origem principal: **Prompt Mestre Final v1.0** (“PM”, seções §1–§74), recebido em 23/10/2026, e as instruções
anteriores do responsável pelo projeto (“RP”). Cada linha liga o requisito à implementação, aos testes e à evidência.
Situações: **Implementado** (código + testes + evidência) · **Parcial** · **Planejado** (entrega indicada) ·
**Aguarda aprovação** · **Fora do escopo**.

As evidências citadas são reproduzíveis: suítes de teste no repositório e execuções de CI identificadas pelo número
(`gh run view <id> -R well498/VYONIX-DICOMPRINT`). Nada aqui afirma validação clínica ou conformidade regulatória.

## 1. Requisitos aprovados

### Entrega 1 — VYONIX DICOM Print (PM §13–§21)

| ID | Requisito | Origem | Módulo | Prior. | Situação | Implementação | Testes / evidência | Versão |
|---|---|---|---|---|---|---|---|---|
| PRT-01 | Inspecionar o código original, criar versão de referência e testes de regressão antes de mudanças | PM §13 | Print | Essencial | Implementado | `docs/ARQUITETURA.md`; releases r2–r5 | 301 testes locais (`python -m unittest discover -s tests`); pipeline “Windows release” | 1.0.0-r5 |
| PRT-02 | Menus suspensos legíveis, contraste, fundos escuros, barras de rolagem, diálogos (QComboBox, QAbstractItemView, QScrollBar, QMenu, QDialog, QPalette, QSS) | PM §14 | Print/UI | Essencial | Implementado | `app/ui/tokens.py`, `app/ui/theme.py` (ADR-0013) | `tests/test_ui_tokens.py`; contraste renderizado medido pela matriz: lista suspensa 16,46:1 (claro) e 13,76:1 (escuro), menu idem, diálogo 15,2:1 e 15,55:1 — CI “UI Windows” run 40021144464 | r6 (não publicada) |
| PRT-03 | Testar 1366×768, 1600×900, 1920×1080, 2560×1440, 3840×2160, escalas DPI e múltiplos monitores, sem alterar a resolução; nada cortado, sobreposto ou fora da tela | PM §14 | Print/UI | Essencial | Implementado | `app/ui/responsive.py` (fluxo, grade responsiva, quebra de rótulos, diálogos roláveis), `app/ui/pages/base.py` (`FitScrollArea`), `MainWindow.show_fitted(screen)` | `tests/test_ui_matrix.py`: 11 configurações (100–200 %, 2 monitores) × 2 temas × 13 páginas + 6 diálogos — 11/11 sem problemas, CI run 40021144464 (a primeira execução encontrou 80 a 106 problemas por configuração) | r6 |
| PRT-04 | AE Title, portas, recepção DICOM, identificação da origem | PM §15 | Print | Essencial | Implementado | `app/dicom/storage_scp.py`, `routing.py`, `listeners.py` | `tests/test_storage_scp.py`, `test_reception.py`; CI r5 | r5 |
| PRT-05 | Seleção de impressora, filas, layouts, impressão automática e manual, reimpressão autorizada, erros, histórico | PM §15 | Print | Essencial | Implementado | `app/jobs/`, `app/printing/` | `tests/test_jobs.py`, `test_job_states.py`, `test_windows_printing.py` (Microsoft Print to PDF no CI) | r5 |
| PRT-06 | Regras por AE/modalidade/impressora/papel/layout/brilho/contraste/gama/cabeçalho/rodapé/imagens vazias | PM §16 | Print | Essencial | Implementado | `app/rules/engine.py`, `app/devices/settings.py` | `tests/test_rules.py`, `test_devices.py` | r5 |
| PRT-07 | Layouts 1×1, 2×2, 3×3…; 14×17/14×14 → papel; A4, A3, Letter, Legal, Tabloid conforme a impressora | PM §16 | Print | Essencial | Implementado | `app/printing/layout_engine.py`, `paper.py` | `tests/test_layout.py` | r5 |
| PRT-08 | `header.bmp`/`footer.bmp` 3000×206 sem distorção; A4 e A3 | PM §17 | Print | Essencial | Implementado | `app/printing/templates.py` | `tests/test_layout.py` | r5 |
| PRT-09 | Calibração brilho/contraste/gama −5 a +5, passo 0,5, pré-visualização, salvar/editar/cancelar/restaurar, por regra, folha 3×3, última imagem como referência, ausência de `last_image.png` | PM §18 | Print | Essencial | Implementado | `app/imaging/tone.py`, `app/ui/pages/device_calibration.py`, `app/printing/calibration_sheet.py` | `tests/test_device_calibration.py`, `test_ui_smoke.py` (Qt real) | r5 |
| PRT-10 | Pausar/Retomar sistema, Abrir log | PM §19 | Print | Essencial | Implementado | `app/services/operation.py`, `app/ui/operation_bar.py`, migração 0008 | `tests/test_operation.py` (10 testes); `tests/test_ui_operation.py` (Qt real, CI run 40021144464); pipeline “Windows release” run 40021144401 | r6 |
| PRT-11 | Visualizar conexões, recebimentos e erros | PM §19 | Print | Essencial | Implementado | Servidor DICOM (associações), Histórico (filtros), Dashboard (falhas recentes) | `tests/test_ui_smoke.py` | r5 |
| PRT-12 | Configurações sensíveis exigem pausa segura | PM §19 | Print | Essencial | Implementado | `SettingsPage.ensure_safe_pause`; `CoreRuntime.restart_when_idle` (espera até 60 s pelas associações) | `tests/test_operation.py::SafeRestartTest`; `tests/test_ui_operation.py` | r6 |
| PRT-13 | Registrar origem, destino, formato, regra, resultado, horário e falhas | PM §19 | Print | Essencial | Implementado | `jobs`, `job_history`, `events` (com redação de dados do paciente) | `tests/test_logging_and_redaction.py`, `test_jobs.py` | r5 |
| PRT-14 | Separar logs operacionais temporários da trilha de auditoria | PM §19 | Print | Essencial | Implementado | `EventRepository.purge_older_than(audit_days=)`; configuração `retention.audit_days` (padrão 1825 dias) | `tests/test_operation.py::AuditRetentionTest` | r6 |
| PRT-15 | Avaliar Windows 7; edição legada isolada se necessário | PM §20 | Print | Recomendada | Implementado (decisão) | ADR-0010; `MinVersion=10.0.17763` nos instaladores | — | — |
| PRT-16 | Nomes `Vyonix.exe` e `Vyonix_Setup.exe` | PM §21 | Print | Essencial | Parcial | `Vyonix.spec` gera `Vyonix.exe`; release publica também `Vyonix_Setup.exe` (ADR-0011) | Será exercido na próxima release publicada (r6) | r6 |

### Entrega 2 — Fundação VYONIX (PM §9, §12, §39–§42, §50)

| ID | Requisito | Origem | Situação | Implementação | Testes / evidência |
|---|---|---|---|---|---|
| FND-01 | Organizações, unidades, segregação entre organizações | PM §9, §50 | Implementado | `vyonix/tenancy`, RLS forçado (ADR-0007) | `tests_platform/test_core.py`, `test_architecture.py`; CI “platform” (PostgreSQL 17) |
| FND-02 | Autenticação segura, sessões, MFA para perfis sensíveis, RBAC | PM §50 | Implementado | `vyonix/auth` (TOTP, códigos de recuperação, bloqueio) | `tests_platform/test_core.py`, `test_api.py`, `test_e2e_web.py` |
| FND-03 | Auditoria encadeada (SHA-256) | PM §9, §50 | Implementado | `vyonix/audit/service.py` | `tests_platform/test_core.py` |
| FND-04 | Configuração central por módulo com histórico | PM §9 | Implementado | `vyonix/settings` | `tests_platform/test_core.py` |
| FND-05 | APIs versionadas e eventos (fila persistente, retentativas, idempotência) | PM §9, §48 | Implementado | `vyonix/api`, `vyonix/events` (ADR-0004) | `tests_platform/test_core.py` |
| FND-06 | Licenciamento modular, assinatura, validação offline, ativação por código/arquivo, demonstração de 5 dias, sem chave privada no cliente, sem destruir dados ao expirar | PM §39 | Implementado | `vyonix/licensing`, `vyonix_protocol`, `app/licensing` | `tests_platform/test_licensing.py`; `tests/test_licensing.py`, `test_license_enforcement.py`; varredura `scan_private_keys` no CI |
| FND-07 | License Manager independente, portátil e instalável; módulos; emissão, reemissão, revogação | PM §40 | Implementado | `license_manager/` | `tests/test_license_manager_ui.py`; release r5 |
| FND-08 | DEPLOY: verificação do sistema, portas, serviços, certificados, impressoras, requisitos; atualização, backup, rollback, diagnóstico | PM §41 | Implementado | `vyonix_deploy/` | Aceitação no Windows: 26 aprovados, 0 reprovados, 1 não executado (run 39702093478) |
| FND-09 | Ativação de módulos sem reinstalar | PM §42 | Implementado | `vyonix_deploy/modules.py` | idem (critério 2.9) |
| FND-10 | Identidade por OpenID Connect/OAuth 2.0 | PM §12 | Planejado (Entrega 6 — portais) | Hoje: sessão própria com MFA | — |
| FND-11 | Atualizações assinadas | PM §50 | Parcial | Licenças assinadas (Ed25519); instalador sem assinatura de código | Pendente: certificado de assinatura de código (serviço pago — exige aprovação, §59) |
| FND-12 | Inventário de componentes, SBOM e análise de vulnerabilidades | PM §50 | Implementado (Python) | `tools/sbom_audit.py` (CycloneDX + pip-audit) nos pipelines Windows; SBOM anexado à release | Print: 41 componentes, 0 vulnerabilidades conhecidas (run 40021144401); plataforma: 47 componentes, 0 (run 40010347005). Pendente: `npm audit` da interface web |

### Entregas 3–8 (PM §22–§38, §43, §60)

| ID | Requisito | Origem | Situação |
|---|---|---|---|
| PAC-01 | PACS: recepção, armazenamento, indexação, pesquisa, importação/exportação, distribuição, acesso, auditoria, backup, retenção, monitoramento; C-ECHO/C-STORE/C-FIND/C-MOVE/C-GET/MWL/MPPS/QIDO/WADO/STOW; declaração de conformidade | PM §22 | **Parcial.** Implementado: recepção (STOW-RS e C-STORE no Orthanc + sincronização no modo edge), validação, armazenamento, índice por organização (RLS), pesquisa QIDO-RS, recuperação WADO-RS (instância, série, estudo, metadados, frames), SHA-256 na entrada e na saída, auditoria de entrada, recusa e abertura — `vyonix/pacs`, `vyonix/api/routes_pacs.py`, migração `pacs_0001`; testes `tests_platform/test_pacs.py` (17) e `test_pacs_orthanc.py` (Orthanc real no CI). Também: motor como serviço e ativação pelo DEPLOY; página Imagens na interface web (`web/src/pages/images.tsx`, ponta a ponta `test_4_images_flow`); declaração de conformidade **preliminar** (`docs/release/Declaracao_Conformidade_DICOM_PACS.md`). C-FIND/C-MOVE (Study Root) servidos pelo Core com nós DICOM autorizados por organização (`vyonix/pacs/dimse_qr.py`, migração `pacs_0003`; `tests_platform/test_pacs_qr.py`: 6 cenários com associações DICOM reais). Backup/restauração verificados e independentes do motor (`vyonix/pacs/backup.py`, comandos `pacs-backup`/`pacs-verify`/`pacs-restore`, `docs/operacao/Backup_e_Restauracao_PACS.md`; `tests_platform/test_pacs_backup.py` 6 cenários, inclusive motor perdido com índice intacto). Falta: C-GET, MPPS, agendamento do backup pelo DEPLOY, retenção, interoperabilidade com equipamentos reais |
| PAC-02 | Integridade: nunca sobrescrever instância indexada; detectar divergência de conteúdo e corrupção | PM §24–§25 | Implementado — `pacs.service.ingest/_verified`; testes de recusa, idempotência e corrupção |
| PAC-03 | Isolamento entre organizações com motor compartilhado | PM §9, §50 | Implementado — índice com RLS, motor sem acesso direto, conteúdo divergente recusado, C-STORE do modo cloud pelo AE Title chamado (quarentena sem rota/licença). Testes: `test_tenant_isolation`; `tests_platform/test_pacs_cloud_isolation.py` (8 cenários: acesso cruzado pela API — pesquisa, recuperação, metadados, frames, qualidade, sem revelar existência —, acesso por SQL bloqueado pelo RLS, AE desconhecido/preenchido/não DICOM, paciente enviado ao AE errado, mesmos UIDs com conteúdos diferentes em duas organizações, reenvio ao AE da outra, rota removida e reassumida, gestão de rotas isolada). Motor: dublê de teste; origem do AE com o Orthanc real em `test_pacs_orthanc.py` |
| PAC-04 | Suspensão comercial não bloqueia dados existentes | Restrição do projeto | Implementado — leitura exige só permissão; entrada exige módulo e licença; `test_permissions_and_read_without_license` |
| VIE-01 | Viewer: séries, miniaturas, W/L, zoom, pan, rotação, inversão, medições, ROI, comparação, sincronização, hanging protocols, metadados, exportação | PM §23 | **Parcial.** OHIF v3.13.13 (MIT, sem alterações) compilado no CI e servido pelo Core em `/viewer/` (mesma origem, sessão do VYONIX, CSP por hash) — `vyonix/api/viewer.py`, `viewer/vyonix.js`, `tools/build_viewer.sh`. Verificado no Chromium (viewer run 40059704370): lista de estudos (QIDO), estudo aberto com imagem desenhada, navegação entre imagens, abertura auditada, sem violação de CSP. Ferramentas verificadas no Chromium: janela/nível, zoom, inverter e girar mudam a imagem desenhada (run 40089461632); medição de distância com Pixel Spacing de 0,5 mm mostra valor em mm plausível (run 40092073131). ROI, comparação, sincronização, hanging protocols e exportação **ainda não verificadas**; a exatidão das medições não foi validada; nenhuma validação clínica |
| INT-01 | Integridade paciente–atendimento–pedido–accession–UIDs–laudo; correção controlada; sem mescla por nome | PM §24 | Parcial — `vyonix/clinical` (mescla reversível com justificativa, reconciliação por accession) — `tests_platform/test_clinical.py` |
| QLD-01 | Detecção de transferências incompletas, corrompidos, duplicidades, séries inesperadas, estudos sem pedido | PM §25 | Parcial — corrompidos, duplicidades e divergências recusados ou detectados; transferência incompleta e estudos sem pedido ainda não |
| RIS-01 | RIS e Central de Exames; ciclo de vida do exame | PM §27–§29 | **Parcial (primeira entrega).** Agendamento de exames (passo agendado com Study Instance UID atribuído antes do exame, raiz 2.25), worklist pela API e **Modality Worklist por DICOM (C-FIND)**, ciclo fechado pela chegada do estudo ao PACS (agendamento "recebido") — `vyonix/ris/`, `vyonix/api/routes_ris.py`, migração `ris_0001`, MWL em `vyonix/pacs/dimse_qr.py`; testes `tests_platform/test_ris.py` (8, com associação DICOM real). **Interface web “Agenda”** (`web/src/pages/schedule.tsx`): pedidos pendentes, agendamento, iniciar/concluir/cancelar com motivo, filtros; ponta a ponta no navegador com recepcionista e técnico (`test_e2e_web.test_5_ris_schedule_flow`). Também: duração com recusa de horário sobreposto por estação/sala (`ris_0002`), check-in (ARRIVED), situação do passo na MWL e **MPPS SCP** (N-CREATE/N-SET com associação real, `ris_0003`; `test_mpps_*`). **Salas** cadastradas (`ris_0004`) com modalidade, estação e duração padrão; o nome da sala é padronizado para a recusa de sobreposição. Falta: central de exames, armazenamento de dose/séries do MPPS |
| REP-01 | Telelaudo, achados críticos | PM §30–§31 | **Parcial (primeira entrega do VYONIX REPORT).** Modelos, rascunho, liberação com confirmação de senha (não é assinatura ICP-Brasil), versões imutáveis com SHA-256 (sem UPDATE/DELETE para a aplicação no banco), adendos, achado crítico com evento `report.critical.v1`, verificação de integridade, pedido concluído na liberação, papel Médico; tela “Laudos” — `vyonix/report/`, `routes_report.py`, migração `report_0001`; `tests_platform/test_report.py` (4), e2e `test_7_report_flow`. Também: PDF do laudo liberado (emissão auditada) e **comunicação de achado crítico** (pendência aberta na liberação, encerrada com a quem, meio, por quem e quando; `report_0002`). Falta: assinatura digital (BLK-14), aviso automático (NOTIFY), telelaudo/distribuição, laudo estruturado |
| TEL-01…16 | Telelaudo multicliente: identidade visual por cliente/unidade, modelos versionados, editor e importação DOCX, cadastro de médicos, assinatura (visual × eletrônica), seleção automática com fallback, isolamento, LGPD, DICOM/HL7/FHIR opcionais | Pedido do proprietário 28/10/2026 | **Em andamento** (BKL-11): TEL-07 cadastro de médicos e vínculos **feito** (T1, `report_0003`, testes `test_report.Physicians`); TEL-01/02/12 identidade visual por organização e unidade **feito** (T2, `report_0004`, `test_report_branding.py`); TEL-03/04/05 modelos com versões, seções e campos dinâmicos **feito** (T3, `report_0005`, `test_report_templates.py`; editor visual rico e DOCX em T6); TEL-10/11 seleção automática com prioridade e isolamento **feito** (T4, `test_report_templates.Selection`); TEL-08 imagem da assinatura só visual, autorizada pelo médico **feito** (T5, `report_0006`, `test_report_signature.py`); TEL-06 importação DOCX assistida **feito** (T6, `test_report_docx.py`; formatação de caractere e tabelas viram texto — limite registrado); TEL-16 fila de telelaudo com escopo por unidade **feito** (T7, `test_report_queue.py`); TEL-13/14 integração e saídas FHIR/HL7/DICOM opcionais **feito** (T8, `test_report_interop.py`). Pendentes: TEL-09 assinatura digital (BLK-14), TEL-15 revisão LGPD/CFM (BLK-06) — `docs/platform/Telelaudo_Multicliente_Requisitos.md` |
| HIS-01 | HIS Connect (HL7 v2/FHIR) | PM §32 | Planejado |
| FLW-01 | FLOW, sem monitoramento físico de equipamentos | PM §33 | Planejado (Entrega 7); exclusão registrada |
| POR-01 | Portais do paciente e do médico, QR Code seguro, Notify | PM §34–§36 | Planejado (Entrega 6) |
| IA-01 | Serviços de IA com governança; sem diagnóstico autônomo | PM §37–§38 | Planejado; nenhum recurso de IA implementado |
| COM-01 | VYONIX Comercial: propostas DOCX/PDF, preços, aprovações | PM §43 | Parcial — gestão de assinaturas e cobrança em `vyonix_commercial`; propostas ainda não |

## 2. Sugestões da IA (não são requisitos aprovados)

| ID | Sugestão | Classe (PM §8) | Situação |
|---|---|---|---|
| SUG-01 | Publicar o instalador também como `Vyonix_Setup.exe` com o mesmo SHA-256 | Recomendada | Implementado no pipeline (ADR-0011) |
| SUG-02 | Matriz automática de resolução/escala/monitores no CI do Windows | Essencial | Implementado (`ui-windows.yml`) |
| SUG-03 | Reinício dos servidores DICOM só depois que as associações em andamento terminam | Recomendada | Implementado |
| SUG-04 | SBOM (CycloneDX) e `pip-audit` em cada build | Essencial | Implementado (falta `npm audit`) |
| SUG-05 | Assinatura de código do instalador | Recomendada | Aguarda aprovação (custo do certificado) |

## 3. Hipóteses pendentes

| ID | Hipótese | Como confirmar |
|---|---|---|
| HIP-01 | Distribuir o Orthanc (GPLv3, sem plugins, processo separado e sem modificação) não obriga a abrir o código do VYONIX | Parecer jurídico (BLK-07) |
| HIP-02 | Nenhum cliente precisa de Windows 7 | Levantamento comercial (ADR-0010) |
| HIP-03 | O índice SQLite interno do Orthanc atende o volume inicial das clínicas | Teste de carga na Entrega 3 (PM §61) |

## 4. Histórico de alterações deste documento

| Data | Alteração |
|---|---|
| 2026-10-23 | Criação a partir do Prompt Mestre v1.0; auditoria da Entrega 1 com as lacunas PRT-02, PRT-03, PRT-10, PRT-12, PRT-14 e PRT-16 corrigidas; FND-12 implementado |
| 2026-10-24 | PACS: primeira entrega vertical — PAC-01 parcial, PAC-02 a PAC-04 implementados, QLD-01 parcial; VIE-01 parcial com o OHIF aberto e navegado no Chromium; motor como serviço e ativação pelo DEPLOY |
| 2026-10-24 (manhã) | PAC-01: página Imagens, Q/R DIMSE desligado explicitamente no motor, declaração de conformidade preliminar |
| 2026-10-24 (08h) | VIE-01: ferramentas janela/nível, zoom, inverter e girar verificadas; PAC-01: C-STORE no modo cloud por AE Title |
| 2026-10-24 (08h40) | PAC-03: testes de isolamento do modo cloud (8 cenários); defeito do AE com espaços de preenchimento corrigido; VIE-01: medição de distância no ponta a ponta |
| 2026-10-24 (09h) | PAC-01: C-FIND/C-MOVE pelo Core (nós DICOM autorizados, isolamento por organização, SHA-256 no envio, auditoria) |
| 2026-10-24 (09h10) | VIE-01: medição de distância verificada (run 40092073131) |
| 2026-10-27 | RIS-01 parcial: agendamento, worklist e MWL por DICOM; UID com raiz 2.25 |
| 2026-10-27 | RIS-01: interface web Agenda; PACS: backup automático diário (Worker + DEPLOY + monitoramento); BKL-10 aprovado e integrado à develop (próxima versão de laboratório) |
| 2026-10-27 | PAC-01: backup e restauração do PACS (exportação verificada, recuperação de desastre) |
