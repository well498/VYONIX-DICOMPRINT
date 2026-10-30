# Reformulação integrada — Técnico, Médico Radiologista e Paciente (Prompt Mestre de 29/10/2026 23:05)

Incorporado ao projeto UX (`Projeto_Reformulacao_UX.md`) sem substituir nada: mesmas regras (incremental, backend
autoriza, contas independentes por instituição, DICOM Print intocado, P0 primeiro). Prioridade: P1 para fluxos
essenciais e permissões (conferência, prioridade, trocar médico, fila com prazo, publicação condicionada); P2 para
visualizador local preferencial; P2/DEC para o Portal do Paciente (BLK-06: protótipo sim, uso real não).

## 1. Situação atual × pedido (auditoria das três interfaces — base: `Fase_A_Diagnostico.md`)
| Perfil | Hoje | Pedido | Lacuna principal |
|---|---|---|---|
| Técnico | 9 itens de menu (inclui Licença, Contratar, Pacientes, Central, Conciliação, Imagens); Painel do técnico com 14 blocos; ficha do estudo com 11 ações; prioridade e troca de médico como **solicitação** (`ris/prep.py` REQUESTS) e prioridade direta com `ris.exam.priority` | 5 itens (Meu painel, Agenda de exames, Exames recebidos, Conferência técnica, Pendências); lista paginada 10/20/50/100; ficha lateral com identificação só leitura, informações técnicas editáveis, checklist; Prioridade; **Trocar médico** | Campos técnicos estruturados (protocolo, contraste, intercorrências, qualidade) não existem como campos — hoje são comentários/checklist; paginação; menu |
| Médico | 9 itens (inclui Pacientes, Agenda, Central, Licença, Contratar); fila "Laudos" com filtro padrão "Sem laudo"; editor abaixo dos botões de configuração; liberação por senha | 6 itens (Meu painel, Fila de exames, Meus laudos, Histórico e pesquisa, Minha produção, Preferências); fila com prazo e filtros (atribuídos, disponíveis, urgentes, pendentes, em elaboração, aguardando revisão); três modos Fila/Imagens/Laudo; viewer e editor em monitores diferentes; salvamento automático; Rascunho / Revisar / Assinar e finalizar | Prazo restante, autosave, separação dos modos, preferência de visualizador local |
| Paciente | Não existe | Portal simples, celular primeiro, Início/Meus exames/Agendamentos/Minha conta, resultado em 3 abas, Viewer simplificado, compartilhamento temporário | Tudo (BLK-06) |

## 2. Nova estrutura de menus (proposta; só mostra o que a pessoa pode usar — o backend continua decidindo)
| Perfil | Menu | Telas atuais reaproveitadas |
|---|---|---|
| Técnico | Meu painel · Agenda de exames · Exames recebidos · Conferência técnica · Pendências | Painel do técnico (dividido), Agenda, ficha do estudo, pendências de qualidade/conciliação |
| Radiologista | Meu painel · Fila de exames · Meus laudos · Histórico e pesquisa · Minha produção · Preferências | Laudos (fila e editor), histórico do paciente, Minha produção, Minha assinatura/Modelos/Frases (→ Preferências) |
| Paciente | Início · Meus exames · Agendamentos · Minha conta (celular: navegação inferior) | — (novo) |
Funcionalidades que saem do menu desses perfis **continuam existindo** para quem tem permissão (ex.: Licença e
Contratar ficam com quem tem `core.license.manage`); nenhuma permissão muda sem decisão.

