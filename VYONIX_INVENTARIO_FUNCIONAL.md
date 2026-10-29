# VYONIX — Inventário funcional (auditoria geral de 29/10/2026)

**Escopo:** VYONIX Medical Platform. **O VYONIX DICOM Print está excluído** deste inventário e dos cálculos.
Referência: ramo `develop`, commit `d29d391`. Gerado por `tools/auditoria_inventario.py` (critérios no cabeçalho do script). “Validada” = testes automatizados aprovados no CI com os componentes reais do caminho; **nenhum item tem validação clínica nem teste prático concluído com usuários reais.**

Legenda: **IMPLEMENTADA E VALIDADA** · **IMPLEMENTADA, MAS NÃO VALIDADA** · **PARCIALMENTE IMPLEMENTADA** · **NÃO IMPLEMENTADA** · **BLOQUEADA** · **NÃO VERIFICADA** · **PROTÓTIPO (não funcional)**

## Conclusão estimada por módulo

| Módulo | Itens | Validadas | Não validadas | Parciais | Não implementadas | Bloqueadas | Não verificadas | Protótipo | Implementação | Validação |
|---|---|---|---|---|---|---|---|---|---|---|
| PACS | 22 | 18 | 2 | 0 | 1 | 1 | 0 | 0 | 91% | 82% |
| Viewer | 14 | 8 | 0 | 0 | 2 | 0 | 4 | 0 | 57% | 57% |
| RIS | 15 | 11 | 1 | 2 | 1 | 0 | 0 | 0 | 87% | 73% |
| Telelaudo | 14 | 11 | 0 | 1 | 2 | 0 | 0 | 0 | 82% | 79% |
| Editor de laudos | 11 | 7 | 0 | 1 | 2 | 1 | 0 | 0 | 68% | 64% |
| Usuários e permissões | 9 | 9 | 0 | 0 | 0 | 0 | 0 | 0 | 100% | 100% |
| Cadastro médico | 7 | 6 | 0 | 0 | 1 | 0 | 0 | 0 | 86% | 86% |
| Produção médica | 5 | 4 | 0 | 1 | 0 | 0 | 0 | 0 | 90% | 80% |
| Administração | 9 | 6 | 1 | 0 | 1 | 0 | 1 | 0 | 78% | 67% |
| Infraestrutura e deploy | 13 | 9 | 1 | 0 | 1 | 1 | 1 | 0 | 77% | 69% |
| Arquitetura híbrida (Edge) | 4 | 1 | 0 | 0 | 0 | 1 | 0 | 2 | 38% | 25% |
| Segurança e conformidade | 12 | 6 | 0 | 2 | 1 | 3 | 0 | 0 | 58% | 50% |
| **Total (pesos iguais por item)** | 135 |  |  |  |  |  |  |  | **78%** | **71%** |

Os percentuais medem a cobertura **deste inventário** (requisitos levantados dos prompts do proprietário e das referências), não o esforço restante nem prontidão clínica. Itens de peso muito diferente (ex.: assinatura ICP-Brasil × zoom) contam igual; por isso servem para comparar módulos, não para prazo.

## PACS

