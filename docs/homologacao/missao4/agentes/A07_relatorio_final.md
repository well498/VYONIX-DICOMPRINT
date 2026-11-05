# A07 — Relatório final de QA — Missão 4 (VYONIX-DEMO-20261105, 0.3.1 edge/homologação)

**Base:** somente as evidências da instância real (https://localhost:8444, execução do coordenador em 05/11/2026
entre 14:42 e 14:53 UTC):
- `export/log_testes.tsv`: 318 verificações, 5 com ok=0;
- `export/VYONIX_DEMO_EXPORT_20261105.json`: 479 eventos de auditoria, `audit/verify ok:true`;
- `export/01_estado_pos_reconexao.md` e `02_stow.md`;
- capturas em `evid/`;
- observações (a) a (h) do coordenador.

Os testes locais do A07 (Linux, `python3 -m unittest`, Ran 68 OK) só sustentam as 4 linhas marcadas "local". Eles
não valem como evidência da instância. Matriz executada: `A07_matriz_executada.csv` (123 testes + 12 critérios
oficiais).

## 1. Contagem por status (123 testes, sem os critérios)

| Status | Qtde |
|---|---|
| APROVADO | 64 (60 na instância + 4 locais) |
| REPROVADO | 12 |
| BLOQUEADO | 44 (não executados nesta rodada ou dependentes do proprietário) |
| NÃO IMPLEMENTADO | 7 |

Mapeamento log → matriz: cada linha cita os IDs do log na coluna `evidencia`. As verificações do log sem linha
prévia viraram linhas novas:

| Linha nova | Verificações do log |
|---|---|
| T-SEC-12 | logins dos 14 usuários |
| T-SEC-13 | IDOR |
| T-USR-06 | self_roles |
| T-RIS-13 | MWL O16 |
| T-TEL-14 | modelos e frases |
| T-TEL-15 | produção |
| T-TEL-16 | lote |
| T-TEL-17 | reencaminhamento |
| T-PRM-09 | recepção lendo o preparo |

As observações (b) a (e) do coordenador viraram T-OBS-01..04. Os 5 itens ok=0 do log são todos REPROVADO:
FIN-09, FIN-10, REC2-11, REP-E3 e MED02-04. T-PRM-ADM-10-invalido foi desconsiderado (erro de execução) e refeito
em ADM11-01.

## 2. Resumo por módulo (A/R/B/NI)

| Módulo | A | R | B | NI | Comentário |
|---|---|---|---|---|---|
| Preservação (PRE) | 4 | 0 | 2 | 0 | LAN e DICOM Print não conferidos |
| Segurança (SEC) | 7 | 0 | 6 | 0 | CSRF, stage, enumeração e logout ok. Bloqueio, MFA, limite, expiração e LAN não executados |
| Adm. Global (GLB) | 2 | 0 | 3 | 1 | operator_only confirmado |
| Institucional (INST) | 0 | 0 | 3 | 0 | nenhuma alteração de configuração executada |
| Unidades (UNI) | 2 | 3 | 1 | 1 | F1 confirmado na instância |
| Usuários (USR) | 5 | 0 | 1 | 0 | desativação não executada |
| Perfis/permissões (PRF+PRM) | 7 | 2 | 2 | 0 | 14 perfis no backend. Menus BLOQUEADO (g) |
| Pacientes (PAC) | 1 | 0 | 5 | 0 | validações de cadastro não exercitadas |
| Médicos (MED) | 2 | 0 | 1 | 1 | |
| Equipamentos (EQP) | 3 | 0 | 2 | 0 | C-ECHO ok. DIMSE externo não |
| PACS/DICOM (PACS+DCM) | 6 | 1 | 3 | 0 | STOW, duplicidade, conciliação auto/manual ok. Motor ausente na instalação (P1) |
| RIS | 9 | 2 | 3 | 0 | exclusividade do técnico e trava após início ok |
| Telelaudos (TEL) | 12 | 1 | 3 | 1 | autoria, senha, imutabilidade, adendo, lote ok |
| Viewer (VWR) | 0 | 0 | 5 | 0 | só launch via API. Renderização não registrada |
| Portal (PORT) | 0 | 0 | 0 | 2 | 404 confirmado |
| Auditoria (AUD) | 3 | 1 | 0 | 0 | cadeia íntegra. Ator da liberação = nome |
| Armazenamento (ARM) | 0 | 1 | 1 | 0 | backup pendente. Aviso de backup do PACS |
| Integrações (INT) | 0 | 0 | 1 | 1 | FHIR/HL7 não executados |
| Persistência (PER) | 1 | 0 | 2 | 0 | reinício aguardando o proprietário |
| UX | 0 | 1 | 0 | 0 | 375 px |

## 3. Falhas (REPROVADO) por severidade