## 3. Matriz de permissões (ação → permissão exigida no backend)
| Ação | Permissão (existente) | Observação |
|---|---|---|
| Ver exames recebidos / agenda | `ris.schedule.read`, `pacs.studies.read` | escopo por instituição (e por vínculo quando configurado) |
| Conferência técnica (checklist, informações técnicas, encaminhar) | `ris.exam.prepare` | encaminhar respeita checklist obrigatório; pendência impeditiva bloqueia (INT-01) |
| Abrir imagens | `pacs.studies.read` + escopo do estudo | auditoria `pacs.study.open` |
| Prioridade — alterar | `ris.exam.priority` | registra anterior, nova, justificativa, usuário, data (já auditado em `prep.set_priority`) |
| Prioridade — solicitar | `ris.exam.prepare` (pedido `priority_request`) | aprovação por quem tem `ris.exam.priority` |
| **Trocar médico** — efetuar | `report.assign` | elegíveis: instituição, unidade/vínculo, modalidade (habilitação: matriz #7, DEC); nunca laudo assinado ou bloqueado |
| Trocar médico — solicitar | `ris.exam.prepare` (pedido `doctor_change`) | aprovação por `report.assign` |
| Elaborar / continuar laudo | `report.write` + escopo; trava de autoria (A05-003, DEC) | |
| Revisar | `report.review` | |
| Assinar e finalizar | `report.sign` (+ senha; ICP-Brasil = BLK-14) | publicação só com laudo assinado e sem pendência (INT-01) |
| Minha produção | `report.production.own` (valores: `report.production.financial`) | nunca dados de outros médicos |
| Preferências (modelos/frases próprios, visualizador) | `report.templates.own`, `report.phrases.own` | não altera cadastro institucional nem assinatura vinculada |
| Paciente — ver os próprios exames/laudos/imagens | **novo** papel `paciente` (autorização por paciente e exame) | DEC/BLK-06: identificação confiável, representantes, sessão, auditoria |
| Paciente — compartilhar | **novo** (link temporário com validade, revogação e auditoria) | DEC/BLK-06 |

### Rótulos de prioridade
Backend: `routine` / `urgent` / `stat` (prazos padrão 48 h / 4 h / 1 h). Proposta de rótulos na tela, sem migração de
dados: **Rotina** = `routine`, **Prioritário** = `urgent`, **Urgente** = `stat`. → decisão do proprietário (D-01).

## 4. Visualizador preferencial do médico (Windows/macOS) — desenho técnico (P2)
* Preferência por usuário: Automático (local primeiro) · Weasis · Outro compatível · Viewer Web VYONIX.
* **Weasis primeiro** (já existe: `pacs/external.py`, manifesto de uso único, token temporário ligado a estudo/usuário/
  instituição, WADO por cabeçalho; desligado por padrão; validação isolada aprovada). Pendências de segurança antes
  de habilitar: A03-008 (revogar no logout, reavaliar escopo, trava do manifesto).
* **Detecção:** o navegador não sabe o que está instalado e abrir `weasis://` não prova sucesso. Mecanismo proposto:
  o manifesto de uso único marca "baixado" quando o Weasis o busca (`/pacs/external/weasis/manifest/{code}`); a tela
  espera essa confirmação por alguns segundos e, sem ela, informa discretamente e abre o Viewer Web **no mesmo exame**
  (sem janela duplicada). Alternativa futura: conector local VYONIX (serviço no computador do médico, com pareamento) —
  só com proposta de segurança aprovada.
* Outros visualizadores (Horos/OsiriX no macOS, RadiAnt, MicroDicom no Windows): investigar mecanismos de abertura
  por URL/arquivo **sem presumir suporte**; nenhum é habilitado sem integração segura validada.
* Nunca credenciais permanentes em URL; tokens curtos; auditoria; controle de cópia local.

## 5. Ordem de apresentação dos protótipos (seção 7 do pedido)
1 Técnico — Exames recebidos · 2 Conferência técnica com Prioridade e Trocar médico · 3 Fila do radiologista ·
4 Ambiente de laudos · 5 Preferências do Viewer · 6 Portal — início · 7 Portal — exames · 8 Portal — resultado e imagens ·
9 Portal — celular. Todos marcados **PROTÓTIPO** com dados fictícios; registrados em `Telas_Apresentadas.md`.

## 6. Decisões do proprietário a registrar
| ID | Decisão | Situação |
|---|---|---|
| D-01 | Rótulos de prioridade Rotina / Prioritário / Urgente sobre routine/urgent/stat | Pendente |
| D-02 | Técnico efetua ou só solicita "Trocar médico" e mudança de prioridade (por papel) | Pendente (hoje: solicita; efetua com permissão) |
| D-03 | Campos técnicos estruturados da conferência (protocolo, contraste, intercorrências, qualidade) — lista e obrigatoriedade por instituição | Pendente |
| D-04 | Portal do Paciente: protótipo autorizado; uso real só após BLK-06 | Registrado (pedido) |
| D-05 | Visualizador local: Weasis como primeira integração; detecção pela busca do manifesto | Proposto |

## 7. Plano incremental (sem troca em massa)
1. Protótipos 1–9 para avaliação (PROTÓTIPO). 2. Itens P1 já no backlog: INT-01 (publicação condicionada), INT-02
(estado único do exame), INT-03 (prazo na fila), INT-04 (contexto no laudo), A05-003/009. 3. Menus por perfil
(componente de navegação único guiado pelas permissões efetivas; testes e2e por perfil). 4. Conferência técnica
estruturada (D-03) e Trocar médico (D-02). 5. Visualizador preferencial (Weasis) após A03-008. 6. Portal do
Paciente só após BLK-06. Critérios de aceitação e testes: os da seção 10 do projeto UX + matriz acima (teste de
API por ação × papel; e2e por perfil; nada de menu sem permissão correspondente).
