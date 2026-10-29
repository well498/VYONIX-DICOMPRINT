# VYONIX — Estado do projeto

Memória técnica do projeto (Prompt Mestre §53). Lida no início e atualizada no fim de cada entrega.
Não contém credenciais, chaves privadas nem dados de pacientes.

* **Atualizado em:** 2026-10-28 (noite)
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

**Restrições do proprietário em vigor (24/10/2026):**
* Testes do DICOM Print somente no ambiente laboratorial offline; nenhum ensaio em campo sem autorização expressa (BLK-13).
* Recuperação da senha administrativa do License Manager adiada: não redefinir senhas, não excluir contas, não alterar
  credenciais (BLK-12). Trabalhos que dependem do acesso ao License Manager ficam registrados como pendentes.
* Preservar as funcionalidades existentes; evitar alterações desnecessárias.

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
| 3 — PACS e Viewer | **Em andamento.** Entrega vertical completa nos testes automatizados (receber → validar → armazenar → indexar → pesquisar → recuperar → abrir no Viewer → navegar → auditar). Não liberado para uso clínico | `tests_platform/test_pacs.py` (17 testes, PostgreSQL real, dublê de motor rotulado); `test_pacs_orthanc.py` contra o Orthanc real no CI “platform” |
| 4 a 8 | Planejadas | — |

## 5. Backlog

| ID | Tarefa | Módulo | Prior. | Depende de | Aceitação | Risco | Estado | Aprovação | Rollback |
|---|---|---|---|---|---|---|---|---|---|
| BKL-01 | ADR-0012 revisada e aceita (sem plugins AGPL). Fica a revisão jurídica da distribuição do Orthanc (BLK-07) | PACS | Essencial | — | Decisão registrada | Licença | Concluída (revisão jurídica em BLK-07) | Sim (BLK-07) | — |
| BKL-02 | Publicar a revisão r6 do DICOM Print (alterar `RELEASE_TAG`) | Print | Alta | CI verde de r6 | Release com SHA-256 e `Vyonix_Setup.exe` | Baixo | Pronta | Sim (publicação) | Release r5 continua disponível |
| BKL-03 | SBOM CycloneDX + `pip-audit` no CI (feito); `npm audit` da interface web no CI da plataforma (só pacotes distribuídos; reprova alta/crítica) | Segurança | Essencial | — | SBOM anexado ao build; vulnerabilidades listadas | Baixo | Feito (28/10) | Não | Remover o passo |
| BKL-04 | Módulo PACS. **Feito:** Orthanc sem plugins como serviço, índice com RLS, STOW/QIDO/WADO-RS, SHA-256 na entrada e na saída, sincronização de C-STORE (edge) e roteamento por AE (cloud), C-FIND/C-MOVE e MWL/MPPS pelo Core com nós autorizados, declaração de conformidade, backup diário verificado e restauração, verificação contínua de integridade, monitoramento, Estações DICOM, aceitação no Windows (C-STORE → índice → backup). C-GET (28/10, só para nó com permissão de receber, SHA-256 conferido), relatório de retenção com guarda obrigatória (28/10, nada é excluído). **Falta:** exclusão por retenção (exige autorização), revisão jurídica da distribuição (BLK-07) | PACS | Essencial | — | Testes com Orthanc real no CI; DEPLOY no Windows | Médio | Entregue para homologação (28/10) | — | Desabilitar o módulo (dados preservados) |
| BKL-05 | Viewer OHIF 3.13 servido pelo CORE (mesma origem, cookie da sessão) apontando para `/api/v1/pacs/dicomweb` | Viewer | Essencial | BKL-04 | Abrir estudo sintético no Chromium (Playwright) e navegar entre imagens | Médio | **Feito** (viewer run 40059704370); empacotamento no instalador em validação | — | Remover `_internal\viewer` |
| BKL-06 | Qualidade dos estudos. **Feito:** recusa de arquivo não DICOM, truncado, sem UIDs, UID inválido, sem Patient ID, conteúdo divergente com o mesmo SOP UID, Patient ID divergente no mesmo estudo; reenvio idempotente; corrupção no motor detectada na recuperação. Transferência incompleta: imagens informadas pela modalidade no MPPS × recebidas pelo PACS (28/10). Estudos sem pedido: contagem no Início e tela **Conciliação** (busca do pedido pelo número de acesso, conferência do paciente DICOM) (28/10) | PACS | Recomendada | BKL-04 | Testes com estudos sintéticos defeituosos | Baixo | **Feito** | — | — |
| BKL-07 | Assinatura de código dos instaladores | Segurança | Recomendada | Certificado (pago) | Instaladores assinados verificados no CI | Baixo | Aguarda aprovação | Sim (custo) | — |
| BKL-08 | Testes manuais em Windows 10/11 limpos, impressoras físicas e equipamentos reais | Print | Essencial | Ambiente do cliente | Roteiro `docs/release/Roteiro_Testes_Manuais.md` executado | — | Aguarda ambiente | — | — |
| BKL-09 | Identidade OpenID Connect para portais | CORE | Recomendada | Entrega 6 | — | — | Planejada | — | — |
| BKL-10 | DICOM Print: trocar a raiz de UID do pydicom por raiz própria ou `2.25` | Print | Recomendada | Aprovação (Print em validação) | UIDs gerados sem raiz de terceiros; testes do Print | Baixo | Aprovado em 27/10 (próxima versão de laboratório); merge `215d83f` na develop após verificação das condições — `docs/homologacao/BKL-10_UIDs_DICOM_Print.md`; raiz própria: `Recomendacao_Raiz_UID_VYONIX.md` | Sim | `git revert -m 1 215d83f` |
| BKL-11 | **VYONIX TELELAUDO multicliente** (TEL-01 a TEL-16): identidade visual por organização e unidade, modelos versionados por modalidade e procedimento, editor e importação DOCX assistida, cadastro de médicos (CRM/UF, RQE, vínculos), imagem de assinatura só visual e autorizada pelo médico, seleção automática com prioridade e fallback sem cruzar clientes, PDF final versionado, fila de telelaudo, DICOM/HL7/FHIR opcionais — `docs/platform/Telelaudo_Multicliente_Requisitos.md` | REPORT | Alta | REPORT (primeira entrega, feita); BLK-14 para assinatura digital; BLK-06 e revisão LGPD/CFM antes da comercialização | Etapas T1–T9 com testes de isolamento | Médio | **T1 a T8 feitos** (28/10) e assinatura manuscrita digitalizada no cadastro médico (T5b); T9 (assinatura digital) depende de BLK-14 | Sim (comercialização, assinatura) | Desabilitar o módulo |

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