| Funcionalidade | Estado | Evidência | Pendência | Prioridade |
|---|---|---|---|---|
| Recepção DICOM (C-STORE no motor) e indexação | IMPLEMENTADA E VALIDADA | vyonix/pacs/service.py (ingest, sync); test_pacs.py, test_pacs_orthanc.py; CI deploy-windows (Windows Server 2022), run 40896603020: 34 aprovados, 0 reprovados, 1 não executado (2.9); CI homologação (instalador de homologação, roteiro 13/13), run 40896631587 | Equipamento real (BLK-02) | P1 |
| Armazenamento (Orthanc 1.13 sem plugins; SHA-256 na entrada e na saída) | IMPLEMENTADA E VALIDADA | vyonix/pacs/orthanc.py, ADR-0012; test_pacs_orthanc.py | Revisão jurídica da distribuição (BLK-07) | P1 |
| Organização de pacientes e estudos (índice por organização, RLS, registro clínico, conciliação) | IMPLEMENTADA E VALIDADA | pacs_0001..0005; test_pacs.py, test_clinical.py, test_pacs_cloud_isolation.py | — | — |
| Cadastro de dispositivos (nós DICOM: fabricante, modelo, modalidade, unidade, serviços, status) | IMPLEMENTADA E VALIDADA | vyonix/pacs/nodes.py, pacs_0006, tela Nós DICOM; test_pacs_nodes.py, test_e2e_web.py::test_6 | Teste com equipamento real (BLK-02) | P1 |
| Gerenciamento de AE Titles (nós por organização; rotas de AE no modo nuvem) | IMPLEMENTADA E VALIDADA | pacs_0002/0003; test_pacs_cloud_isolation.py, test_pacs_qr.py | — | — |
| C-ECHO (SCP no Q/R e no motor; SCU de teste a partir do cadastro) | IMPLEMENTADA E VALIDADA | dimse_qr.py, nodes.echo; test_pacs_nodes.py::Echo | — | — |
| C-STORE SCP (recepção) e SCU (envio por C-MOVE e encaminhamento) | IMPLEMENTADA E VALIDADA | test_pacs_orthanc.py, test_pacs_qr.py, test_pacs_forward.py | — | — |
| C-FIND (Study Root: estudo, série, imagem) | IMPLEMENTADA E VALIDADA | dimse_qr.py; test_pacs_qr.py | Patient Root não implementado | P2 |
| C-MOVE (só para nós com permissão de receber; SHA-256 conferido) | IMPLEMENTADA E VALIDADA | test_pacs_qr.py | — | — |
| C-GET (só para o nó solicitante com permissão de receber) | IMPLEMENTADA E VALIDADA | test_pacs_qr.py | — | — |
| DICOMweb STOW-RS / QIDO-RS / WADO-RS (metadados e frames) | IMPLEMENTADA E VALIDADA | routes_pacs.py; test_pacs.py; CI viewer (Chromium + Orthanc real), run 40896603037 | Teste de carga | P2 |
| Roteamento automático (regras por origem/modalidade, envio manual, novas tentativas) | IMPLEMENTADA, MAS NÃO VALIDADA | vyonix/pacs/forward.py, pacs_0007; test_pacs_forward.py (Storage SCP real, motor DUBLÊ) | Teste com Orthanc real e no serviço Worker do Windows | P2 |
| Storage Commitment (SCP) | IMPLEMENTADA, MAS NÃO VALIDADA | vyonix/pacs/commitment.py; test_pacs_commitment.py (pynetdicom real, motor DUBLÊ) | Teste com modalidade real; Orthanc real | P2 |
| Controle de duplicidade (reenvio idempotente; conteúdo divergente recusado) | IMPLEMENTADA E VALIDADA | service.ingest; test_pacs.py, test_pacs_orthanc.py | — | — |
| Quarentena (nuvem: sem rota/licença; local: equipamento não autorizado retido) | IMPLEMENTADA E VALIDADA | cloud_sync, pacs.store_holds; test_pacs_cloud_isolation.py, test_pacs_orthanc.py::test_reception_only_from_registered_equipment | Recusa já na associação (BLK-15) | P2 |
| Integração entre clínicas (compartilhar estudos entre instituições) | NÃO IMPLEMENTADA | Só compartilhamento temporário dentro da instituição (ris.exam.share) | Desenho de consentimento, vínculo e auditoria entre organizações | P3 |
| Políticas de armazenamento: retenção (relatório e guarda obrigatória) | IMPLEMENTADA E VALIDADA | vyonix/pacs/retention.py; test_pacs_retention.py | Exclusão por retenção exige política aprovada | P3 |
| Exclusão automática por retenção / camadas de armazenamento / compressão | BLOQUEADA | Não implementado por decisão (sem política aprovada) | Aprovação do proprietário e jurídico | P3 |
| Auditoria (entrada, recusa, abertura, Q/R, nós, envios) | IMPLEMENTADA E VALIDADA | vyonix/audit; test_core.py (cadeia), test_pacs*.py | — | — |
| Backup diário verificado e restauração | IMPLEMENTADA E VALIDADA | pacs/backup.py, backup_task.py; test_pacs_backup*.py; CI deploy-windows (Windows Server 2022), run 40896603020: 34 aprovados, 0 reprovados, 1 não executado (2.7, 2.9) | Backup sem criptografia própria | P2 |
| Verificação contínua de integridade | IMPLEMENTADA E VALIDADA | integrity_task.py; test_pacs_integrity_task.py | — | — |
| Histórico de conexões DICOM e recepção só de equipamentos cadastrados | IMPLEMENTADA E VALIDADA | pacs.dicom_events, pacs/reception; test_pacs_nodes.py, test_pacs_orthanc.py | — | — |

