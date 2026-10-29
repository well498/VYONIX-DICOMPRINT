"""Gera VYONIX_INVENTARIO_FUNCIONAL.md e a tabela de conclusão por módulo a partir do inventário abaixo
(auditoria geral de 29/10/2026, commit de referência d29d391). O DICOM Print está fora do escopo.

Estados: V = implementada e validada (código + testes automatizados aprovados no CI com os componentes reais do
caminho: PostgreSQL, Orthanc e/ou Windows, conforme o caso) · NV = implementada, mas não validada (sem teste, ou só
com dublê de algum componente, ou sem o ambiente-alvo) · P = parcialmente implementada · NI = não implementada ·
B = bloqueada (decisão, certificado, equipamento, avaliação externa) · ? = não verificada · PROT = protótipo.

Percentuais: pesos iguais por item dentro do módulo. Implementação: V e NV = 1, P = 0,5, PROT = 0,25, demais 0.
Validação: V = 1, demais 0. Nenhum item tem validação clínica nem teste prático com usuários reais.

Uso: python tools/auditoria_inventario.py  (reescreve VYONIX_INVENTARIO_FUNCIONAL.md na raiz)
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = {"V": "IMPLEMENTADA E VALIDADA", "NV": "IMPLEMENTADA, MAS NÃO VALIDADA", "P": "PARCIALMENTE IMPLEMENTADA",
         "NI": "NÃO IMPLEMENTADA", "B": "BLOQUEADA", "?": "NÃO VERIFICADA", "PROT": "PROTÓTIPO (não funcional)"}
IMPL = {"V": 1.0, "NV": 1.0, "P": 0.5, "PROT": 0.25}
CI_P = "CI platform (PostgreSQL 17.11 + Orthanc real), run 40896603151: 279 testes, 0 pulados, 0 falhas"
CI_W = "CI deploy-windows (Windows Server 2022), run 40896603020: 34 aprovados, 0 reprovados, 1 não executado"
CI_V = "CI viewer (Chromium + Orthanc real), run 40896603037"
CI_H = "CI homologação (instalador de homologação, roteiro 13/13), run 40896631587"

# (módulo, funcionalidade, estado, evidência, pendência, prioridade)
INV: list[tuple[str, str, str, str, str, str]] = [
    # ------------------------------------------------------------------ A. PACS
    ("PACS", "Recepção DICOM (C-STORE no motor) e indexação", "V", "vyonix/pacs/service.py (ingest, sync); test_pacs.py, test_pacs_orthanc.py; " + CI_W + " (2.9); " + CI_H, "Equipamento real (BLK-02)", "P1"),
    ("PACS", "Armazenamento (Orthanc 1.13 sem plugins; SHA-256 na entrada e na saída)", "V", "vyonix/pacs/orthanc.py, ADR-0012; test_pacs_orthanc.py", "Revisão jurídica da distribuição (BLK-07)", "P1"),
    ("PACS", "Organização de pacientes e estudos (índice por organização, RLS, registro clínico, conciliação)", "V", "pacs_0001..0005; test_pacs.py, test_clinical.py, test_pacs_cloud_isolation.py", "—", "—"),
    ("PACS", "Cadastro de dispositivos (nós DICOM: fabricante, modelo, modalidade, unidade, serviços, status)", "V", "vyonix/pacs/nodes.py, pacs_0006, tela Nós DICOM; test_pacs_nodes.py, test_e2e_web.py::test_6", "Teste com equipamento real (BLK-02)", "P1"),
    ("PACS", "Gerenciamento de AE Titles (nós por organização; rotas de AE no modo nuvem)", "V", "pacs_0002/0003; test_pacs_cloud_isolation.py, test_pacs_qr.py", "—", "—"),
    ("PACS", "C-ECHO (SCP no Q/R e no motor; SCU de teste a partir do cadastro)", "V", "dimse_qr.py, nodes.echo; test_pacs_nodes.py::Echo", "—", "—"),
    ("PACS", "C-STORE SCP (recepção) e SCU (envio por C-MOVE e encaminhamento)", "V", "test_pacs_orthanc.py, test_pacs_qr.py, test_pacs_forward.py", "—", "—"),
    ("PACS", "C-FIND (Study Root: estudo, série, imagem)", "V", "dimse_qr.py; test_pacs_qr.py", "Patient Root não implementado", "P2"),
    ("PACS", "C-MOVE (só para nós com permissão de receber; SHA-256 conferido)", "V", "test_pacs_qr.py", "—", "—"),
    ("PACS", "C-GET (só para o nó solicitante com permissão de receber)", "V", "test_pacs_qr.py", "—", "—"),
    ("PACS", "DICOMweb STOW-RS / QIDO-RS / WADO-RS (metadados e frames)", "V", "routes_pacs.py; test_pacs.py; " + CI_V, "Teste de carga", "P2"),
    ("PACS", "Roteamento automático (regras por origem/modalidade, envio manual, novas tentativas)", "NV", "vyonix/pacs/forward.py, pacs_0007; test_pacs_forward.py (Storage SCP real, motor DUBLÊ)", "Teste com Orthanc real e no serviço Worker do Windows", "P2"),
    ("PACS", "Storage Commitment (SCP)", "NV", "vyonix/pacs/commitment.py; test_pacs_commitment.py (pynetdicom real, motor DUBLÊ)", "Teste com modalidade real; Orthanc real", "P2"),
    ("PACS", "Controle de duplicidade (reenvio idempotente; conteúdo divergente recusado)", "V", "service.ingest; test_pacs.py, test_pacs_orthanc.py", "—", "—"),
    ("PACS", "Quarentena (nuvem: sem rota/licença; local: equipamento não autorizado retido)", "V", "cloud_sync, pacs.store_holds; test_pacs_cloud_isolation.py, test_pacs_orthanc.py::test_reception_only_from_registered_equipment", "Recusa já na associação (BLK-15)", "P2"),
    ("PACS", "Integração entre clínicas (compartilhar estudos entre instituições)", "NI", "Só compartilhamento temporário dentro da instituição (ris.exam.share)", "Desenho de consentimento, vínculo e auditoria entre organizações", "P3"),
    ("PACS", "Políticas de armazenamento: retenção (relatório e guarda obrigatória)", "V", "vyonix/pacs/retention.py; test_pacs_retention.py", "Exclusão por retenção exige política aprovada", "P3"),
    ("PACS", "Exclusão automática por retenção / camadas de armazenamento / compressão", "B", "Não implementado por decisão (sem política aprovada)", "Aprovação do proprietário e jurídico", "P3"),
    ("PACS", "Auditoria (entrada, recusa, abertura, Q/R, nós, envios)", "V", "vyonix/audit; test_core.py (cadeia), test_pacs*.py", "—", "—"),
    ("PACS", "Backup diário verificado e restauração", "V", "pacs/backup.py, backup_task.py; test_pacs_backup*.py; " + CI_W + " (2.7, 2.9)", "Backup sem criptografia própria", "P2"),
    ("PACS", "Verificação contínua de integridade", "V", "integrity_task.py; test_pacs_integrity_task.py", "—", "—"),
    ("PACS", "Histórico de conexões DICOM e recepção só de equipamentos cadastrados", "V", "pacs.dicom_events, pacs/reception; test_pacs_nodes.py, test_pacs_orthanc.py", "—", "—"),
    # ------------------------------------------------------------------ B. VIEWER
    ("Viewer", "Abertura de estudos no navegador (OHIF 3.13 na mesma origem)", "V", "viewer/, routes viewer; tests_viewer/test_viewer_e2e.py; " + CI_V, "Navegadores além do Chromium", "P2"),
    ("Viewer", "Navegação entre imagens e séries", "V", "test_viewer_e2e.py::test_multi_series_navigation", "—", "—"),
    ("Viewer", "Zoom", "V", "test_viewer_e2e.py::check_tools", "—", "—"),
    ("Viewer", "Pan", "?", "Ferramenta do OHIF; não exercitada nos testes", "Incluir no teste do Viewer", "P2"),
    ("Viewer", "Janela/nível, inverter, girar", "V", "test_viewer_e2e.py::check_tools", "—", "—"),
    ("Viewer", "Medição de distância", "V", "test_viewer_e2e.py::check_length (Pixel Spacing 0,5 mm)", "Sem validação clínica de medidas", "P2"),
    ("Viewer", "Anotações (seta, texto, ROI)", "?", "Ferramentas do OHIF; não exercitadas nos testes", "Testar e decidir quais liberar", "P2"),
    ("Viewer", "Reconstrução multiplanar (MPR)", "?", "Não configurada nem testada", "Configurar e testar com volume sintético", "P3"),
    ("Viewer", "Comparação lado a lado de exames", "NI", "Sem protocolo de exibição configurado", "Protocolo de exibição com anterior", "P2"),
    ("Viewer", "Exames anteriores (lista para comparação)", "V", "ris/timeline.priors; test_ris_workflow.py::test_priors_of_same_patient", "Abrir anterior e atual juntos no Viewer", "P2"),
    ("Viewer", "Ferramentas por modalidade", "NI", "—", "Definir conjuntos por modalidade", "P3"),
    ("Viewer", "Desempenho (estudos grandes)", "?", "Sem teste de carga", "Teste com estudo de TC/RM grande sintético", "P2"),
    ("Viewer", "Integração com o PACS (DICOMweb do Core, cookie da sessão)", "V", "test_viewer_serving.py, test_viewer_e2e.py", "—", "—"),
    ("Viewer", "Controle de acesso (sessão, permissão pacs.studies.read, auditoria de abertura)", "V", "test_viewer_serving.py, test_pacs.py", "—", "—"),
    # ------------------------------------------------------------------ C. RIS
    ("RIS", "Cadastro de pacientes (identificadores, mescla e desfazer)", "V", "vyonix/clinical; test_clinical.py; " + CI_H, "—", "—"),
    ("RIS", "Cadastro de exames/procedimentos", "V", "clinical.save_procedure; test_ris.py", "—", "—"),
    ("RIS", "Solicitações (pedidos)", "V", "clinical.create_order; test_ris.py, test_clinical.py", "—", "—"),
    ("RIS", "Agendamento (conflito de sala/estação, duração)", "V", "ris/service.schedule; test_ris.py", "—", "—"),
    ("RIS", "Agenda por modalidade e sala", "V", "ris_0004 salas; test_ris.py; tela Agenda", "—", "—"),
    ("RIS", "Modality Worklist (C-FIND MWL)", "V", "dimse_qr._worklist; test_ris.py", "Modalidade real (BLK-02)", "P1"),
    ("RIS", "Situação do atendimento (chegada, em realização, MPPS, recebido)", "V", "ris_0003/0005; test_ris.py, test_ris_technician.py", "—", "—"),
    ("RIS", "Histórico do paciente", "P", "Exames anteriores e linha do tempo por exame (test_ris_workflow.py); sem tela única de histórico", "Tela de histórico do paciente", "P2"),
    ("RIS", "Cadastro de convênios", "NI", "Nenhum modelo, rota ou tela", "Definir escopo (faturamento/autorização)", "P2"),
    ("RIS", "Integração com o PACS (UID do agendamento, recebido, conciliação)", "V", "ris.register_consumers; test_ris.py, test_ris_prep.py", "—", "—"),
    ("RIS", "Integração com modalidades (MWL/MPPS)", "NV", "Só com SCU simulado (pynetdicom)", "Teste com equipamento real (BLK-02)", "P1"),
    ("RIS", "Integração HL7 v2", "P", "Saída ORU do laudo (report/interop.py; test_report_interop.py); sem entrada ADT/ORM (MLLP)", "Receptor HL7 ADT/ORM", "P2"),
    ("RIS", "Relatórios operacionais (Central de exames: etapas, atrasos, tempos)", "V", "ris/tracking.py; test_ris_exam_center.py", "Exportação dos relatórios", "P3"),
    ("RIS", "Central de Exames e preparação técnica (checklist, anexos, comentários, encaminhamento)", "V", "ris/prep.py; test_ris_prep.py, test_e2e_prep.py; " + CI_H, "—", "—"),
    ("RIS", "Fluxo do exame configurável e linha do tempo", "V", "ris/workflow, ris/timeline.py; test_ris_workflow.py", "—", "—"),
    # ------------------------------------------------------------------ D. TELELAUDO
    ("Telelaudo", "Recebimento de exames na fila", "V", "report/queue.py; test_report_queue.py; " + CI_H, "—", "—"),
    ("Telelaudo", "Fila de trabalho com escopo por vínculo/unidade", "V", "test_report_queue.py::test_scope_by_unit", "—", "—"),
    ("Telelaudo", "Distribuição entre médicos (manual, fixo, equilibrada) e reserva", "V", "report/distribution.py; test_ris_prep.py", "—", "—"),
    ("Telelaudo", "Atribuição manual", "V", "test_report_queue.py", "—", "—"),
    ("Telelaudo", "Atribuição automática", "V", "test_ris_prep.py (distribuição fixa e equilibrada)", "Regras por modalidade/unidade", "P2"),
    ("Telelaudo", "Prioridades e urgências", "V", "test_report_queue.py, test_ris_prep.py", "—", "—"),
    ("Telelaudo", "Acompanhamento de prazos (SLA)", "V", "queue.SLA_HOURS; test_report_queue.py", "Alertas de atraso (notificação)", "P2"),
    ("Telelaudo", "Elaboração de laudos", "V", "report/service.py; test_report.py; " + CI_H + " (passo 13)", "—", "—"),
    ("Telelaudo", "Revisão (segunda leitura / dupla assinatura)", "NI", "—", "Definir fluxo de revisão", "P2"),
    ("Telelaudo", "Retificação (adendos versionados)", "V", "service.addendum; test_report.py", "—", "—"),
    ("Telelaudo", "Finalização e liberação (confirmação por senha; versões imutáveis com SHA-256)", "V", "test_report.py, test_report_signature_lifecycle.py", "Não é assinatura digital ICP-Brasil (BLK-14)", "P1"),
    ("Telelaudo", "Entrega ao paciente/solicitante", "P", "PDF, FHIR, HL7 ORU e DICOM PDF (test_report_interop.py); sem portal nem envio", "Portal do paciente / envio", "P2"),
    ("Telelaudo", "Histórico e auditoria do laudo", "V", "report_versions, audit; test_report.py", "—", "—"),
    ("Telelaudo", "Rede de médicos entre instituições (telelaudo multiorganização)", "NI", "Médicos são cadastrados por instituição", "Desenho de vínculo entre organizações", "P3"),
    # ------------------------------------------------------------------ E. EDITOR
    ("Editor de laudos", "Editor de texto", "P", "Campo de texto simples com seções do modelo (web/src/pages/reports.tsx)", "Editor com formatação", "P1"),
    ("Editor de laudos", "Formatação avançada (negrito, listas, tabelas)", "NI", "—", "Editor rico com saída segura no PDF", "P2"),
    ("Editor de laudos", "Importação de modelos Word (DOCX)", "V", "report/docx_import.py; test_report_docx.py", "—", "—"),
    ("Editor de laudos", "Templates versionados com seleção automática", "V", "report/templates.py; test_report_templates.py", "—", "—"),
    ("Editor de laudos", "Presets / frases rápidas / textos básicos", "NI", "—", "Biblioteca de frases por médico e modalidade", "P2"),
    ("Editor de laudos", "Cabeçalhos e rodapés (identidade visual por organização e unidade)", "V", "report/branding.py; test_report_branding.py", "—", "—"),
    ("Editor de laudos", "Geração de PDF", "V", "report/pdf.py; test_report.py; " + CI_H, "—", "—"),
    ("Editor de laudos", "Assinatura manuscrita digitalizada (elemento visual autorizado)", "V", "report/signature.py; test_report_signature_lifecycle.py", "—", "—"),
    ("Editor de laudos", "Assinatura digital ICP-Brasil / PAdES", "B", "report/pades.py recusa (BLK-14)", "Decisão de padrão e certificados", "P1"),
    ("Editor de laudos", "Controle de versões e histórico", "V", "report_versions; test_report.py", "—", "—"),
    ("Editor de laudos", "Proteção de documentos finalizados", "V", "versões imutáveis + verificação SHA-256; test_report.py", "—", "—"),
    # ------------------------------------------------------------------ F. USUÁRIOS
    ("Usuários e permissões", "Cadastro administrativo de usuários", "V", "auth/service.py; test_core.py, test_e2e_web.py", "—", "—"),
    ("Usuários e permissões", "Perfis (papéis padrão, modelos opcionais, papéis personalizados)", "V", "manifest.DEFAULT_ROLES/ROLE_TEMPLATES, save_role; test_access_multiinst.py", "—", "—"),
    ("Usuários e permissões", "Permissões por módulo e por operação (backend valida)", "V", "needs(...); test_api.py::test_role_permissions", "—", "—"),
    ("Usuários e permissões", "Alteração administrativa e auditoria de permissões", "V", "test_access_multiinst.py, audit", "—", "—"),
    ("Usuários e permissões", "Isolamento entre instituições (RLS forçado)", "V", "test_core.py (RLS), test_pacs_cloud_isolation.py, test_architecture.py", "—", "—"),
    ("Usuários e permissões", "Cadastros independentes por instituição e login só com usuário e senha", "V", "auth/directory.py, core_0002; test_access_multiinst.py, test_e2e_cloud.py", "—", "—"),
    ("Usuários e permissões", "Revogação de acesso (desativar usuário, bloqueio, sessão expira)", "V", "auth.update_user(active); test_core.py", "—", "—"),
    ("Usuários e permissões", "Proteção contra acesso indevido por API (sessão, CSRF, cabeçalhos)", "V", "test_api.py", "Teste de intrusão externo", "P2"),
    ("Usuários e permissões", "MFA (TOTP) e política de senha", "V", "test_core.py::test_mfa_*", "—", "—"),
    # ------------------------------------------------------------------ G. CADASTRO MÉDICO
    ("Cadastro médico", "Cadastro administrativo (CRM/UF, especialidades, RQE, rodapé)", "V", "report/physicians.py; test_report.py, test_e2e_roteiro.py", "Validação de CRM em base oficial", "P3"),
    ("Cadastro médico", "Vínculos institucionais por unidade e vigência", "V", "physician_links; test_report_queue.py", "—", "—"),
    ("Cadastro médico", "Upload, recorte e tratamento da assinatura manuscrita", "V", "test_report_signature_lifecycle.py", "—", "—"),
    ("Cadastro médico", "Proteção da assinatura (cifrada, autorização do médico, auditoria de uso)", "V", "test_report_signature_lifecycle.py", "—", "—"),
    ("Cadastro médico", "Médico não altera o próprio cadastro administrativo", "V", "report.physicians.manage fora do papel 'medico'; test_api.py", "—", "—"),
    ("Cadastro médico", "Permissões de elaboração/liberação de laudos", "V", "report.write/report.sign; test_report*.py", "—", "—"),
    ("Cadastro médico", "Templates pessoais do médico", "NI", "Modelos são da instituição (report.templates.manage)", "Modelos pessoais com permissão", "P2"),
    # ------------------------------------------------------------------ H. PRODUÇÃO
    ("Produção médica", "Minha Produção (dia, mês, período, unidade, modalidade, pendências, tempo médio)", "V", "report/production.py; test_report_production.py; test_e2e_roteiro.py (r10)", "—", "—"),
    ("Produção médica", "Relatório PDF e exportação CSV (Excel)", "V", "test_report_production.py", "Arquivo .xlsx nativo", "P3"),
    ("Produção médica", "Produção financeira", "P", "Tabela de valor por modalidade (report/production)", "Valores por procedimento/convênio, fechamento mensal", "P2"),
    ("Produção médica", "Permissão independente para valores financeiros", "V", "report.production.financial; test_report_production.py", "—", "—"),
    ("Produção médica", "Isolamento entre médicos e regra de contagem documentada", "V", "test_report_production.py; docstring de production.py", "—", "—"),
    # ------------------------------------------------------------------ I. ADMINISTRAÇÃO
    ("Administração", "Gestão de instituições (operadora VYONIX, modo nuvem)", "V", "tenancy/platform_admin.py; test_platform_admin.py, test_e2e_cloud.py", "—", "—"),
    ("Administração", "Gestão de usuários, unidades, salas (modalidades) e nós DICOM", "V", "telas Usuários, Unidades, Agenda→Salas, Nós DICOM; test_e2e_web.py", "—", "—"),
    ("Administração", "Configurações com histórico e motivo", "V", "settings/service.py; test_core.py::test_settings_*", "—", "—"),
    ("Administração", "Auditoria encadeada (tela e verificação)", "V", "audit; test_core.py::test_chain_and_tamper_detection", "—", "—"),
    ("Administração", "Monitoramento (serviços, motor, Q/R, backup, integridade, licença, disco)", "V", "monitoring.py; test_monitoring.py", "—", "—"),
    ("Administração", "Alertas (notificação ativa por e-mail/mensagem)", "NI", "Só painel; módulo NOTIFY planejado", "Notificações", "P2"),
    ("Administração", "Logs técnicos (arquivos dos serviços, relatórios do DEPLOY)", "NV", "winservice.py (RotatingFileHandler); sem tela", "Tela de logs para suporte", "P3"),
    ("Administração", "Menus por perfil e menu lateral recolhível", "V", "web/src/app.tsx; test_e2e_web.py", "—", "—"),
    ("Administração", "Usabilidade avaliada com usuários", "?", "Sem teste com usuários reais", "Avaliação prática do proprietário (em curso)", "P1"),
    # ------------------------------------------------------------------ J. INFRAESTRUTURA
    ("Infraestrutura e deploy", "Instalador Windows com dependências (PostgreSQL 17, Orthanc, Viewer)", "V", "installer/VyonixPlatform.iss, deploy-windows.yml; " + CI_W, "Assinatura de código (BLK-08)", "P1"),
    ("Infraestrutura e deploy", "Serviços do Windows com início automático, sem login, dependências e recuperação", "V", "steps/services.py; " + CI_W + " (2.3, 2.5)", "—", "—"),
    ("Infraestrutura e deploy", "Recuperação de falhas (processo do Core encerrado; banco derrubado e recuperado)", "V", "winservice.db_watchdog; test_db_watchdog.py; " + CI_W + " (2.5, 2.10)", "—", "—"),
    ("Infraestrutura e deploy", "Inicialização após reiniciar o computador", "?", "Coberto indiretamente (início automático + dependências); o runner do CI não reinicia", "Teste real de reinicialização (BLK-04)", "P0"),
    ("Infraestrutura e deploy", "Acesso por localhost e pelo IP da rede (HTTPS; http:// redireciona)", "V", "https_server.py, firewall Público/LocalSubnet; test_https_server.py; " + CI_W + " (2.10)", "Confirmação na instalação real do proprietário", "P0"),
    ("Infraestrutura e deploy", "Frontend e backend disponíveis após instalar", "V", CI_W + " (2.5, 2.10); " + CI_H, "—", "—"),
    ("Infraestrutura e deploy", "Diagnóstico de inicialização (sem administrador) e reparo", "V", "vyonix_deploy/startup.py, diagnose.py; test_startup.py; " + CI_W + " (2.7, 2.10)", "—", "—"),
    ("Infraestrutura e deploy", "Porta ocupada (detectada e reparada)", "V", CI_W + " (2.1, 2.7)", "—", "—"),
    ("Infraestrutura e deploy", "Atualização preservando dados (backup antes da migração)", "V", "steps/update.py; " + CI_W + " (2.8)", "—", "—"),
    ("Infraestrutura e deploy", "Desinstalação preservando dados", "V", CI_W + " (2.8)", "—", "—"),
    ("Infraestrutura e deploy", "Instalação real pelo proprietário (falha de 28/10)", "NV", "Causa raiz comprovada e corrigida (docs/homologacao/Correcao_Inicializacao_Acesso_Web.md); validada no CI, ainda não confirmada na máquina do proprietário", "Reinstalar com o instalador bc9cf28 e confirmar", "P0"),
    ("Infraestrutura e deploy", "Windows 10/11 de mesa limpos", "B", "CI usa Windows Server 2022 (BLK-04)", "Máquina/VM com Windows 10 e 11", "P0"),
    ("Infraestrutura e deploy", "Instalação em diretório diferente", "NI", "DisableDirPage=yes (pasta fixa)", "Decidir se é requisito", "P3"),
    # ------------------------------------------------------------------ K. EDGE
    ("Arquitetura híbrida (Edge)", "Proposta arquitetural (PACS local + central)", "V", "docs/adr/ADR-0014.md", "Aprovação (BLK-16)", "P3"),
    ("Arquitetura híbrida (Edge)", "Fila de envio, retentativas, queda/volta da internet, integridade, duplicidade, isolamento", "PROT", "vyonix/pacs/edge_sync.py, pacs_0008; test_edge_sync.py (central simulado)", "Transporte mTLS, endpoint central, tarefa do Worker", "P3"),
    ("Arquitetura híbrida (Edge)", "Sincronização funcional com servidor central", "B", "Desabilitada por decisão (BLK-16)", "Decisão do proprietário, LGPD, certificados", "P3"),
    ("Arquitetura híbrida (Edge)", "Monitoramento da sincronização", "PROT", "edge_sync.stats", "Tela e alertas", "P3"),
    # ------------------------------------------------------------------ L. SEGURANÇA
    ("Segurança e conformidade", "Autenticação (senha forte, bloqueio, MFA, sessão)", "V", "test_core.py, test_api.py", "—", "—"),
    ("Segurança e conformidade", "Autorização por permissão no backend", "V", "test_api.py, test_access_multiinst.py", "—", "—"),
    ("Segurança e conformidade", "Isolamento entre organizações (RLS forçado em todas as tabelas)", "V", "test_architecture.py::test_every_tenant_table_is_protected_by_rls_in_migration", "—", "—"),
    ("Segurança e conformidade", "Criptografia em trânsito (HTTPS; DICOM sem TLS na rede local)", "P", "TLS no Core; DICOM em texto claro", "DICOM TLS opcional", "P2"),
    ("Segurança e conformidade", "Criptografia em repouso (anexos AES-GCM, segredos DPAPI; banco e imagens sem cifra própria)", "P", "ris/prep.py, vyonix/secrets.py", "BitLocker documentado ou cifra própria; backup cifrado", "P2"),
    ("Segurança e conformidade", "Auditoria encadeada e sem dados de pacientes nos eventos", "V", "test_core.py, test_clinical.py::test_events_carry_no_personal_data", "—", "—"),
    ("Segurança e conformidade", "Segurança de arquivos (ACL mínima nas pastas)", "V", CI_W + " (2.3)", "—", "—"),
    ("Segurança e conformidade", "Dependências vulneráveis (SBOM, pip-audit, npm audit)", "V", "SBOM 0 vulnerabilidades (deploy-windows); npm audit 0", "—", "—"),
    ("Segurança e conformidade", "Chave de emissão de licenças comprometida (vyx-2026-01)", "B", "BLK-01", "Nova chave e lista de documentos legítimos", "P0"),
    ("Segurança e conformidade", "LGPD (avaliação, base legal, retenção, direitos do titular)", "B", "BLK-06; docs/regulatorio/", "Avaliação especializada", "P1"),
    ("Segurança e conformidade", "CFM (telemedicina/telerradiologia, assinatura, guarda)", "B", "BLK-06, BLK-14", "Avaliação especializada", "P1"),
    ("Segurança e conformidade", "Teste de intrusão / revisão de segurança independente", "NI", "—", "Contratar ou executar", "P1"),
]


def render() -> str:
    mods: dict[str, list] = {}
    for it in INV:
        mods.setdefault(it[0], []).append(it)
    out = ["# VYONIX — Inventário funcional (auditoria geral de 29/10/2026)", "",
           "**Escopo:** VYONIX Medical Platform. **O VYONIX DICOM Print está excluído** deste inventário e dos cálculos.",
           "Referência: ramo `develop`, commit `d29d391`. Gerado por `tools/auditoria_inventario.py` (critérios no "
           "cabeçalho do script). “Validada” = testes automatizados aprovados no CI com os componentes reais do caminho; "
           "**nenhum item tem validação clínica nem teste prático concluído com usuários reais.**", "",
           "Legenda: " + " · ".join(f"**{v}**" for v in STATE.values()), ""]
    out += ["## Conclusão estimada por módulo", "",
            "| Módulo | Itens | Validadas | Não validadas | Parciais | Não implementadas | Bloqueadas | Não verificadas | Protótipo | Implementação | Validação |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    tot = {"n": 0, "impl": 0.0, "val": 0}
    for m, items in mods.items():
        c = {k: sum(1 for x in items if x[2] == k) for k in STATE}
        impl = sum(IMPL.get(x[2], 0) for x in items)
        n = len(items)
        tot["n"] += n
        tot["impl"] += impl
        tot["val"] += c["V"]
        out.append(f"| {m} | {n} | {c['V']} | {c['NV']} | {c['P']} | {c['NI']} | {c['B']} | {c['?']} | {c['PROT']} | "
                   f"{impl / n * 100:.0f}% | {c['V'] / n * 100:.0f}% |")
    out.append(f"| **Total (pesos iguais por item)** | {tot['n']} |  |  |  |  |  |  |  | "
               f"**{tot['impl'] / tot['n'] * 100:.0f}%** | **{tot['val'] / tot['n'] * 100:.0f}%** |")
    out += ["", "Os percentuais medem a cobertura **deste inventário** (requisitos levantados dos prompts do proprietário "
            "e das referências), não o esforço restante nem prontidão clínica. Itens de peso muito diferente (ex.: "
            "assinatura ICP-Brasil × zoom) contam igual; por isso servem para comparar módulos, não para prazo.", ""]
    for m, items in mods.items():
        out += [f"## {m}", "", "| Funcionalidade | Estado | Evidência | Pendência | Prioridade |", "|---|---|---|---|---|"]
        for _m, f, st, ev, pend, pr in items:
            out.append(f"| {f} | {STATE[st]} | {ev} | {pend} | {pr} |")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    (ROOT / "VYONIX_INVENTARIO_FUNCIONAL.md").write_text(render(), encoding="utf-8")
    print("VYONIX_INVENTARIO_FUNCIONAL.md gerado")
