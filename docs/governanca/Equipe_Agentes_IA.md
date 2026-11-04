# Equipe de agentes especializados de IA — VYONIX Medical Platform

Implantação pedida pelo proprietário em 04/11/2026 04:09. Este registro distingue:
**CONFIGURADO** (definição existe e é válida) · **EXECUTADO** (recebeu e realizou tarefa real, com registro de
execução) · **VALIDADO** (resultado revisado e aceito pelo coordenador e/ou pelo proprietário).

## Agentes configurados (`.claude/agents/`, frontmatter YAML validado)
| Agente | Arquivo | Ferramentas | Atuação |
|---|---|---|---|
| A01 Arquiteto de Software | `a01-arquiteto.md` | Read, Grep, Glob, Bash | somente leitura |
| A02 PACS/DICOM | `a02-pacs-dicom.md` | Read, Grep, Glob, Bash | análise; edição só se a tarefa pedir |
| A03 RIS e Telelaudos | `a03-ris-telelaudos.md` | Read, Grep, Glob, Bash | análise; edição só se a tarefa pedir |
| A04 Segurança e LGPD | `a04-seguranca-lgpd.md` | Read, Grep, Glob, Bash | somente leitura; provas só no scratchpad |
| A05 UX/UI | `a05-ux-ui.md` | Read, Grep, Glob, Bash, Write, Edit | protótipos no canvas; nada definitivo em `web/src` sem aprovação |
| A06 Windows/DevOps | `a06-windows-devops.md` | Read, Grep, Glob, Bash | leitura; não dispara nem cancela CI |
| A07 QA e Testes | `a07-qa-testes.md` | Read, Grep, Glob, Bash | revisor independente |
| A08 Banco de Dados | `a08-banco-dados.md` | Read, Grep, Glob, Bash | somente leitura |

Todas as definições carregam as regras permanentes: não modificar o DICOM Print, dados só fictícios, nada
destrutivo, sem push/commit/CI, evidência obrigatória, distinguir teste local × CI × validação do proprietário.

### Limitação técnica observada (sem contornar)
A sessão atual do Claude Code (2.1.318) carregou a lista de tipos de agente ao iniciar. Chamar `a01-arquiteto`
pelo nome devolveu "Agent type not found" (tentativa registrada em 04/11 04:11). Os tipos personalizados passam a
ser acionáveis pelo nome numa sessão nova (a pasta também foi exposta na raiz de trabalho da sessão,
`/home/claude/.claude/agents` → `vyonix-dicomprint/.claude/agents`). **Nesta sessão**, cada agente é executado
como subagente real do tipo `general-purpose` que **lê e segue o seu arquivo de definição** e abre o relatório
com "AGENTE: A0x — definição lida".

## Coordenação
- Sessão principal = coordenadora: distribui, acompanha, integra alterações, roda testes, atualiza backlog.
- Paralelismo só entre tarefas independentes; agentes de revisão não editam o repositório; integração centralizada.
- Registros de execução: arquivos de transcrição em `~/.claude/projects/-home-claude/<sessão>/subagents/`.

## Execuções
### Missão 1 — auditoria coordenada da retirada do licenciamento (04/11/2026, lançadas às 04:12, em paralelo)
| Agente | Tarefa | Estado |
|---|---|---|
| A01 | Dependências de licença restantes; acoplamento com o DICOM Print | EXECUTANDO |
| A04 | Autenticação, autorização, isolamento e auditoria após retirar a licença; GET /system | EXECUTANDO |
| A06 | Fase 3 (dd6a2e6), instalador 0.3.0, atualização sobre 0.2.0, critério 2.9 | EXECUTANDO |
| A07 | Revisão independente dos testes novos/alterados e cobertura | EXECUTANDO |
| A08 | Tabelas legadas, migração report_0012, concorrência, prazos | EXECUTANDO |

### Execuções anteriores (29/10/2026, tipo general-purpose, sem definição de agente)
Auditoria PACS/Viewer, Auditoria QA/Segurança, Auditoria RIS/Telelaudos, UX Fase A, UX Fase B — resultados
consolidados em `Registro_Aperfeicoamento.md` (A03/A04/A05) e `docs/ux/Fase_A_*`, `Fase_B_*`.