## Viewer

| Funcionalidade | Estado | Evidência | Pendência | Prioridade |
|---|---|---|---|---|
| Abertura de estudos no navegador (OHIF 3.13 na mesma origem) | IMPLEMENTADA E VALIDADA | viewer/, routes viewer; tests_viewer/test_viewer_e2e.py; CI viewer (Chromium + Orthanc real), run 40896603037 | Navegadores além do Chromium | P2 |
| Navegação entre imagens e séries | IMPLEMENTADA E VALIDADA | test_viewer_e2e.py::test_multi_series_navigation | — | — |
| Zoom | IMPLEMENTADA E VALIDADA | test_viewer_e2e.py::check_tools | — | — |
| Pan | NÃO VERIFICADA | Ferramenta do OHIF; não exercitada nos testes | Incluir no teste do Viewer | P2 |
| Janela/nível, inverter, girar | IMPLEMENTADA E VALIDADA | test_viewer_e2e.py::check_tools | — | — |
| Medição de distância | IMPLEMENTADA E VALIDADA | test_viewer_e2e.py::check_length (Pixel Spacing 0,5 mm) | Sem validação clínica de medidas | P2 |
| Anotações (seta, texto, ROI) | NÃO VERIFICADA | Ferramentas do OHIF; não exercitadas nos testes | Testar e decidir quais liberar | P2 |
| Reconstrução multiplanar (MPR) | NÃO VERIFICADA | Não configurada nem testada | Configurar e testar com volume sintético | P3 |
| Comparação lado a lado de exames | NÃO IMPLEMENTADA | Sem protocolo de exibição configurado | Protocolo de exibição com anterior | P2 |
| Exames anteriores (lista para comparação) | IMPLEMENTADA E VALIDADA | ris/timeline.priors; test_ris_workflow.py::test_priors_of_same_patient | Abrir anterior e atual juntos no Viewer | P2 |
| Ferramentas por modalidade | NÃO IMPLEMENTADA | — | Definir conjuntos por modalidade | P3 |
| Desempenho (estudos grandes) | NÃO VERIFICADA | Sem teste de carga | Teste com estudo de TC/RM grande sintético | P2 |
| Integração com o PACS (DICOMweb do Core, cookie da sessão) | IMPLEMENTADA E VALIDADA | test_viewer_serving.py, test_viewer_e2e.py | — | — |
| Controle de acesso (sessão, permissão pacs.studies.read, auditoria de abertura) | IMPLEMENTADA E VALIDADA | test_viewer_serving.py, test_pacs.py | — | — |

## RIS

