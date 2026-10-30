# UX — Fase A: diagnóstico da interface web atual (29/10/2026)

Somente leitura; web compilada numa cópia fora do repositório e examinada com Playwright e API simulada (1366 e
375 px). **[F]** fato no código/teste · **[O]** opinião. Perfis = papéis reais do backend (`vyonix/modules/manifest.py`
padrões: administrador, supervisor, medico, tecnico, recepcionista; modelos: coordenador_cdi, gestor_telelaudos,
financeiro, suporte_tecnico; operadora: admin_vyonix).

## Menu atual por perfil (`web/src/app.tsx:25-46,83-84`)
| Perfil | Itens |
|---|---|
| Administrador / Supervisor (16) | Início, Pacientes, Agenda, Painel do técnico, Central de exames, Laudos, Minha produção, Conciliação, Imagens, Nós DICOM, Usuários e papéis, Unidades, Configurações, Licença e módulos, Contratar e demonstrar, Auditoria |
| Médico (9) | Início, Pacientes, Agenda, Central de exames, Laudos, Minha produção, Imagens, **Licença e módulos, Contratar e demonstrar** |
| Técnico (9) | Início, Pacientes, Agenda, Painel do técnico, Central de exames, Conciliação, Imagens, **Licença e módulos, Contratar e demonstrar** |
| Recepcionista (4) | Início, Pacientes, Agenda, Central de exames |
| Coordenador do CDI (9) | Início, Pacientes, Agenda, Painel do técnico, Central de exames, Laudos, Conciliação, Imagens, Usuários e papéis (leitura) |
| Gestor de Telelaudos (3) | Início, Laudos, Imagens |
| Financeiro (5) | Início, **Agenda, Central de exames** (nomes de pacientes), Licença e módulos, Contratar e demonstrar |
| Suporte técnico (7) | Início, Nós DICOM, Unidades, Configurações, Licença e módulos, Contratar e demonstrar, Auditoria |
| Admin geral VYONIX (8) | Início, Administração VYONIX, Usuários e papéis, Unidades, Configurações, Licença e módulos, **Contratar e demonstrar**, Auditoria |
| Médico solicitante, enfermagem, faturamento, paciente | **Não existem** como papel ou modelo ("solicitante" é texto livre no pedido, nunca preenchido pela web) |

## Jornada (cliques estimados pelo código): ~35–45 cliques, ≥ 5 telas e 4 perfis por exame
| Etapa | Cliques/campos | Gargalos |
|---|---|---|
| Agendamento | ~9 cliques, 9–11 campos (+6 paciente novo) | Pedido criado vazio (sem procedimento, solicitante, prioridade); procedimentos sem tela; modalidade/AE digitados; sem grade de disponibilidade |
| Chegada | 2 | Sem ficha de atendimento (backend sem rota) |
| Preparação/aquisição | 2–3 | Regras diferentes entre Agenda e Painel |
| Recepção PACS | 0–2 | Técnico vê recusas mas só pacs.admin resolve |
| Conferência | ~7 por estudo, sem lote | "Encaminhar" no 6º item; uma chamada por caixa do checklist; sem pedido → Conciliação por número de acesso |
| Distribuição | ~5 por estudo, sem lote | Formulário espremido na coluna "Fila" |
| Visualização | 2 | "Abrir imagens ▾" consistente (bom) |
| Laudo | 4 + texto; retomar +3 | Editor no topo sem rolagem; filtro padrão "Sem laudo"; médico não vê o material do técnico |
| Assinatura | 2 | Avisos repetidos |
| Entrega | 2 | Sem entrega ao paciente/solicitante |

