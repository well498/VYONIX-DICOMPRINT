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
| PRT-02 | Menus suspensos legíveis, contraste, fundos escuros, barras de rolagem, diálogos (QComboBox, QAbstractItemView, QScrollBar, QMenu, QDialog, QPalette, QSS) | PM §14 | Print/UI | Essencial | Implementado (aguarda CI) | `app/ui/tokens.py`, `app/ui/theme.py` (ADR-0013) | `tests/test_ui_tokens.py` (local); `tests/test_ui_matrix.py` mede o contraste renderizado (CI “UI Windows”) | r6 (não publicada) |
| PRT-03 | Testar 1366×768, 1600×900, 1920×1080, 2560×1440, 3840×2160, escalas DPI e múltiplos monitores, sem alterar a resolução | PM §14 | Print/UI | Essencial | Implementado (aguarda CI) | `tests/ui_matrix_probe.py`; `MainWindow.show_fitted(screen)` | 11 configurações × 2 temas × 13 páginas + 6 diálogos (`tests/test_ui_matrix.py`) | r6 |
| PRT-04 | AE Title, portas, recepção DICOM, identificação da origem | PM §15 | Print | Essencial | Implementado | `app/dicom/storage_scp.py`, `routing.py`, `listeners.py` | `tests/test_storage_scp.py`, `test_reception.py`; CI r5 | r5 |
| PRT-05 | Seleção de impressora, filas, layouts, impressão automática e manual, reimpressão autorizada, erros, histórico | PM §15 | Print | Essencial | Implementado | `app/jobs/`, `app/printing/` | `tests/test_jobs.py`, `test_job_states.py`, `test_windows_printing.py` (Microsoft Print to PDF no CI) | r5 |
| PRT-06 | Regras por AE/modalidade/impressora/papel/layout/brilho/contraste/gama/cabeçalho/rodapé/imagens vazias | PM §16 | Print | Essencial | Implementado | `app/rules/engine.py`, `app/devices/settings.py` | `tests/test_rules.py`, `test_devices.py` | r5 |
| PRT-07 | Layouts 1×1, 2×2, 3×3…; 14×17/14×14 → papel; A4, A3, Letter, Legal, Tabloid conforme a impressora | PM §16 | Print | Essencial | Implementado | `app/printing/layout_engine.py`, `paper.py` | `tests/test_layout.py` | r5 |
| PRT-08 | `header.bmp`/`footer.bmp` 3000×206 sem distorção; A4 e A3 | PM §17 | Print | Essencial | Implementado | `app/printing/templates.py` | `tests/test_layout.py` | r5 |
| PRT-09 | Calibração brilho/contraste/gama −5 a +5, passo 0,5, pré-visualização, salvar/editar/cancelar/restaurar, por regra, folha 3×3, última imagem como referência, ausência de `last_image.png` | PM §18 | Print | Essencial | Implementado | `app/imaging/tone.py`, `app/ui/pages/device_calibration.py`, `app/printing/calibration_sheet.py` | `tests/test_device_calibration.py`, `test_ui_smoke.py` (Qt real) | r5 |
| PRT-10 | Pausar/Retomar sistema, Abrir log | PM §19 | Print | Essencial | Implementado | `app/services/operation.py`, `app/ui/operation_bar.py`, migração 0008 | `tests/test_operation.py` (local, 10 testes); `tests/test_ui_operation.py` (CI) | r6 |
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
| FND-12 | Inventário de componentes, SBOM e análise de vulnerabilidades | PM §50 | Planejado (próxima tarefa, BKL-03) | — | — |

### Entregas 3–8 (PM §22–§38, §43, §60)

| ID | Requisito | Origem | Situação |
|---|---|---|---|
| PAC-01 | PACS: recepção, armazenamento, indexação, pesquisa, importação/exportação, distribuição, acesso, auditoria, backup, retenção, monitoramento; C-ECHO/C-STORE/C-FIND/C-MOVE/C-GET/MWL/MPPS/QIDO/WADO/STOW; declaração de conformidade | PM §22 | Aguarda aprovação (ADR-0012: motor e revisão jurídica da AGPL) |
| VIE-01 | Viewer: séries, miniaturas, W/L, zoom, pan, rotação, inversão, medições, ROI, comparação, sincronização, hanging protocols, metadados, exportação | PM §23 | Aguarda aprovação (ADR-0012) |
| INT-01 | Integridade paciente–atendimento–pedido–accession–UIDs–laudo; correção controlada; sem mescla por nome | PM §24 | Parcial — `vyonix/clinical` (mescla reversível com justificativa, reconciliação por accession) — `tests_platform/test_clinical.py` |
| QLD-01 | Detecção de transferências incompletas, corrompidos, duplicidades, séries inesperadas, estudos sem pedido | PM §25 | Planejado (Entrega 3) |
| RIS-01 | RIS e Central de Exames; ciclo de vida do exame | PM §27–§29 | Planejado (Entrega 4) |
| REP-01 | Telelaudo, achados críticos | PM §30–§31 | Planejado (Entrega 5) |
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
| SUG-04 | SBOM (CycloneDX) e `pip-audit` em cada build | Essencial | Planejado (BKL-03) |
| SUG-05 | Assinatura de código do instalador | Recomendada | Aguarda aprovação (custo do certificado) |

## 3. Hipóteses pendentes

| ID | Hipótese | Como confirmar |
|---|---|---|
| HIP-01 | O uso do plugin DICOMweb (AGPL) sem modificação, em processo separado, não obriga a abrir o código do VYONIX | Parecer jurídico (ADR-0012) |
| HIP-02 | Nenhum cliente precisa de Windows 7 | Levantamento comercial (ADR-0010) |
| HIP-03 | O índice SQLite interno do Orthanc atende o volume inicial das clínicas | Teste de carga na Entrega 3 (PM §61) |

## 4. Histórico de alterações deste documento

| Data | Alteração |
|---|---|
| 2026-10-23 | Criação a partir do Prompt Mestre v1.0; auditoria da Entrega 1 com as lacunas PRT-02, PRT-03, PRT-10, PRT-12, PRT-14 e PRT-16 corrigidas |