| Funcionalidade | Estado | Evidência | Pendência | Prioridade |
|---|---|---|---|---|
| Cadastro de pacientes (identificadores, mescla e desfazer) | IMPLEMENTADA E VALIDADA | vyonix/clinical; test_clinical.py; CI homologação (instalador de homologação, roteiro 13/13), run 40896631587 | — | — |
| Cadastro de exames/procedimentos | IMPLEMENTADA E VALIDADA | clinical.save_procedure; test_ris.py | — | — |
| Solicitações (pedidos) | IMPLEMENTADA E VALIDADA | clinical.create_order; test_ris.py, test_clinical.py | — | — |
| Agendamento (conflito de sala/estação, duração) | IMPLEMENTADA E VALIDADA | ris/service.schedule; test_ris.py | — | — |
| Agenda por modalidade e sala | IMPLEMENTADA E VALIDADA | ris_0004 salas; test_ris.py; tela Agenda | — | — |
| Modality Worklist (C-FIND MWL) | IMPLEMENTADA E VALIDADA | dimse_qr._worklist; test_ris.py | Modalidade real (BLK-02) | P1 |
| Situação do atendimento (chegada, em realização, MPPS, recebido) | IMPLEMENTADA E VALIDADA | ris_0003/0005; test_ris.py, test_ris_technician.py | — | — |
| Histórico do paciente | PARCIALMENTE IMPLEMENTADA | Exames anteriores e linha do tempo por exame (test_ris_workflow.py); sem tela única de histórico | Tela de histórico do paciente | P2 |
| Cadastro de convênios | NÃO IMPLEMENTADA | Nenhum modelo, rota ou tela | Definir escopo (faturamento/autorização) | P2 |
| Integração com o PACS (UID do agendamento, recebido, conciliação) | IMPLEMENTADA E VALIDADA | ris.register_consumers; test_ris.py, test_ris_prep.py | — | — |
| Integração com modalidades (MWL/MPPS) | IMPLEMENTADA, MAS NÃO VALIDADA | Só com SCU simulado (pynetdicom) | Teste com equipamento real (BLK-02) | P1 |
| Integração HL7 v2 | PARCIALMENTE IMPLEMENTADA | Saída ORU do laudo (report/interop.py; test_report_interop.py); sem entrada ADT/ORM (MLLP) | Receptor HL7 ADT/ORM | P2 |
| Relatórios operacionais (Central de exames: etapas, atrasos, tempos) | IMPLEMENTADA E VALIDADA | ris/tracking.py; test_ris_exam_center.py | Exportação dos relatórios | P3 |
| Central de Exames e preparação técnica (checklist, anexos, comentários, encaminhamento) | IMPLEMENTADA E VALIDADA | ris/prep.py; test_ris_prep.py, test_e2e_prep.py; CI homologação (instalador de homologação, roteiro 13/13), run 40896631587 | — | — |
| Fluxo do exame configurável e linha do tempo | IMPLEMENTADA E VALIDADA | ris/workflow, ris/timeline.py; test_ris_workflow.py | — | — |

## Telelaudo

| Funcionalidade | Estado | Evidência | Pendência | Prioridade |
|---|---|---|---|---|
| Recebimento de exames na fila | IMPLEMENTADA E VALIDADA | report/queue.py; test_report_queue.py; CI homologação (instalador de homologação, roteiro 13/13), run 40896631587 | — | — |
| Fila de trabalho com escopo por vínculo/unidade | IMPLEMENTADA E VALIDADA | test_report_queue.py::test_scope_by_unit | — | — |
| Distribuição entre médicos (manual, fixo, equilibrada) e reserva | IMPLEMENTADA E VALIDADA | report/distribution.py; test_ris_prep.py | — | — |
| Atribuição manual | IMPLEMENTADA E VALIDADA | test_report_queue.py | — | — |
| Atribuição automática | IMPLEMENTADA E VALIDADA | test_ris_prep.py (distribuição fixa e equilibrada) | Regras por modalidade/unidade | P2 |
| Prioridades e urgências | IMPLEMENTADA E VALIDADA | test_report_queue.py, test_ris_prep.py | — | — |
| Acompanhamento de prazos (SLA) | IMPLEMENTADA E VALIDADA | queue.SLA_HOURS; test_report_queue.py | Alertas de atraso (notificação) | P2 |
| Elaboração de laudos | IMPLEMENTADA E VALIDADA | report/service.py; test_report.py; CI homologação (instalador de homologação, roteiro 13/13), run 40896631587 (passo 13) | — | — |
| Revisão (segunda leitura / dupla assinatura) | NÃO IMPLEMENTADA | — | Definir fluxo de revisão | P2 |
| Retificação (adendos versionados) | IMPLEMENTADA E VALIDADA | service.addendum; test_report.py | — | — |
| Finalização e liberação (confirmação por senha; versões imutáveis com SHA-256) | IMPLEMENTADA E VALIDADA | test_report.py, test_report_signature_lifecycle.py | Não é assinatura digital ICP-Brasil (BLK-14) | P1 |
| Entrega ao paciente/solicitante | PARCIALMENTE IMPLEMENTADA | PDF, FHIR, HL7 ORU e DICOM PDF (test_report_interop.py); sem portal nem envio | Portal do paciente / envio | P2 |
| Histórico e auditoria do laudo | IMPLEMENTADA E VALIDADA | report_versions, audit; test_report.py | — | — |
| Rede de médicos entre instituições (telelaudo multiorganização) | NÃO IMPLEMENTADA | Médicos são cadastrados por instituição | Desenho de vínculo entre organizações | P3 |