| # | Sev | ID | Teste | Evidência |
|---|---|---|---|---|
| 1 | **P1** | M4-INST-01 | T-PACS-05 | Instalação nova deixa `pacs` habilitado sem motor: 20 STOW = 503 até o atalho "Preparar modulos" (01/02_*.md) |
| 2 | **P1** | F1 / A04 F-01 / A08-M4-01 | T-UNI-04 | `site_id=null` em todos os estudos. demo.tecnico.satelite atribui exames de qualquer unidade (RIS-C2 200) |
| 3 | **P1** | A04 F-02 / A03 F4 | T-PRM-02 | financeiro lê o preparo (FIN-09 200) e a linha do tempo clínica (FIN-10 200) |
| 4 | **P1** | A04 F-02 | T-PRM-09 | recepção lê o preparo técnico (REC2-11 200) |
| 5 | P2 | A04 F-03/F-05 | T-UNI-05 | Dr. Bruno: fila vazia/403 para laudar, mas metadata DICOMweb 200 (MED02-04) |
| 6 | P2 | A03 F3 | T-TEL-09 | Rascunho devolvido para correção continua editável (REP-E3 200) |
| 7 | P2 | M4-AUD-01 | T-AUD-02 | `report.finalize` grava o nome de exibição como ator, e o filtro por login não encontra (audit seq 420-452) |
| 8 | P2 | M4-UI-01 | T-OBS-01 | GET /ris/prep devolveu 409 uma vez em ~6 (intermitente, captura em evid/). Causa não determinada |
| 9 | P2 | M4-BKP-01 | T-OBS-03 | "Nenhum backup automático do PACS registrado / não foi possível medir". Trilha: export às 08:54 com 0 bytes |
| 10 | P3 | A03 F5 | T-RIS-12 | O04 rebaixado para rotina mantém o prazo de urgente (due 18:43:54Z) |
| 11 | P3 | M4-UI-02 | T-OBS-02 | Laudos em 375 px alarga para 499 px |
| 12 | P3 | M4-UI-03 / A01-4 | T-OBS-03/04 | Sistema leva 4-6 s. Texto da tela Unidades cita licença |

Não há P0 comprovado nesta rodada. Os itens P0 de acesso/instalação dependem da validação no PC (LAN, reinício,
Print), que está BLOQUEADA.

Comportamentos registrados sem reprovação (decisão do proprietário): o médico cria modelo institucional
(T-TEL-13, A03 F6); o encaminhamento é bloqueado por 2 min após a última imagem (RIS-B3 422, regra do sistema).

**NÃO IMPLEMENTADO (7):** Adm. Global no edge, unidade do pedido (A08-M4-02), desligamento de médico, retificação
(405), Portal do Paciente (404), Notify e Connect (entrada HL7/FHIR).

**Ressalva T-PRE-03:** o admin redefiniu a senha de tecnico-cdi às 09:11 e às 10:15 (horário local), logo após
falhas de login do próprio tecnico-cdi. Parece uso do proprietário, mas o ator `admin` é compartilhado com o
coordenador: **confirmar com o proprietário**.

## 4. Painel por agente (testes da matriz executada)

| Agente | Total | APROVADO | REPROVADO | BLOQUEADO | NI |
|---|---|---|---|---|---|
| A01 Arquitetura | 7 | 2 | 0 | 2 | 3 |
| A02 PACS/DICOM | 14 | 6 | 0 | 7 | 1 |
| A03 RIS/Telelaudo | 38 | 22 | 4 | 9 | 3 |
| A04 Segurança | 45 | 26 | 3 | 16 | 0 |
| A05 UX | 6 | 0 | 3 | 3 | 0 |
| A06 Windows/infra | 8 | 0 | 2 | 6 | 0 |
| A07 QA (local) | 4 | 4 | 0 | 0 | 0 |
| A08 Banco | 5 | 4 | 0 | 1 | 0 |
| **Total** | **123** | **64** | **12** | **44** | **7** |

## 5. Parecer sobre os 12 critérios oficiais

| CA | Critério | Parecer | Fundamento |
|---|---|---|---|
| 1 | Acesso real comprovado | **APROVADO** | 318 chamadas reais na instância, health 0.3.1. LAN ainda não comprovada |
| 2 | Oito agentes acionados ou limitações documentadas | **APROVADO** | A01..A08 com relatórios. A06/A08 sem `*_relatorio_final.md` na pasta: confirmar |
| 3 | Funcionalidades implementadas testadas | **BLOQUEADO** | 44 testes não executados: críticos, envio ao PACS, FHIR/HL7, viewer visual, Weasis, bloqueio, MFA, compartilhamento, backup, reinício |
| 4 | Cadastros fictícios preservados | **APROVADO** | Nada excluído. Dados DEMO e do proprietário íntegros (ressalva T-PRE-03) |
| 5 | Usuários demo conseguem login | **APROVADO** | 14/14 login + troca 200 |
| 6 | Pacientes acessíveis | **APROVADO** | 15 pacientes. Acesso conforme o perfil |
| 7 | Exames e laudos vinculados | **APROVADO** | 19 DEMO + O16 conciliados. 10 laudos (7 finais) |
| 8 | Permissões verificadas | **REPROVADO** | Verificação feita nos 14 perfis, mas com 3 falhas de acesso (2 P1, 1 P2). Menus BLOQUEADO |
| 9 | Inventário corresponde aos dados reais | **BLOQUEADO** | Planilha de inventário da M4 não encontrada no scratchpad |
| 10 | Relatórios e evidências disponíveis | **APROVADO** | log, export, md, capturas, matriz e este relatório |
| 11 | Proprietário tem instruções para reutilizar | **BLOQUEADO** | Nenhum guia de reutilização da M4 encontrado |
| 12 | Pendências e falhas registradas | **APROVADO** | Seção 3 + coluna `defeito` |

**Parecer geral:** a homologação funcional **não está aprovada**. Ficam abertos:
- CA-8: 2 P1 de permissão e o P1 de unidade;
- CA-3: cobertura incompleta;
- CA-9 e CA-11: entregáveis ausentes;
- o P1 da instalação nova (motor PACS).

## 6. Não verificado

- O acesso pela LAN, o DICOM Print, o backup, o reinício e os menus por perfil dependem do proprietário ou da
  interface.
- Os 44 testes BLOQUEADOS.
- Os resultados com usuário diferente do especificado estão anotados em cada linha (SEC-03/04/07, PRM-06/08,
  RIS-03).
- O conteúdo das 3 capturas foi aceito conforme a descrição do coordenador: o A07 não reproduziu o 409 nem a
  largura de 499 px.