## 10. Registro da sessão de 2026-10-24 (Comando Executivo e Comando de Retomada)

**Entregas desta sessão:**

| Prioridade | Entrega | Arquivos | Evidência |
|---|---|---|---|
| 1 — chaves | Ferramenta do passo 4 do incidente (aplica chave pública nova + restrição da comprometida em `keys.py`, valida e recusa material privado) | `tools/apply_key_rotation.py` | `tests/test_key_rotation_tool.py` (License Manager real: legítima aceita, forjada recusada, 9 recusas de entrada) |
| 2 — vulnerabilidades | `filelock` 4.1.1 vem do `pipx` da imagem do runner, **não** entra no pacote distribuído; atualizado no ambiente de build dos 5 pipelines | `constraints-security.txt`, workflows | Windows release run 40057755638: "filelock NÃO está no pacote distribuído"; SBOM do Print 41 componentes, 0 vulnerabilidades (run 40058503963) |
| 2 — varredura de chaves | Falso positivo em `certifi/cacert.pem` (o pacote da plataforma passou a levar httpx) corrigido; caminhos acusados viram anotação | `tools/scan_private_keys.py` | `tests/test_scan_private_keys.py`; varredura do `cacert.pem` real sem acusação |
| 3 — r6 | Notas da revisão 6, rótulo "Release candidata à homologação — não liberada para uso clínico" na release e no LEIA-ME, etapa do programa atualizada. **Publicação não feita** (BLK-05) | `docs/release/Notas_da_Versao.md`, `windows-release.yml`, `app/__init__.py`, `tools/make_release.py` | Windows release run 40058503963 (commit `5182d87`): sucesso; TPM "não verificável"; release r5 não substituída |
| 5 — PACS | Primeira entrega vertical (receber → validar → armazenar → indexar → pesquisar → recuperar → metadados/frames → auditar); qualidade do estudo | `vyonix/pacs/`, `vyonix/api/routes_pacs.py`, `pacs_0001` | platform run 40058503989: **94 testes, 0 pulados, 0 falhas**, PostgreSQL 17.11 e Orthanc real 1.12.2 (pacote Ubuntu) |
| 5 — PACS no servidor | Motor Orthanc 1.13.0 oficial como serviço supervisionado `VyonixPacsEngine`; ativação pelo DEPLOY (configuração, ACL, serviço, firewall da porta DICOM, Core) | `vyonix/pacs/engine_host.py`, `vyonix_deploy/steps/pacs.py`, `deploy-windows.yml` | `tests_deploy/test_pacs_module.py` (4, local); `tests_platform/test_pacs_engine.py` (binário real, CI); aceitação 2.9 do PACS no Windows (CI) |
| 5 — Viewer | OHIF v3.13.13 compilado sem alterações no CI e servido em `/viewer/` com CSP por hash | `vyonix/api/viewer.py`, `viewer/vyonix.js`, `viewer.yml` | viewer run 40059704370: **3 testes, 0 pulados, 0 falhas** — lista de estudos, imagem desenhada, navegação, abertura auditada, sem violação de CSP. Corrigido no caminho: auditoria da abertura pelos metadados por série |