## Editor de laudos

| Funcionalidade | Estado | Evidência | Pendência | Prioridade |
|---|---|---|---|---|
| Editor de texto | PARCIALMENTE IMPLEMENTADA | Campo de texto simples com seções do modelo (web/src/pages/reports.tsx) | Editor com formatação | P1 |
| Formatação avançada (negrito, listas, tabelas) | NÃO IMPLEMENTADA | — | Editor rico com saída segura no PDF | P2 |
| Importação de modelos Word (DOCX) | IMPLEMENTADA E VALIDADA | report/docx_import.py; test_report_docx.py | — | — |
| Templates versionados com seleção automática | IMPLEMENTADA E VALIDADA | report/templates.py; test_report_templates.py | — | — |
| Presets / frases rápidas / textos básicos | NÃO IMPLEMENTADA | — | Biblioteca de frases por médico e modalidade | P2 |
| Cabeçalhos e rodapés (identidade visual por organização e unidade) | IMPLEMENTADA E VALIDADA | report/branding.py; test_report_branding.py | — | — |
| Geração de PDF | IMPLEMENTADA E VALIDADA | report/pdf.py; test_report.py; CI homologação (instalador de homologação, roteiro 13/13), run 40896631587 | — | — |
| Assinatura manuscrita digitalizada (elemento visual autorizado) | IMPLEMENTADA E VALIDADA | report/signature.py; test_report_signature_lifecycle.py | — | — |
| Assinatura digital ICP-Brasil / PAdES | BLOQUEADA | report/pades.py recusa (BLK-14) | Decisão de padrão e certificados | P1 |
| Controle de versões e histórico | IMPLEMENTADA E VALIDADA | report_versions; test_report.py | — | — |
| Proteção de documentos finalizados | IMPLEMENTADA E VALIDADA | versões imutáveis + verificação SHA-256; test_report.py | — | — |

## Usuários e permissões

| Funcionalidade | Estado | Evidência | Pendência | Prioridade |
|---|---|---|---|---|
| Cadastro administrativo de usuários | IMPLEMENTADA E VALIDADA | auth/service.py; test_core.py, test_e2e_web.py | — | — |
| Perfis (papéis padrão, modelos opcionais, papéis personalizados) | IMPLEMENTADA E VALIDADA | manifest.DEFAULT_ROLES/ROLE_TEMPLATES, save_role; test_access_multiinst.py | — | — |
| Permissões por módulo e por operação (backend valida) | IMPLEMENTADA E VALIDADA | needs(...); test_api.py::test_role_permissions | — | — |
| Alteração administrativa e auditoria de permissões | IMPLEMENTADA E VALIDADA | test_access_multiinst.py, audit | — | — |
| Isolamento entre instituições (RLS forçado) | IMPLEMENTADA E VALIDADA | test_core.py (RLS), test_pacs_cloud_isolation.py, test_architecture.py | — | — |
| Cadastros independentes por instituição e login só com usuário e senha | IMPLEMENTADA E VALIDADA | auth/directory.py, core_0002; test_access_multiinst.py, test_e2e_cloud.py | — | — |
| Revogação de acesso (desativar usuário, bloqueio, sessão expira) | IMPLEMENTADA E VALIDADA | auth.update_user(active); test_core.py | — | — |
| Proteção contra acesso indevido por API (sessão, CSRF, cabeçalhos) | IMPLEMENTADA E VALIDADA | test_api.py | Teste de intrusão externo | P2 |
| MFA (TOTP) e política de senha | IMPLEMENTADA E VALIDADA | test_core.py::test_mfa_* | — | — |

