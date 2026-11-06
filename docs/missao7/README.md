# Missão 7 — Central de Exames do Técnico (etapas 1 e 2: diagnóstico e redesenho)

Situação em 05/11/2026: **PROPOSTO** (nada implementado). Protótipo interativo: quadro "1c · Técnico — Central de Exames v3"
no canvas de protótipos VYONIX. Relatórios dos agentes A01–A08 nesta pasta (leitura de código; A07 rodou regressão local).

## Achados que mudam a ordem de trabalho
| Sev | Achado | Agente |
|---|---|---|
| P0 | Central de exames e Painel do técnico não filtram por unidade; estudo sem unidade é visível e alterável por qualquer técnico | A01, A04 |
| P1 | Estudo sem unidade (F-02): ingestão não grava unidade e conciliação não herda a do pedido/atendimento | A02, A04, A08 |
| P1 | `prep.queue` ~6 consultas por estudo, filtros aplicados após corte de 300 | A01 |
| P1 | Financeiro tem `ris.schedule.read` (vê pacientes na Central) | A04, A07 |
| P1 | Ramo WIP `usuarios-admin-principal` quebra 2 testes aprovados (delegação) — corrigir antes de mesclar | A07 |
| P1 | CI só testa atualização a partir da 0.2.0; artefato 0.3.1 expira em 05/12/2026 | A06 |
| P2 | Técnico não abre laudo (sem `report.read`): criar leitura restrita ao laudo liberado | A01, A03 |
| P2 | Visualizador abre menu com 4 opções; falta `default_viewer` e restringir alternativas | A02 |
| P2 | Cancelamento aceita exame com laudo iniciado; sem reversão; pendência sem responsável | A03 |

## Novo (a implementar após aprovação)
`GET /ris/central` (consultas em lote, paginação, `q`, filtros médico/situação do laudo, filtro de unidade no SQL);
`POST /ris/central/batch`; desconsiderados (`ris_0008`); compartilhamento com paciente **simulado** (`ris_0009` +
`notify_0001`, sem envio real); unidade do estudo (`core_0006`, atribuição só com aprovação); `web/src/pages/exams/*`.
Dependências do proprietário: Portal do Paciente (forma de acesso, validade do link), rótulos Rotina/Prioridade/Urgência,
backfill de unidade dos estudos existentes, provedor de WhatsApp/e-mail (custo).