## Problemas priorizados (UX-A-001…025)
| ID | Cl. | Evidência | Proposta |
|---|---|---|---|
| UX-A-001 | D | Ficha do estudo só pelo Painel do técnico (technician.tsx:74,113); editor de laudo sem comentários/anexos/"Devolver" (reports.tsx:270-383), embora a API permita (routes_ris.py:145,377) | Painel de contexto do estudo dentro do laudo |
| UX-A-002 | D | Pedido criado só com `patient_id` (patients.tsx:109); `POST /procedures` sem tela | Formulário de pedido (procedimento, solicitante, prioridade) junto do agendamento |
| UX-A-003 | D | Configurações mostram listas como texto ("[object Object]") e opções fixas digitadas (settings.tsx:68-92) | Controles próprios (lista, seleção, escolher médico) |
| UX-A-004 | D | core.license.read em médico/técnico/financeiro/suporte/admin_vyonix → "Licença" e "Contratar" (beco sem saída) | Mostrar só com core.license.manage (backend inalterado sem decisão) |
| UX-A-005 | D | Painéis laterais sem foco/Esc/bloqueio de foco (prep.tsx:75; stations.tsx:315) — confirmado no Playwright; menu móvel fechado alcançável por Tab | Componente de diálogo único |
| UX-A-006 | D | Editor de laudo acima dos filtros sem rolagem (reports.tsx:118); mensagens no topo | Tela de laudo própria com a lista ao lado |
| UX-A-007 | P | Encaminhar ~7 cliques/estudo | "Conferir e encaminhar" no topo; marcar todos; lote |
| UX-A-008 | P | Filtro padrão "Sem laudo" esconde rascunhos e revisões (reports.tsx:44) | "Minha fila" padrão do médico |
| UX-A-009 | D | Agenda × Painel: "Check-in" × "Chegou", regras de conclusão diferentes, MPPS em inglês | Uma lista de exames com ações padronizadas |
| UX-A-010 | D | Laudos empilha 5 painéis administrativos acima da fila | "Configurações de laudo" e "Meu perfil" |
| UX-A-011 | R | Painel do técnico: 14 cartões, contagens diferentes | Abas Fila / Agenda do dia / Recepção |
| UX-A-012 | D | Menu × permissões incoerentes (Painel, Unidades, "Minha produção") | Matriz única tela × permissão com testes |
| UX-A-013 | R | Financeiro vê nomes de pacientes (Agenda/Central) | Revisar modelo com o Agente 04 (LGPD) |
| UX-A-014 | D | Jargão técnico ("Nós DICOM", "AE Title", "C-STORE", "MWL", "MPPS", "Installation ID", "SHA-256"…), JSON cru | Linguagem clínica no nível principal; técnico como detalhe |
| UX-A-015 | D | "Accession" × "Acesso"; situação em inglês cru (reconcile.tsx:75) | Glossário único |
| UX-A-016 | D | Conciliação só por número de acesso (N+1 consultas); mescla com ID digitado | Busca assistida (nome, nascimento, ID DICOM) |
| UX-A-017 | D | `window.prompt` mostra a senha provisória (users.tsx:49) | Diálogo com campo de senha |
| UX-A-018 | D | Contraste abaixo de WCAG AA (foco 1,84:1; bordas 1,73:1; `.tag` 4,28:1) | Ajustar tema |
| UX-A-019 | R | Filtros só com placeholder; Agenda a 375 px com ações fora da tela | Rótulos visíveis; cartões no celular |
| UX-A-020 | P | Início sem próxima tarefa | "Minhas tarefas" por perfil |
| UX-A-021 | P | Configurações: ~11 formulários numa página | Agrupar por tema |
| UX-A-022 | D | Menu recolhido com abreviações ambíguas ("I", "C") | Ícones e dica |
| UX-A-023 | R | 2 etapas sem QR; sem papel personalizado na web; médico padrão gerencia modelos da instituição | QR local; editor de papéis; revisar com 04 |
| UX-A-024 | D | Ações destrutivas sem confirmação (regra, frase, assinatura, 2FA, usuário, módulo) | Padrão único de confirmação |
| UX-A-025 | P | Aviso "não é assinatura ICP-Brasil" 5 vezes | Aviso legal fixo num lugar só |

Já registrados no Registro de Aperfeiçoamento e usados na Fase C pelos IDs: A05-009 (autosave), A04-001 (papel por
unidade), A05-006 (pedido preso), A05-012 (distribuição automática).

## Restrições a preservar
APIs `/api/v1/*` e formatos; autorização no backend; login sem escolha de instituição; isolamento institucional;
Administração VYONIX sem dados clínicos; papéis padrão não editáveis e "ninguém concede o que não possui"; decisões do
Viewer/Weasis/Oviyam; avisos legais (consolidados, não removidos); trilha de auditoria e motivos obrigatórios;
~405 localizadores dos testes e2e por rótulo (renomear exige atualizar os testes); CSP sem CDN; DICOM Print intocado.

## Não verificado
Uso com dados e volume reais (cliques estimados, sem tempo medido); interior do OHIF/Weasis; leitores de tela reais;
navegadores além do Chromium e larguras 768–1280 px. `VYONIX_INVENTARIO_FUNCIONAL.md` está desatualizado (histórico,
editor rico e modelos pessoais já existem) — atualizar.
Capturas e scripts: scratchpad da sessão (`uxA/`), fora do repositório.
