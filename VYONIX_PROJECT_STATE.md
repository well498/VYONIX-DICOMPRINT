# VYONIX — Estado do projeto

Memória técnica do projeto (Prompt Mestre §53). Lida no início e atualizada no fim de cada entrega.
Não contém credenciais, chaves privadas nem dados de pacientes.

* **Atualizado em:** 2026-10-24
* **Repositório:** `well498/VYONIX-DICOMPRINT`, ramo `develop`
* **Especificação vigente:** Prompt Mestre Final v1.0 (2026-10-23); decisões em [`docs/adr/`](docs/adr/README.md)
* **Rastreabilidade:** [`VYONIX_REQUIREMENTS_TRACEABILITY.md`](VYONIX_REQUIREMENTS_TRACEABILITY.md)
* **Documento de arquitetura da plataforma:** Claude Doc “VYONIX — Arquitetura da Plataforma e Plano das Fases 1 e 2”

## 1. Versões

| Componente | Versão | Publicação |
|---|---|---|
| VYONIX DICOM Print (`app/`) | 1.0.0 | Pré-release **v1.0.0-r5** (commit `fd59d83`), homologação. Revisão 6 pronta no `develop`, **não publicada** |
| Plataforma — CORE (`vyonix/`) | 0.2.0 | Não publicada |
| VYONIX DEPLOY (`vyonix_deploy/`) | 0.2.0 | Instalador `VYONIX_Setup_x64.exe` só como artefato de CI |
| License Manager / License Server | 1.0.0 | Na release r5 (somente fornecedor) |

Nenhum componente está validado para uso clínico. Nenhuma conformidade regulatória é declarada.

## 2. Arquitetura (resumo)

* **EDGE** (servidor da clínica, Windows 10 1809+/Server 2019+): VYONIX DICOM Print (Qt + serviço Windows,
  SQLite próprio), CORE (FastAPI + React), worker de eventos, PostgreSQL 17 administrado pelo DEPLOY.
* **CLOUD** (planejada): mesmo código do CORE com `tenant_id` e row level security forçado.
* Comunicação entre módulos por API versionada e eventos na outbox do PostgreSQL (ADR-0004).
* PACS da Entrega 3 (ADR-0012, aceita): Orthanc sem modificações e sem plugins AGPL como motor; índice por
  organização (RLS), DICOMweb (STOW/QIDO/WADO-RS), integridade e auditoria no CORE (`vyonix/pacs`). Viewer: OHIF 3.13 (a integrar).

## 3. Tecnologias

Python 3.12, PySide6 (Qt 6), pydicom/pynetdicom, FastAPI, SQLAlchemy 2 + Alembic, PostgreSQL 17.11 (EDB),
React 19 + TypeScript (esbuild), ReportLab, cryptography (Ed25519), PyInstaller, Inno Setup, GitHub Actions
(windows-2022, ubuntu com PostgreSQL 17).

## 4. Estado por entrega (Prompt Mestre §60)

| Entrega | Situação | Evidência |
|---|---|---|
| 1 — DICOM Print estável | Concluída para homologação (r5) + correções da auditoria de 23/10 (r6, não publicada) | “Windows release” run 40021144401 (testes, instalador, validação, SBOM); “UI Windows” run 40021144464 (matriz 11/11); 303 testes locais |
| 2 — Fundação VYONIX | Concluída (Fases 1 e 2 da plataforma) | CI “platform” (69 testes, PostgreSQL 17.11); aceitação DEPLOY 26/0/1 (run 39702093478) |
| 3 — PACS e Viewer | **Em andamento.** Primeira entrega vertical do PACS feita (receber → validar → armazenar → indexar → pesquisar → recuperar → metadados/frames → auditar). Viewer ainda não integrado. Não liberado para uso clínico | `tests_platform/test_pacs.py` (17 testes, PostgreSQL real, dublê de motor rotulado); `test_pacs_orthanc.py` contra o Orthanc real no CI “platform” |
| 4 a 8 | Planejadas | — |

## 5. Backlog