## Cadastro médico

| Funcionalidade | Estado | Evidência | Pendência | Prioridade |
|---|---|---|---|---|
| Cadastro administrativo (CRM/UF, especialidades, RQE, rodapé) | IMPLEMENTADA E VALIDADA | report/physicians.py; test_report.py, test_e2e_roteiro.py | Validação de CRM em base oficial | P3 |
| Vínculos institucionais por unidade e vigência | IMPLEMENTADA E VALIDADA | physician_links; test_report_queue.py | — | — |
| Upload, recorte e tratamento da assinatura manuscrita | IMPLEMENTADA E VALIDADA | test_report_signature_lifecycle.py | — | — |
| Proteção da assinatura (cifrada, autorização do médico, auditoria de uso) | IMPLEMENTADA E VALIDADA | test_report_signature_lifecycle.py | — | — |
| Médico não altera o próprio cadastro administrativo | IMPLEMENTADA E VALIDADA | report.physicians.manage fora do papel 'medico'; test_api.py | — | — |
| Permissões de elaboração/liberação de laudos | IMPLEMENTADA E VALIDADA | report.write/report.sign; test_report*.py | — | — |
| Templates pessoais do médico | NÃO IMPLEMENTADA | Modelos são da instituição (report.templates.manage) | Modelos pessoais com permissão | P2 |

## Produção médica

| Funcionalidade | Estado | Evidência | Pendência | Prioridade |
|---|---|---|---|---|
| Minha Produção (dia, mês, período, unidade, modalidade, pendências, tempo médio) | IMPLEMENTADA E VALIDADA | report/production.py; test_report_production.py; test_e2e_roteiro.py (r10) | — | — |
| Relatório PDF e exportação CSV (Excel) | IMPLEMENTADA E VALIDADA | test_report_production.py | Arquivo .xlsx nativo | P3 |
| Produção financeira | PARCIALMENTE IMPLEMENTADA | Tabela de valor por modalidade (report/production) | Valores por procedimento/convênio, fechamento mensal | P2 |
| Permissão independente para valores financeiros | IMPLEMENTADA E VALIDADA | report.production.financial; test_report_production.py | — | — |
| Isolamento entre médicos e regra de contagem documentada | IMPLEMENTADA E VALIDADA | test_report_production.py; docstring de production.py | — | — |

## Administração

| Funcionalidade | Estado | Evidência | Pendência | Prioridade |
|---|---|---|---|---|
| Gestão de instituições (operadora VYONIX, modo nuvem) | IMPLEMENTADA E VALIDADA | tenancy/platform_admin.py; test_platform_admin.py, test_e2e_cloud.py | — | — |
| Gestão de usuários, unidades, salas (modalidades) e nós DICOM | IMPLEMENTADA E VALIDADA | telas Usuários, Unidades, Agenda→Salas, Nós DICOM; test_e2e_web.py | — | — |
| Configurações com histórico e motivo | IMPLEMENTADA E VALIDADA | settings/service.py; test_core.py::test_settings_* | — | — |
| Auditoria encadeada (tela e verificação) | IMPLEMENTADA E VALIDADA | audit; test_core.py::test_chain_and_tamper_detection | — | — |
| Monitoramento (serviços, motor, Q/R, backup, integridade, licença, disco) | IMPLEMENTADA E VALIDADA | monitoring.py; test_monitoring.py | — | — |
| Alertas (notificação ativa por e-mail/mensagem) | NÃO IMPLEMENTADA | Só painel; módulo NOTIFY planejado | Notificações | P2 |
| Logs técnicos (arquivos dos serviços, relatórios do DEPLOY) | IMPLEMENTADA, MAS NÃO VALIDADA | winservice.py (RotatingFileHandler); sem tela | Tela de logs para suporte | P3 |
| Menus por perfil e menu lateral recolhível | IMPLEMENTADA E VALIDADA | web/src/app.tsx; test_e2e_web.py | — | — |
| Usabilidade avaliada com usuários | NÃO VERIFICADA | Sem teste com usuários reais | Avaliação prática do proprietário (em curso) | P1 |