**Ponto de retomada:** conferir os runs do commit `5650627` (platform com `test_pacs_engine`; viewer com diagnóstico do
navegador; deploy-windows com o `Orthanc.exe` 1.13.0 e a aceitação 2.9 do PACS). Fixar `ORTHANC_SHA256` em
`deploy-windows.yml` com o valor anotado pelo primeiro download. Corrigir o ponta a ponta do Viewer a partir do
diagnóstico.

**Comandos de teste locais** (Linux, PostgreSQL 16 em 55432):

```
. /home/claude/vendor/platform_env.sh && . /home/claude/vendor/env.sh
export PYTHONPATH=.:$PLATPATH:$VYPATH VYONIX_TEST_ADMIN_URL=postgresql://postgres@127.0.0.1:55432/postgres
python3 -m unittest discover -s tests -t .            # 317+ testes (26 pulados: Qt/Windows)
python3 -m unittest discover -s tests_platform -t .   # Orthanc real e OHIF só no CI
python3 -m unittest discover -s tests_deploy -t .
```

**Aprovações pendentes (inalteradas):** publicar r6 (BLK-05); rotação da chave e comunicação aos clientes (BLK-01,
depende do fornecedor gerar `vyx-2026-02`); destruir as cópias de chave da sessão de desenvolvimento (irreversível);
certificado de assinatura de código (BLK-08); especialista regulatório (BLK-06); revisão jurídica da distribuição do
Orthanc (BLK-07).

### Continuação de 24/10 (manhã)

| Entrega | Evidência |
|---|---|
| Aceitação 2.9 do PACS no Windows revertia em "Permissões de imagens do PACS": a conta virtual do serviço era usada antes de o serviço existir. Serviço registrado antes das ACLs + teste da ordem | run 40059704391 (falha encontrada); `tests_deploy/test_pacs_module.py` |
| `ORTHANC_SHA256` fixado (`2D507DF9…C424`, medido no primeiro download) | run 40059704391 |
| Página **Imagens** na interface web (pesquisa, estado do armazenamento, qualidade, link para o Viewer) | `test_e2e_web.py::test_4_images_flow` (Chromium, local): 4/4 aprovados; revisão visual da captura |
| Consulta/recuperação DIMSE (C-FIND/C-MOVE/C-GET) desligada explicitamente no motor | `tests_deploy/test_pacs_module.py`; `test_pacs_engine.py::test_dimse_echo_allowed_query_refused` (binário real, CI) |
| Declaração de conformidade DICOM do PACS (preliminar) | `docs/release/Declaracao_Conformidade_DICOM_PACS.md` |

Restrições do proprietário em vigor: DICOM Print só no laboratório offline; nenhum ensaio em campo sem autorização
expressa (BLK-13); recuperação de senha do License Manager adiada, sem redefinições, exclusões de conta ou mudanças de
credenciais (BLK-12).