| ID | Tarefa | Módulo | Prior. | Depende de | Aceitação | Risco | Estado | Aprovação | Rollback |
|---|---|---|---|---|---|---|---|---|---|
| BKL-01 | ADR-0012 revisada e aceita (sem plugins AGPL). Fica a revisão jurídica da distribuição do Orthanc (BLK-07) | PACS | Essencial | — | Decisão registrada | Licença | Concluída (revisão jurídica em BLK-07) | Sim (BLK-07) | — |
| BKL-02 | Publicar a revisão r6 do DICOM Print (alterar `RELEASE_TAG`) | Print | Alta | CI verde de r6 | Release com SHA-256 e `Vyonix_Setup.exe` | Baixo | Pronta | Sim (publicação) | Release r5 continua disponível |
| BKL-03 | SBOM CycloneDX + `pip-audit` no CI (feito); falta `npm audit` da interface web | Segurança | Essencial | — | SBOM anexado ao build; vulnerabilidades listadas | Baixo | Parcial | Não | Remover o passo |
| BKL-04 | Módulo PACS. **Feito:** `PacsBackend`/Orthanc REST, índice com RLS (`pacs_0001`), STOW/QIDO/WADO-RS, SHA-256 na entrada e na saída, sincronização de C-STORE (modo edge), auditoria, evento. **Falta:** instalação do Orthanc pelo DEPLOY, C-FIND/C-MOVE/C-GET pelo CORE, roteamento por AE Title no modo cloud, MWL/MPPS, declaração de conformidade | PACS | Essencial | — | Testes com Orthanc real no CI; DEPLOY no Windows | Médio | Em andamento | — | Desabilitar o módulo (dados preservados); `alembic downgrade pacs@base` |
| BKL-05 | Viewer OHIF 3.13 servido pelo CORE (mesma origem, cookie da sessão) apontando para `/api/v1/pacs/dicomweb` | Viewer | Essencial | BKL-04 (API pronta) | Abrir estudo sintético no Chromium (Playwright) e navegar entre imagens | Médio | Próxima — o build do OHIF precisa ser feito no CI (o registro npm não é alcançável neste ambiente) | — | Desativar o módulo |
| BKL-06 | Qualidade dos estudos. **Feito:** recusa de arquivo não DICOM, truncado, sem UIDs, UID inválido, sem Patient ID, conteúdo divergente com o mesmo SOP UID, Patient ID divergente no mesmo estudo; reenvio idempotente; corrupção no motor detectada na recuperação. **Falta:** transferência incompleta (série esperada × recebida), estudos sem pedido no painel | PACS | Recomendada | BKL-04 | Testes com estudos sintéticos defeituosos | Baixo | Parcial | — | — |
| BKL-07 | Assinatura de código dos instaladores | Segurança | Recomendada | Certificado (pago) | Instaladores assinados verificados no CI | Baixo | Aguarda aprovação | Sim (custo) | — |
| BKL-08 | Testes manuais em Windows 10/11 limpos, impressoras físicas e equipamentos reais | Print | Essencial | Ambiente do cliente | Roteiro `docs/release/Roteiro_Testes_Manuais.md` executado | — | Aguarda ambiente | — | — |
| BKL-09 | Identidade OpenID Connect para portais | CORE | Recomendada | Entrega 6 | — | — | Planejada | — | — |

## 6. Dependências externas

PostgreSQL 17.11 (binários EDB, SHA-256 conferido no CI); Inno Setup; PySide6; Orthanc (núcleo GPLv3, sem plugins; no CI, pacote do Ubuntu 24.04); OHIF 3.13 (a integrar); pydicom 3 no Core.

## 7. Problemas conhecidos

* CI não permite baixar logs nem artefatos (HTTP 403); a evidência do CI vem das anotações dos check-runs.
* Não verificado: equipamentos DICOM reais, impressão em papel em impressora física, Windows 10/11 limpos
  (o CI usa Windows Server 2022), instalador sem assinatura de código.
* A matriz de interface usa telas virtuais (`offscreen`): confirma geometria, cortes, sobreposição e contraste,
  mas não substitui a revisão visual num monitor real.

## 8. Riscos

| Risco | Efeito | Mitigação |
|---|---|---|
| Distribuição do Orthanc (GPLv3) junto do produto | Obrigações de licença | Sem plugins AGPL; processo separado e sem modificação; revisão jurídica antes de distribuir (BLK-07) |
| Motor DICOM compartilhado entre organizações | Vazamento entre clínicas | Índice com RLS; o motor nunca é consultado por UID do cliente; SHA-256 conferido; sincronização de C-STORE só no modo edge |
| Enquadramento regulatório dos módulos clínicos (RDC 657/2022, 751/2022) | Venda sem regularização | Classificação por módulo antes de declarar qualquer módulo clínico pronto |
| Duas interfaces (Qt e web) durante a transição | Inconsistência | Tokens de cor e regras comuns; migração tela a tela |
| Clínica sem TI | Falhas de serviço | DEPLOY com diagnóstico e reparo; pausa segura no Print |