## Infraestrutura e deploy

| Funcionalidade | Estado | Evidência | Pendência | Prioridade |
|---|---|---|---|---|
| Instalador Windows com dependências (PostgreSQL 17, Orthanc, Viewer) | IMPLEMENTADA E VALIDADA | installer/VyonixPlatform.iss, deploy-windows.yml; CI deploy-windows (Windows Server 2022), run 40896603020: 34 aprovados, 0 reprovados, 1 não executado | Assinatura de código (BLK-08) | P1 |
| Serviços do Windows com início automático, sem login, dependências e recuperação | IMPLEMENTADA E VALIDADA | steps/services.py; CI deploy-windows (Windows Server 2022), run 40896603020: 34 aprovados, 0 reprovados, 1 não executado (2.3, 2.5) | — | — |
| Recuperação de falhas (processo do Core encerrado; banco derrubado e recuperado) | IMPLEMENTADA E VALIDADA | winservice.db_watchdog; test_db_watchdog.py; CI deploy-windows (Windows Server 2022), run 40896603020: 34 aprovados, 0 reprovados, 1 não executado (2.5, 2.10) | — | — |
| Inicialização após reiniciar o computador | NÃO VERIFICADA | Coberto indiretamente (início automático + dependências); o runner do CI não reinicia | Teste real de reinicialização (BLK-04) | P0 |
| Acesso por localhost e pelo IP da rede (HTTPS; http:// redireciona) | IMPLEMENTADA E VALIDADA | https_server.py, firewall Público/LocalSubnet; test_https_server.py; CI deploy-windows (Windows Server 2022), run 40896603020: 34 aprovados, 0 reprovados, 1 não executado (2.10) | Confirmação na instalação real do proprietário | P0 |
| Frontend e backend disponíveis após instalar | IMPLEMENTADA E VALIDADA | CI deploy-windows (Windows Server 2022), run 40896603020: 34 aprovados, 0 reprovados, 1 não executado (2.5, 2.10); CI homologação (instalador de homologação, roteiro 13/13), run 40896631587 | — | — |
| Diagnóstico de inicialização (sem administrador) e reparo | IMPLEMENTADA E VALIDADA | vyonix_deploy/startup.py, diagnose.py; test_startup.py; CI deploy-windows (Windows Server 2022), run 40896603020: 34 aprovados, 0 reprovados, 1 não executado (2.7, 2.10) | — | — |
| Porta ocupada (detectada e reparada) | IMPLEMENTADA E VALIDADA | CI deploy-windows (Windows Server 2022), run 40896603020: 34 aprovados, 0 reprovados, 1 não executado (2.1, 2.7) | — | — |
| Atualização preservando dados (backup antes da migração) | IMPLEMENTADA E VALIDADA | steps/update.py; CI deploy-windows (Windows Server 2022), run 40896603020: 34 aprovados, 0 reprovados, 1 não executado (2.8) | — | — |
| Desinstalação preservando dados | IMPLEMENTADA E VALIDADA | CI deploy-windows (Windows Server 2022), run 40896603020: 34 aprovados, 0 reprovados, 1 não executado (2.8) | — | — |
| Instalação real pelo proprietário (falha de 28/10) | IMPLEMENTADA, MAS NÃO VALIDADA | Causa raiz comprovada e corrigida (docs/homologacao/Correcao_Inicializacao_Acesso_Web.md); validada no CI, ainda não confirmada na máquina do proprietário | Reinstalar com o instalador bc9cf28 e confirmar | P0 |
| Windows 10/11 de mesa limpos | BLOQUEADA | CI usa Windows Server 2022 (BLK-04) | Máquina/VM com Windows 10 e 11 | P0 |
| Instalação em diretório diferente | NÃO IMPLEMENTADA | DisableDirPage=yes (pasta fixa) | Decidir se é requisito | P3 |

## Arquitetura híbrida (Edge)

| Funcionalidade | Estado | Evidência | Pendência | Prioridade |
|---|---|---|---|---|
| Proposta arquitetural (PACS local + central) | IMPLEMENTADA E VALIDADA | docs/adr/ADR-0014.md | Aprovação (BLK-16) | P3 |
| Fila de envio, retentativas, queda/volta da internet, integridade, duplicidade, isolamento | PROTÓTIPO (não funcional) | vyonix/pacs/edge_sync.py, pacs_0008; test_edge_sync.py (central simulado) | Transporte mTLS, endpoint central, tarefa do Worker | P3 |
| Sincronização funcional com servidor central | BLOQUEADA | Desabilitada por decisão (BLK-16) | Decisão do proprietário, LGPD, certificados | P3 |
| Monitoramento da sincronização | PROTÓTIPO (não funcional) | edge_sync.stats | Tela e alertas | P3 |

## Segurança e conformidade

| Funcionalidade | Estado | Evidência | Pendência | Prioridade |
|---|---|---|---|---|
| Autenticação (senha forte, bloqueio, MFA, sessão) | IMPLEMENTADA E VALIDADA | test_core.py, test_api.py | — | — |
| Autorização por permissão no backend | IMPLEMENTADA E VALIDADA | test_api.py, test_access_multiinst.py | — | — |
| Isolamento entre organizações (RLS forçado em todas as tabelas) | IMPLEMENTADA E VALIDADA | test_architecture.py::test_every_tenant_table_is_protected_by_rls_in_migration | — | — |
| Criptografia em trânsito (HTTPS; DICOM sem TLS na rede local) | PARCIALMENTE IMPLEMENTADA | TLS no Core; DICOM em texto claro | DICOM TLS opcional | P2 |
| Criptografia em repouso (anexos AES-GCM, segredos DPAPI; banco e imagens sem cifra própria) | PARCIALMENTE IMPLEMENTADA | ris/prep.py, vyonix/secrets.py | BitLocker documentado ou cifra própria; backup cifrado | P2 |
| Auditoria encadeada e sem dados de pacientes nos eventos | IMPLEMENTADA E VALIDADA | test_core.py, test_clinical.py::test_events_carry_no_personal_data | — | — |
| Segurança de arquivos (ACL mínima nas pastas) | IMPLEMENTADA E VALIDADA | CI deploy-windows (Windows Server 2022), run 40896603020: 34 aprovados, 0 reprovados, 1 não executado (2.3) | — | — |
| Dependências vulneráveis (SBOM, pip-audit, npm audit) | IMPLEMENTADA E VALIDADA | SBOM 0 vulnerabilidades (deploy-windows); npm audit 0 | — | — |
| Chave de emissão de licenças comprometida (vyx-2026-01) | BLOQUEADA | BLK-01 | Nova chave e lista de documentos legítimos | P0 |
| LGPD (avaliação, base legal, retenção, direitos do titular) | BLOQUEADA | BLK-06; docs/regulatorio/ | Avaliação especializada | P1 |
| CFM (telemedicina/telerradiologia, assinatura, guarda) | BLOQUEADA | BLK-06, BLK-14 | Avaliação especializada | P1 |
| Teste de intrusão / revisão de segurança independente | NÃO IMPLEMENTADA | — | Contratar ou executar | P1 |
