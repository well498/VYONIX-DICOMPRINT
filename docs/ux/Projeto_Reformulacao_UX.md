# Projeto de reformulação da experiência do usuário (UX/UI) — autorizado em 29/10/2026 21:36

**Objetivo:** reformulação profunda da experiência (não só estética): interfaces modernas, humanas, simples e por
perfil, adaptadas à rotina dos profissionais de saúde brasileiros, mantendo a identidade VYONIX.

**Prioridade:** P3 no geral (UX), com correções P1 quando houver problema relevante de acesso, permissões ou
usabilidade operacional. **Não interrompe a homologação P0.** Nada é substituído em massa antes da aprovação da
proposta visual pelo proprietário.

## Ampliação de 29/10 21:45 — benchmarking profundo de plataformas brasileiras
Referências prioritárias: **RadCloud** (estudo especial), Audo, Telepacs, ASL Sistemas, Pixeon, Telelaudo, MV (outras
só com justificativa). Classificação obrigatória: CONFIRMADO · DECLARADO PELO FORNECEDOR · NÃO VERIFICADO ·
PROPOSTA VYONIX. Nada de áreas restritas; nunca afirmar teste de plataforma sem acesso. O modelo de login
multi-institucional divulgado pela RadCloud **não** substitui as contas independentes por instituição do VYONIX
(decisão aprovada). Conformidade de concorrente não prova conformidade do VYONIX. Assinatura, compartilhamento, IA
clínica, portal do paciente e uso diagnóstico passam por avaliação de segurança, privacidade e regulatória.

### Entregas (10)
| # | Entrega | Responsável | Estado |
|---|---|---|---|
| 1 | Relatório comparativo das plataformas brasileiras | UX/pesquisa (apoio 01) | Em execução |
| 2 | Estudo específico da RadCloud | UX/pesquisa | Em execução |
| 3 | Inventário das funcionalidades existentes no VYONIX | 01 + Fase A (UX) | Em execução |
| 4 | Matriz de oportunidades e lacunas (11 colunas: plataforma, funcionalidade, fonte, situação no VYONIX — implementada e adequada / precisa melhoria / parcial / não implementada / não recomendada / dependente de decisão ou conformidade —, problema, benefício, complexidade, riscos e dependências, prioridade, agente, critérios de aceitação) | 01 consolida; 03/04/05 revisam | Após 1–3 |
| 5 | Nova arquitetura de navegação por perfil | 01 + UX | Após 4 |
| 6 | Proposta de design system VYONIX | UX | Após 4 |
| 7 | Protótipos das principais telas (comparados com a experiência atual; funcionalidades preservadas) | UX | Após 5–6 |
| 8 | Plano de implementação incremental | 01 + 02 (impacto de empacotamento/atualização) | Após aprovação |
| 9 | Backlog priorizado por agente | 01 | Contínuo |
| 10 | Critérios de aceitação e testes | 04 | Com 4 e 7 |

Perfis incluídos: técnico, radiologista, solicitante, recepção, coordenador do CDI, administrador da clínica,
administrador global VYONIX, enfermagem, faturamento, auditoria, paciente e demais autorizados.

## Fases
| Fase | Conteúdo | Estado |
|---|---|---|
| A — Diagnóstico | Inventário de telas, menus, diálogos, formulários, ações, fluxos, perfis e permissões; problemas com evidência | Em execução (29/10, somente leitura) |
| B — Referências | Audo, Telelaudo, Telepacs, ASL RIS, Fleury, Laudos.AI, Pixeon, MV e outras; DOC/INF/HIP com fontes; sem copiar interfaces | Em execução (29/10, pesquisa pública) |
| C — Nova arquitetura | Menus laterais por perfil (recolhíveis), jornadas, permissões efetivas, ambientes | Após A e B |
| D — Protótipos | Propostas visuais das telas principais e mapas de navegação, **para aprovação** | Após C |
| E — Implementação | Gradual, por módulo e perfil, preservando dados, APIs e integrações | Após aprovação |
| F — Validação | Testes funcionais, visuais, de permissões, acessibilidade e regressão; medir cliques/tempo quando possível | Contínua |

## Regras preservadas
* Login por usuário e senha, contas por instituição, sem escolha de instituição; perfis configuráveis; múltiplas
  funções por profissional; isolamento institucional; autorização por recurso e estudo **no backend** (ocultar no
  frontend não é segurança).
* Nenhuma funcionalidade é eliminada sem identificar finalidade e dependências; funcionalidades anteriores continuam
  disponíveis aos autorizados.
* Decisões já aprovadas: VYONIX Viewer principal; Weasis só validação isolada; Oviyam desativado; "Abrir imagens"
  para todo usuário autorizado; acesso por vínculo configurável (padrão inalterado).
* Portal do paciente: requisito futuro sujeito a BLK-06 (segurança, privacidade, conformidade).
* Não modificar o VYONIX DICOM Print.

## Perfis a projetar
Técnico em radiologia · Médico radiologista · Recepção · Coordenador do CDI · Administrador da clínica · Médico
solicitante · Paciente (futuro) · Enfermagem, faturamento, auditoria, suporte técnico, administrador global VYONIX
e demais existentes — sem perfis obrigatórios para funções que a clínica não tem.

## Critérios de aceitação
Ver a mensagem do proprietário (seção 10): menus só relevantes e autorizados; próxima tarefa evidente; ações
fáceis de achar; linguagem natural; menos etapas; consistência visual; resoluções suportadas; permissões no
backend; funcionalidades preservadas; regressão aprovada; medição de cliques/tempo/conclusão quando possível.

## Especialista
O trabalho de UX é feito como apoio ao Coordenador (01), com 05 (fluxos médicos/técnicos/administrativos), 03
(imagens e listas de exames), 04 (permissões, acessibilidade, regressão) e 02 (empacotamento da nova interface).
Não foi criado agente permanente adicional; se a Fase C mostrar necessidade, será proposto com justificativa.