**Ponto de retomada:** conferir os runs do commit `8810e40` e seguintes (aceitação 2.9 do PACS e `/viewer/` no
Windows; `test_dimse_echo_allowed_query_refused` no platform).

### Continuação de 24/10 (08h)

| Entrega | Evidência |
|---|---|
| **Ativação do PACS aprovada no Windows** (2.9): Orthanc 1.13.0 como serviço, sem plugins, Core alcançando o motor, porta DICOM 4242 aberta; **Viewer servido pelo Core instalado** com CSP por hash (2.5) | deploy-windows run 40087337898 |
| Correções no caminho: serviço antes das ACLs; código de direito `RX` (o `R` só falhava no Windows) + teste de códigos conhecidos | runs 40059704391 e 40085298672 (falhas encontradas) |
| Com o PACS ativado, a atualização falhou (código 5: o motor mantinha `VyonixPlatform.exe` em execução); instalador passa a parar o `VyonixPacsEngine`, reparo/atualização o reiniciam, desinstalação o remove | **deploy-windows run 40089461650: aceitação 28 aprovados, 0 reprovados, 1 não executado** (impressão de teste no DICOM Print — exige impressora física) |
| C-STORE no modo cloud por AE Title (BLK-11 resolvido) | `tests_platform/test_pacs.py::CloudRouting` |
| Tour guiado do OHIF desligado | `viewer/vyonix.js`; ponta a ponta no Chromium |

**Ponto de retomada:** runs do commit `d0e0a29` (deploy-windows: atualização e desinstalação com o PACS ativado; viewer:
ferramentas janela/nível, zoom, inverter e girar).

### Continuação de 24/10 (08h40)

| Entrega | Evidência |
|---|---|
| Aceitação completa no Windows com o PACS ativado (instalar, ativar PACS, Viewer, atualizar, reparar, restaurar, desinstalar) | deploy-windows run 40089461650: 28/0/1; Windows release run 40089461683: sucesso |
| `2598bc9` e `7d09fcb` confirmados no remoto (ancestrais de `d0e0a29`, head remota); viewer run 40089461632 aprovado depois de `7d09fcb` — o tour não bloqueia mais o zoom | `gh api compare`; run 40089461632 (3/3) |
| Isolamento do PACS cloud: 8 cenários de ataque e erro; encontrou e corrigiu AE Title com espaços de preenchimento indo para a quarentena | `tests_platform/test_pacs_cloud_isolation.py` (8/8 local) |
| Medição de distância (Length) no ponta a ponta do Viewer | `tests_viewer/test_viewer_e2e.py` (confirmação no CI pendente) |

Restrições mantidas: r6 não publicada; sem ensaio em campo; recuperação de senha do License Manager adiada; DICOM Print em
laboratório (rede isolada, impressora física e modalidades de teste).

### Continuação de 24/10 (09h)

| Entrega | Evidência |
|---|---|
| C-FIND/C-MOVE (Study Root) pelo Core, nós DICOM por organização, porta 4243 pelo DEPLOY | platform run 40092073102 (131/0/0, inclui `test_pacs_qr.py`); deploy-windows run 40092073108: 28/0/1; Windows release run 40092073124: sucesso |
| Medição de distância no Viewer | viewer run 40092073131 (3/3) |

Aceitação 2.9 estendida confirmada no Windows (run 40094435865, 2ª tentativa: 28/0/1): "consulta DICOM 4243 escutando e recusando estação não cadastrada". A 1ª tentativa falhou no download do Orthanc (site indisponível; mesmo SHA-256 na 2ª); o passo passou a tentar 3 vezes e a anotar o motivo (commit `c5ee2bd`).

## 11. Retomada de 27/10/2026 (após interrupção por limite de créditos)

**Verificação inicial:** ramo `develop`; remoto em `39e7a96` (mais novo que o `c87c8a3` citado no comando de retomada);
CI de `39e7a96` todo aprovado — platform run 40104250535 (**135 testes, 0 pulados**), viewer run 40104250565 (**5/5**:
duas séries e queda/volta do motor), deploy-windows run 40104250638 (**28/0/1**), Windows release run 40104250660.
Trabalho local não enviado (RIS/MWL) preservado e concluído.