## 9. Registro da sessão de 2026-10-23

**Início (checklist §53):** ramo `develop` limpo em `65c229a`; documentação comparada com o código; auditoria da
Entrega 1 contra o Prompt Mestre §13–§21.

**Lacunas encontradas e corrigidas:**

| Lacuna | Correção | Arquivos |
|---|---|---|
| Tema escuro com a paleta Qt clara: listas suspensas, menus e caixas de mensagem com texto claro sobre fundo claro; verde e âmbar da marca abaixo de 4,5:1 como texto | Tokens com contraste verificado, `QPalette` completa, regras para listas, menus, rolagem, dicas e diálogos | `app/ui/tokens.py`, `app/ui/theme.py` |
| Nenhum teste de resolução, escala ou múltiplos monitores | Matriz de 11 configurações com o Qt real; janela abre na tela indicada e centralizada | `tests/test_ui_matrix.py`, `tests/ui_matrix_probe.py`, `app/ui/main_window.py`, `.github/workflows/ui-windows.yml` |
| Sem “Pausar sistema”, “Retomar sistema” e “Abrir log” | Pausa segura no banco (vale para interface e serviço), barra no cabeçalho | `app/services/operation.py`, `app/ui/operation_bar.py`, migração `0008` |
| Configurações sensíveis aplicadas sem pausa e com reinício imediato dos servidores | Exige pausa; reinício espera as associações terminarem (até 60 s) | `app/ui/pages/settings_page.py`, `app/services/runtime.py` |
| Trilha de auditoria apagada junto com os eventos operacionais | Retenção própria (`retention.audit_days`, padrão 5 anos) | `app/database/repositories/events_repo.py`, `app/services/retention.py`, `settings_service.py` |
| Nome comercial `Vyonix_Setup.exe` ausente | Publicado como cópia idêntica na release (exercido na próxima publicação) | `.github/workflows/windows-release.yml` |
| Rolagem horizontal na janela padrão (1280 px), textos cortados, campos espremidos, botões sobre tabela, diálogos maiores que a tela em 1366 × 768 e 150 % | Linhas de botões e filtros em fluxo, rótulos com quebra, listas suspensas compactas, formulários que quebram a linha, grade responsiva (Dashboard, Calibração), área rolável que respeita quebra de linha, diálogos roláveis e dentro da tela | `app/ui/responsive.py`, `app/ui/pages/base.py`, páginas e diálogos |
| Sem SBOM nem análise de vulnerabilidades | CycloneDX + pip-audit nos dois pipelines Windows; SBOM anexado à release | `tools/sbom_audit.py`, workflows |

**Migrações:** Print `0008_operation_control` (cria `operation_state`; reversão: restaurar o backup automático
feito antes de migrar — a tabela não altera dados existentes).

**Aprovações pendentes:** BKL-01 (ADR-0012), BKL-02 (publicar r6), BKL-07 (certificado).

**Rollback desta sessão:** `git revert` dos commits de 23/10 no `develop`; a release r5 não foi alterada.

**Testes e evidências (CI, commit `10abc1b`):**

| Execução | Resultado |
|---|---|
| UI Windows — run 40021144464 | Sucesso: matriz 11/11 configurações sem problemas (2 temas × 13 páginas + 6 diálogos cada); contraste medido nos pixels: lista suspensa 16,46:1 / 13,76:1, menu 16,46:1 / 13,76:1, diálogo 15,2:1 / 15,55:1 (claro/escuro); 8 testes de fumaça Qt; 2 testes da barra de operação; 5 de tokens |
| Windows release — run 40021144401 | Sucesso: todos os testes, PyInstaller, Inno Setup, validação do executável e do instalador; SBOM 41 componentes, 0 vulnerabilidades conhecidas; publicação não executada (r5 já existe) |
| platform — run 40021144434 | Sucesso |
| deploy-windows — run 40022803070 (`0d746d6`) | Aceitação do DEPLOY sem regressão: 26 aprovados, 0 reprovados, 1 não executado (impressão de teste no Print); SBOM da plataforma 47 componentes, 0 vulnerabilidades conhecidas |
| Local (Linux) | 303 testes, 0 falhas, 25 ignorados (Qt/Windows) |

**Próxima tarefa:** BKL-02 (publicar r6) e BKL-01 (aprovar ADR-0012) dependem de aprovação; sem aprovação, seguir com
`npm audit` (BKL-03) e com os itens de usabilidade da Entrega 1 que a matriz não cobre (revisão visual em monitor real).
