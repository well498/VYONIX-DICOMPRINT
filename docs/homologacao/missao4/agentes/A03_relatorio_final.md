# A03 — Relatório final RIS/Telelaudo (Missão 4, Fase 4)

**O que eu fiz:** li o código 0.3.1 (vyonix/ igual a d1af7f2), escrevi o roteiro `A03.md` e rodei 11 testes locais
(Linux, OK). Quem executou na instância real foi o coordenador. Eu só conferi as evidências `log_testes.tsv`
(318 linhas) e `VYONIX_DEMO_EXPORT_20261105.json` (gerado em 14:49Z). Não tive acesso à instância.

## Resultado por etapa (somente evidência)
| Etapa | Status | Evidência / observação |
|---|---|---|
| A Recepção | APROVADO | A1–A4 com 201/200; agendamento sem fuso deu 422; atribuir e mudar prioridade deram 403 `technician_only`; CSRF 403 |
| B Técnico/preparo | APROVADO | Checklist e encaminhamento OK. O06–O15 deram 422 até passarem 2 min sem imagens novas, depois 200 (regra prevista no código). O10 com pendência aberta deu 422. Cancelar e devolver deram 403 |
| C Atribuição/prioridade | APROVADO (com F1) | Admin, supervisor, coordenação e gestor receberam 403 `technician_only`. Redistribuição do O02 auditada com `previous`=Ana. O06→Bruno deu 403 `physician_not_linked` |
| D Início/autoria | APROVADO | Após o início, mudar prioridade, médico ou atribuição deu 409 `report_started`. Os casos de autoria deram 409 `assigned_to_other`, 403 `not_responsible` e 404 (modelo e frase de outro médico). O visualizador não iniciou o laudo |
| E Devolução | REPROVADO (F3) | O05: devolução 200; reencaminhado e voltou à Ana (auditoria: "volta ao médico que iniciou"); troca de médico 409. Mas o rascunho devolvido continuou editável (T-REP-E3: 200, o esperado era 409). E5 não foi executado |
| F Liberação | APROVADO | Sem `row_version` 422, versão velha 409, senha errada 403, lote sem confirmação 422, lote 200. Em todas as versões `signature_mode=password`. Imagem de assinatura NÃO VERIFICADA |
| G Adendo/retificação | APROVADO / NÃO IMPLEMENTADO | Adendo em rascunho 409, de outro médico 403, adendos de O01 e O07 201. `/rectify` responde 405 |
| H Minha Produção | APROVADO | Respostas 200 (inclusive CSV); produção de outra médica 403; supervisor 200. As contagens vêm dos laudos do export (Ana 6 liberados + 2 adendos, Carla 1). O conteúdo JSON da produção não está no log |
| I Outros perfis | REPROVADO (requisitos) | Financeiro lê preparo e linha do tempo (FIN-09/10: 200, F4). Recepção lê preparo (REC2-11: 200). Médico 02 lê metadados DICOM fora do escopo (MED02-04: 200). PUT do SLA e prioridade pelo `demo.multi` não foram executados |
| J Histórico/portal | APROVADO / NÃO IMPLEMENTADO | Histórico P04 e anteriores 200; Portal do paciente 404 |

## Estado final no export
| Pedido | Prior. | Etapa | Médico | Laudo |
|---|---|---|---|---|
| O01 | routine | reported | Ana | final v2 (adendo) |
| O02 | routine | assigned | Carla | rascunho |
| O03 | stat | reported | Carla | final v1 |
| O04 | routine | assigned (prazo 15:43 de 05/11) | Ana | rascunho |
| O05 (P04) | urgent | reported | Ana | final v1 |
| O06 | routine | assigned (reserva) | Carla | sem laudo |
| O07 | routine | reported | Ana | final v2 (adendo) |
| O08 | routine | forwarded | — | sem laudo |
| O09 | urgent | assigned (prazo 15:43) | Carla | sem laudo |
| O10 | routine | pending (`artifacts`) | — | sem laudo |
| O11 | stat | reported | Ana | final v1 |
| O12 | routine | assigned | Carla | sem laudo |
| O13 | routine | reported | Ana | final v1 |
| O14 | routine | reported | Ana | final v1 |
| O15 | routine | assigned | Carla | rascunho |
| O16 | routine | received (agendamento `received`, `incomplete=true`) | — | sem laudo |

Pedidos dos laudos liberados ficaram `completed`; os demais, `in_progress`. Cadeia de auditoria: `ok:true`. O estudo
do proprietário (JoaoVictor/tecnico-cdi) aparece no export e não foi tocado.

## Achados confirmados
- **F1 (P1):** `site_id` nulo em todos os estudos. Médico 02 sem escopo; técnico de uma unidade age em qualquer exame.
- **F3 (P2):** laudo devolvido para correção continua editável.
- **F4 (P2):** financeiro (e também a recepção) leem o preparo do exame.
- **F5 (P3):** O04 voltou a `routine` e manteve o prazo de 4 h.
- **F6 (P3):** médico cria modelo da instituição (201).
- **A04 F-03 (P1/P2):** médico fora do escopo lê metadados DICOM.

**Não verificado:** F2 (prioridade omitida em `/report/assignments`), E5, imagem de assinatura, SLA não retroativo,
expiração da reserva do O06 e PDF com identidade visual.

## Recomendações
1. Propagar a unidade pedido/agendamento/nó → estudo, ao receber e ao conciliar.
2. Bloquear `PUT`/`finalize` com o preparo em `returned`, e exigir encaminhamento em `open_report`.
3. Tirar o preparo e os anexos de `ris.schedule.read`.
4. Tornar `priority` obrigatória em `/report/assignments`.
5. Aplicar o escopo do médico ao DICOMweb.
6. Rodar E5 e o teste do SLA com aprovação do proprietário.