| Entrega | Evidência |
|---|---|
| RIS — primeira entrega: agendamento, worklist, Modality Worklist por DICOM, ciclo fechado pelo PACS | `tests_platform/test_ris.py` 7/7 local; suíte da plataforma 112 testes locais (2 pulados: binário do Orthanc, só no CI) |
| Defeito corrigido: UID agendado era gerado com a **raiz do pydicom** (`1.2.826.0.1.3680043.8.498`); agora `2.25.<UUID>` | `test_schedule_assigns_uid_and_updates_order` |
| Teste do grafo de migrações generalizado para N ramos (core, pacs, ris) | `tests_platform/test_migrations_graph.py` |

**Achado registrado, sem alteração (preservar o DICOM Print em validação):** o DICOM Print usa a raiz do pydicom nos UIDs
que gera (`app/dicom/print_model.py`, `print_intake.py`, `print_scp.py`, `app/ui/application.py`). Recomendação: raiz
própria do fornecedor ou `2.25`, numa revisão futura do Print, com aprovação (BKL-10).

| Entrega (27/10, cont.) | Evidência |
|---|---|
| Backup e restauração do PACS (exportação verificada e incremental, verificação, restauração idempotente; motor perdido com índice intacto) | `tests_platform/test_pacs_backup.py` 6/6 local; teste com o Orthanc real no CI |
| Comando `worker` passa a ter as mesmas tarefas periódicas do serviço do Windows (sincronização do PACS) | `vyonix/events/worker.py::build_worker` |
| CI do commit do RIS (`326c458`): platform 142 testes, 0 pulados | platform run 40606680321 |
| Saúde detalhada para o administrador (`GET /api/v1/health/detail`): banco, fila de eventos (worker parado), motor DICOM, índice, sincronização, porta de consulta DICOM e licença, com motivo legível e estado ok/atenção/falha | `tests_platform/test_monitoring.py` 5/5 local |

| Entrega (27/10, noite) | Commit | Evidência |
|---|---|---|
| **BKL-10 aprovado e integrado** (UIDs criados pelo DICOM Print em `2.25.<UUID>`; UIDs recebidos e dados guardados intactos) — só para a próxima versão de laboratório; `RELEASE_TAG` continua `v1.0.0-r5` | `215d83f` (merge) | Print 337, plataforma 130, DEPLOY 21 (local); UI Windows da branch e da develop aprovados (runs 40609234009, 40610705126) — `docs/homologacao/BKL-10_UIDs_DICOM_Print.md` |
| Recomendação de raiz UID própria (IANA PEN) e Implementation Class UID | `cfe77e4` | `docs/homologacao/Recomendacao_Raiz_UID_VYONIX.md` |
| PACS: backup automático diário no VyonixWorker, configurado pelo DEPLOY, no monitoramento | `ed1fdf0`, `7c39c4c` | `test_pacs_backup_task.py` 6/6; teste DEPLOY corrigido (separador de caminho no Windows) |
| CI plataforma: numpy nas dependências de teste (teste de compatibilidade Print → PACS era pulado) | `a71acde` | run 40610705143 tinha 162 testes, 0 falhas, 1 pulado |
| RIS: tela Agenda (pedidos pendentes, agendamento, iniciar/concluir/cancelar com motivo) | `7a77c8f` | e2e no navegador (recepcionista e técnico) |
| RIS: duração do exame e recusa de horários sobrepostos na mesma estação ou sala (migração `ris_0002`) | `7a53fb9` | `test_no_overlap_on_same_station_or_room`; e2e recusa na Agenda |
| RIS/Viewer: exame com imagens recebidas abre no Viewer pela Agenda | `d24e022` | e2e agendamento → PACS → recebido → link |
| DEPLOY: diagnóstico aponta backup do PACS ausente, com falha, atrasado ou sem espaço | `6d1ce2b` | `test_diagnose_reports_pacs_backup` |

| RIS: check-in (ARRIVED) e situação do passo na MWL | `96470f0` | `test_check_in_keeps_worklist_and_updates_order`; e2e |
| PACS/RIS: tela Estações DICOM; escolha da estação no agendamento | `d76a54b` | e2e `test_6_dicom_stations`; `test_stations_for_scheduling` |

