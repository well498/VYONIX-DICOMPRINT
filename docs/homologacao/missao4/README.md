# Missão 4 — Homologação funcional real com dados fictícios persistentes (05/11/2026)

Instância: PC do proprietário (desktop-3qf85g7), VYONIX 0.3.1 edge/homologação, https://localhost:8444. Identificador: VYONIX-DEMO-20261105.
Execução real: 318 verificações na instância (313 conforme, 5 divergentes). Matriz A07: 64 aprovados, 12 reprovados, 44 bloqueados, 7 não implementados.
Entregas ao proprietário (no PC, Downloads\VYONIX_homologacao\Entregas): VYONIX_DEMO_CADASTROS_COMPLETOS.xlsx, VYONIX_DEMO_USUARIOS.xlsx,
VYONIX_DEMO_PACIENTES.xlsx, VYONIX_DEMO_GUIA_DE_ACESSO.pdf, VYONIX_RELATORIO_HOMOLOGACAO_FUNCIONAL.pdf, RELATORIOS_AGENTES/, EVIDENCIAS/.
Nenhuma senha armazenada; recuperação de acesso dos usuários demo pelo admin (Redefinir senha, troca obrigatória).

## Falhas confirmadas na instância
| ID | Sev | Falha |
|---|---|---|
| F-01 | P1 | Módulo PACS habilitável pela tela Sistema sem motor DICOM (STOW 503 até o atalho "Preparar modulos") |
| F-02 | P1 | Estudos sem unidade (site_id nulo): isolamento por unidade ineficaz; médico de unidade sem fila |
| F-03 | P1 | Financeiro e recepção leem o preparo clínico (GET /ris/prep/{id} 200) |
| F-04 | P2 | Médico fora do escopo lê metadados WADO |
| F-05 | P2 | Laudo devolvido continua editável |
| F-06 | P2 | 409 intermitente em GETs simultâneos (renovação de sessão com controle de versão — A01) |
| F-07 | P2 | Auditoria de liberação/adendo com nome exibido como ator; negações/leituras sem auditoria |
| F-08 | P2 | Sem comando de backup avulso; alerta de backup do PACS |
| F-09..F-16 | P3 | Prazo ao rebaixar prioridade, modelo institucional por médico, Laudos 375 px, textos de licença, "Laudar" para admin, Agenda, /health, agendamento pós-chegada |

Não implementado no edge: multi-instituição (Hospital Modelo, Rede Estadual), regiões, Administração Global, Portal do Paciente, Gateway,
perfis Paciente/Médico solicitante, retificação, ICP-Brasil. Bloqueados: DIMSE de entrada, menus por perfil na UI, flags de cookie,
reinício controlado e backup (scripts A06 entregues ao proprietário).