**CI após o merge do BKL-10:** `7c39c4c` — UI Windows (40610705126), deploy-windows **28/0/1** (40610705105) e Windows
release (40610705173, release `v1.0.0-r5` não substituída) aprovados; platform 40610705143 com 162 testes e 0 falhas,
mas 1 pulado (falta de numpy, corrigido em `a71acde`). `96470f0` — platform **167 testes, 0 pulados** (40614419360),
viewer **5/5** (40614419201), deploy-windows **28/0/1** (40614419271), Windows release (40614419238) aprovados.

`e8d7a23` (só interface web, API do RIS e documentação; nenhum código do DICOM Print): platform **169/0/0**
(40617699999), viewer **5/5** (40617700014). Na 1ª tentativa, deploy-windows falhou no download do Orthanc oficial e a
Windows release terminou o passo de testes com código 1 apesar de **337 aprovados, 0 falhas**; reexecução das jobs com
falha (mesmo commit): Windows release aprovada e deploy-windows **28/0/1**. Registradas como **instabilidades a
observar** (rede do download; código de saída do pytest no Windows após todos os testes aprovados).

| CI Windows: cache do Orthanc oficial conferido pelo SHA-256; código de saída do pytest com JUnit limpo vira aviso | `f6eb88f` | platform, deploy-windows **28/0/1** e Windows release aprovados (40621896693, 40621896676, 40621896652) |
| RIS: **MPPS SCP** (N-CREATE/N-SET) — início, conclusão e interrupção na modalidade atualizam o agendamento (`ris_0003`) | `52671dd` | 3 testes com associação DICOM real; platform **172/0/0** (40625193378), viewer 5/5 (40625193340), deploy-windows **28/0/1** (40625193375), Windows release (40625193382; `v1.0.0-r5` não substituída) |

**Pendências:** ensaios no laboratório da correção BKL-10 (modalidades de teste e impressora física) antes de uma
nova versão de laboratório; troca do Implementation Class UID (aprovação própria, após raiz VYONIX); imagem do Print
sem Patient ID não entra no PACS (por projeto; encaminhamento futuro exige identificação); salas/recursos cadastrados,
check-in e MPPS no RIS.

## 12. Continuação de 28/10/2026

| Entrega | Commit | Evidência |
|---|---|---|
| CI Windows: GPLv3 do Orthanc versionada e conferida (o download do gnu.org falhava; era a causa das falhas sem anotação do passo do Orthanc), sem conversão de fim de linha; saída explícita do passo de testes da Windows release | `02d46b1`, `4ffdc93` | e489d1a: deploy-windows e Windows release falharam (download GPL; pytest com **339 aprovados, 0 falhas** e saída `0xC0000409` no encerramento do processo) → corrigido |
| DEPLOY: pasta e hora do backup do PACS no assistente | `eb3b8f7` | `tests_deploy` 22/22 |
| Aceitação Windows 2.9: C-STORE de modalidade simulada no motor → indexado pelo Worker → `pacs-backup` pelo executável do produto (arquivo idêntico) → `pacs-verify` | `eb3b8f7` | deploy-windows 40673396855 reprovou só a comparação byte a byte (o motor regrava o File Meta); corrigido em `74da54f` → deploy-windows 40678091138 **29/0/1**: C-STORE → motor → indexado → backup (1 instância) → objeto idêntico (UIDs, paciente, pixels) → manifesto válido |
| RIS: situação informada pela modalidade (MPPS) na Agenda | `82a5e0e` | `test_mpps_in_progress_completed_and_rules` |
| PACS: verificação contínua da integridade do armazenamento (Worker, lotes com cursor, só registra; monitoramento “falha”) | `26945f5` | `test_pacs_integrity_task.py` 2/2; platform **174/0/0** (40673396971), viewer 5/5 (40673396856) |

| **VYONIX REPORT — primeira entrega**: modelos, rascunho, liberação com confirmação de senha, versões imutáveis (SHA-256; banco sem UPDATE/DELETE para a aplicação), adendos, achado crítico (evento), verificação, papel Médico, tela Laudos | `0596b65` | `test_report.py`; e2e 7/7 |
| REPORT: PDF do laudo liberado; comunicação de achado crítico (`report_0002`); correção da tela (senha recusada deixava o rascunho com versão desatualizada) | `33dda63`, `3402531`, `398ea3f` | `test_report.py` 5/5; e2e `test_7_report_flow`; platform 147 local |

| Confirmação de senha no ato bloqueada após 5 erros em 15 min; RIS: salas cadastradas (`ris_0004`); Início com pendências por papel | `94943a1`, `bc89131`, `173c9b2` | `test_report.py`, `test_ris.py`, e2e 7/7; platform 148 local |

**CI de `5767a66` (REPORT incluído):** platform **180/0/0** (40682713999), viewer **5/5** (40682713953), deploy-windows
**29/0/1** (40682713933, com o backup do PACS real no Windows), Windows release (40682714100; `v1.0.0-r5` não substituída).

**CI de `b98dc02`:** platform **181/0/0** (40687347852), viewer **5/5** (40687347846), deploy-windows **29/0/1**
(40687347923), Windows release (40687347828; `v1.0.0-r5` não substituída). Local depois: `063076e` (laudo na ficha
do paciente) — e2e 7/7.

**CI de `cf4d7be`:** platform, viewer, deploy-windows **29/0/1** (40692296911) e Windows release aprovados.

| Entrega (28/10, tarde) | Commit | Evidência |
|---|---|---|
| Requisitos do TELELAUDO multicliente registrados (TEL-01…16, BKL-11), sem iniciar a implementação | `1dc22f0` | `docs/platform/Telelaudo_Multicliente_Requisitos.md` |
| `npm audit` da interface web no CI (BKL-03 concluído) | `610f10f` | 0 vulnerabilidades (platform 40697537395) |
| Transferência incompleta pelo MPPS × PACS (`ris_0005`) | `f6f53f3` | `test_mpps_performed_images_vs_pacs` |
| Tela Conciliação de estudos sem pedido (BKL-06 concluído) | `1d15da9` | e2e `test_8_reconcile_flow`; platform 150 local |

**CI de `7804f57`:** platform **183/0/0** (40697537395), viewer **5/5** (40697537355), deploy-windows **29/0/1**
(40697537396), Windows release (40697537456; `v1.0.0-r5` não substituída).

**Retomada de 28/10, 12h50:** o desenvolvimento tinha parado porque a resposta anterior terminou sem nenhuma espera
pendente (não houve erro nem bloqueio); o contêiner foi reciclado por inatividade e o PostgreSQL de testes religado.
Retornos agendados nesta sessão passam a garantir a continuidade.

**CI de `f39b8e9` (TELELAUDO T1):** platform, viewer, deploy-windows **29/0/1** (40720905755) e Windows release
aprovados. Depois, locais: T2 `285dfb8`, T3 `cc9140a`, T4 `50570e8`, T5 `6ca6896`, T6 `5c1c524`, T7 `2e30bf4` —
platform **168** testes locais, e2e 8/8.

**CI de `f4b1fea`:** platform, viewer, deploy-windows (40726845928) e Windows release aprovados. Enviados depois:
T8 `63205f1`, `f098374`, assinatura manuscrita `0d3e05d` e C-GET `72abd86` (platform e viewer aprovados; Windows em andamento). Locais depois: resumo do MPPS `a83c00a`, Central de exames `6d6aa78`, retenção do PACS — platform **186** local, e2e 8/8.

**Prompt Mestre (28/10, 14h29) — multi-institucional, licenciamento centralizado, perfis dinâmicos:** auditoria e
matriz em `docs/platform/Prompt_Mestre_Auditoria_e_Matriz.md`. Fase 2 (primeira parte) feita: diretório global de
logins (`core_0002`; login só com usuário e senha no servidor com várias instituições, identificador único na
plataforma, contas independentes; logins repetidos antigos continuam com o código da organização), delegação
limitada (ninguém concede permissão que não tem nem altera conta mais privilegiada), modelos de perfil opcionais
(Coordenador do CDI, Gestor de Telelaudos, Financeiro, Técnico de Suporte) e estruturas (clínica pequena, CDI,
hospital) — `test_access_multiinst.py` 4/4 com Clínica Alfa, Hospital Beta e CDI Gama fictícios. Decisão pendente
do proprietário antes da Fase 5: onde fica a chave de emissão de licenças (o teste de arquitetura proíbe chave
privada na plataforma; BLK-01).

**Assinatura manuscrita digitalizada no cadastro médico (pedido de 28/10, tarde) — implementada, não validada para
uso clínico:** imagem JPG/JPEG/PNG/WEBP com recorte, brilho, contraste e remoção do fundo branco; fica pendente até o
médico confirmar com a senha; administrador só envia se o médico o designou; cifrada, privada, auditada (envio,
confirmação, autorização, exclusão, designação, visualização administrativa e uso em cada documento); inserida só no
laudo liberado pelo próprio médico; rascunho com marca d'água e sem assinatura; bloco configurável no modelo;
liberação em lote com confirmação explícita, senha e auditoria por laudo; PAdES preparado e recusando (BLK-14).
Testes: `test_report_signature_lifecycle.py` 11/11, platform **182** local (2 ignorados por falta do Orthanc local,
cobertos no CI), e2e 8/8. Regressão ajustada: `test_report_signature.py` (ciclo com confirmação). A imagem continua
sendo apenas elemento visual; nada disso libera laudos clínicos reais.

**Decisão pendente do proprietário (REPORT):** assinatura digital do laudo (ICP-Brasil: certificado A1/A3, padrão
PAdES/CAdES, carimbo de tempo). Até lá a liberação é por confirmação de senha, registrada e verificável, e a tela
informa que não é assinatura digital.

**Instabilidade conhecida:** o processo do pytest no Windows às vezes termina com `0xC0000409` depois de todos os
testes aprovados (encerramento do interpretador). A Windows release registra aviso quando o JUnit está limpo e
continua reprovando qualquer falha ou erro de teste. Investigar a origem (Qt/threads no encerramento).

## Sessão de 2026-10-28 (noite) — estudo dcm4chee/J4Care e evolução autônoma

**Pedido:** Prompt Mestre "Estudo do dcm4chee, evolução do PACS e desenvolvimento autônomo" + complemento J4Care
SMooTH (VNA, Viewer, VNEdge, VNIN). Estudo e matriz: `docs/platform/Estudo_Referencias_dcm4chee_J4Care.md`.

| Commit | Entrega | Testes |
|---|---|---|
| `344ab09` | DEPLOY: assistente abre o navegador por atalho `.url` (relato da homologação: abria a pasta Documentos); atalhos de homologação | `tests_deploy/test_wizard.py`; homologação no Windows 13/13 (run 40783644239) |
| `485df19` | **Nós DICOM**: cadastro completo do equipamento, edição auditada, C-ECHO, status, histórico de conexões (Q/R aceitas/recusadas com motivo, C-STORE, C-MOVE recusado), política de recepção `pacs/reception` (padrão = qualquer equipamento; opcional = só cadastrados, com retenção sem exclusão e decisão do admin); migração `pacs_0006` (aditiva) | `test_pacs_nodes.py` 6/6; `test_pacs_orthanc.py::test_reception_only_from_registered_equipment` (Orthanc real, CI); e2e Nós DICOM |
| `57ca030` | **Minha Produção**: dia, mês, período, unidade, modalidade, pendências, tempo médio, CSV/PDF; permissões own/all/financial; tabela de valores opcional | `test_report_production.py` 3/3; e2e roteiro (r10) |
| `69459b5` | **Fluxo do exame** configurável (`ris/workflow`: agendamento e worklist, com dependência) e **linha do tempo do exame** | `test_ris_workflow.py` |
| `2fcf974` | Estudo dcm4chee × SMooTH × VYONIX; **exames anteriores** do paciente (preparação e laudo); **alerta de espaço em disco** no monitoramento | `test_ris_workflow.py::test_priors_of_same_patient`; `test_monitoring.py::test_disk_space_levels_grouped_by_volume` |

**Regressão local:** `tests_platform` completo 215 OK antes do último ciclo (2 dependentes do Orthanc só no CI);
módulos afetados reexecutados depois de cada mudança (PACS, Q/R, RIS, laudos, monitoramento, e2e 18/18).

**Preservado:** comportamento homologado de recepção (aceita qualquer equipamento por padrão), BKL-10, instalação do
DICOM Print, configuração do Orthanc instalada pelo DEPLOY. Nenhuma exclusão automática de estudos.

**Próxima tarefa programada:** ver `VYONIX_NEXT_ACTION.md`.
