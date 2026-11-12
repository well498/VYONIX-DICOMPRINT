# P0 BLOQUEANTE 0.3.2 — Isolamento por unidade

Decisão do proprietário: 05/11/2026, 22:05. Ramo: `p0-isolamento-unidade`.
Agentes: A01, A02, A04, A07 e A08. A04 escreveu a lista de correções, A07 a bateria de testes e A08 a migração e a simulação.

## Regra aplicada no backend

O módulo é `vyonix/auth/scope.py`.

| Regra do proprietário | Como ficou |
|---|---|
| 1. Cada técnico vê só as suas unidades | Toda rota que lê ou altera exame, pedido, agendamento, paciente, laudo ou imagem confere a permissão **na unidade do objeto**. As listas filtram no SQL, antes do LIMIT. |
| 2. Quem tem várias unidades alcança só essas | `scope.sites()` devolve o conjunto exato de unidades do papel. Papel em todas as unidades = sem filtro. Para **médico**, vale a interseção papel × vínculo vigente (`scope.eff_sites`), também nas imagens. |
| 3. Exame sem unidade fica restrito | `site_id NULL` só passa para quem tem a permissão **em todas** as unidades, ou para o médico vinculado à instituição inteira. Isso substitui a exceção V-03 da Missão 2. |
| 4. Backend, APIs, banco, PACS e visualizadores | Rotas RIS, clínicas e de laudos. No PACS: QIDO filtrado no SQL; WADO, metadata, séries e qualidade com 404; lançador do Viewer e anteriores; Weasis revalidado a cada uso da credencial; STOW sem acrescentar imagens a estudo de outra unidade. |
| 5. Instituição é a fronteira principal | Continua o RLS por `tenant_id`. A simulação roda no papel da aplicação, com RLS. |
| 6. Toda alteração revalida | Médico, prioridade, estado, checklist, sinalização, duplicado, cancelamento, conciliação e compartilhamento conferem a unidade. A conciliação recusa pedido e estudo de unidades diferentes (`409 unit_mismatch`). O compartilhamento recusa destinatário fora da unidade (`409 share_out_of_site`). |
| 7. Financeiro sem dados clínicos | O modelo "Administrador Financeiro" perdeu `ris.schedule.read`. Só fica `core.license.read`. |
| 8. Auditoria | Toda recusa por escopo grava `access.denied` com motivo, permissão, rota e método. A gravação é feita numa sessão própria, porque a transação da rota é desfeita. Há deduplicação de 10 min e teto de 20 por minuto por usuário, contra rajadas de frames. |

## Entrada de novos exames com unidade

- **Pedido:** recebe a unidade informada ou a do atendimento. Usuário restrito precisa informar a unidade, que é preenchida sozinha quando ele tem uma só.
- **Estudo conciliado:** herda a unidade do pedido (`site_source = pedido`).
- **Instituição com uma só unidade:** a unidade é atribuída sozinha (`unica`).
- **STOW de usuário de uma única unidade:** o estudo recebe essa unidade (`manual`).
- **Liberação de recepção retida de equipamento cadastrado numa unidade:** o estudo recebe a unidade do equipamento (`no_dicom`).
- **Unidade já definida:** nunca é sobrescrita na entrada.

## Exames antigos sem unidade (não aplicado)

Todos os 20 estudos DEMO da instância do proprietário estão sem unidade. Depois desta versão, quem é restrito a uma unidade deixa de vê-los até a vinculação. Isso é a regra 3.

- `vyonix unidade-simular --saida sim.json --csv sim.csv`
  - **Somente leitura**: transação READ ONLY, nada é gravado.
  - Para cada estudo, mostra a unidade proposta e a evidência: pedido, atendimento, agendamento, equipamento DICOM ou unidade única.
  - Mostra também os conflitos e os estudos que não têm proposta.
  - O arquivo não contém nome, accession nem UID.
- `vyonix unidade-aplicar --simulacao sim.json --sha256 <aprovado> --aprovado-por "<nome>" [--seco]`
  - Aceita só o arquivo cujo SHA-256 foi aprovado, da mesma instituição e com até 7 dias.
  - Reavalia cada estudo e grava só onde a unidade continua vazia e a evidência não mudou.
  - Registra `clinical.study_site_assignments` e a auditoria `clinical.study.site`.
  - Rodar de novo não aplica duas vezes.

**Nenhuma aplicação foi feita.** A simulação na instância do proprietário depende da autorização dele.

## Banco de dados

A migração `clinical_0001` (novo ramo `clinical`, depende de `core_0001`) só **acrescenta**; não apaga nem altera nada que já existe:

- `orders.site_id`;
- `studies.site_source`, `site_set_at` e `site_set_by`;
- índices;
- a tabela `clinical.study_site_assignments`, com RLS forçado. O papel da aplicação só tem SELECT e INSERT nela.

## Testes

- `tests_platform/test_p0_isolamento_unidade.py`, escrito por A07, revisor independente, antes da correção. São 25 cenários com duas unidades fictícias, técnicos com permissões diferentes, médico vinculado só à A, coordenação, recepção, financeiro, exame sem unidade e uma segunda instituição. Tudo é verificado por **API direta**.
- Antes da correção (commit 0464c16): 15 de 24 falhavam.
- Depois da correção: **25 de 25 passam**. O 25º cobre a simulação somente leitura e a aplicação só com o SHA-256 aprovado.
- `test_m2_security.test_r04` foi ajustado à regra 3: antes exigia acesso de papel de unidade a exame sem unidade.
- **Suíte completa** (`tests_platform`, PostgreSQL 16 local, commit 4b3ae50): **316 testes, OK** (3 pulados, os mesmos de antes).
  - A primeira execução mostrou 6 regressões, todas corrigidas:
    - camadas de domínio;
    - RLS declarado na migração;
    - grafo de migração;
    - código `out_of_scope` do médico;
    - expectativa V-03.

## Revisão independente A04 (09/11/2026) e correções

A04 encontrou 3 vazamentos P1 e 9 itens P2/P3. Os P1 foram reproduzidos com dados fictícios e todos têm teste.

| # | Sev. | Achado | Correção | Teste |
|---|---|---|---|---|
| N1 | P1 | Histórico do paciente mostrava pedido/atendimento de outra unidade (accession, solicitante, sala) | Itens de outra unidade aparecem só com data e tipo (`restricted`) | p26 |
| N2 | P1 | Usuário com papéis diferentes em duas unidades cancelava agendamento da outra | A permissão que autoriza aquela mudança precisa valer na unidade do pedido | p27 |
| N3 | P1 | Médico com papel em todas as unidades e vínculo só numa via listas e imagens das demais e os exames sem unidade | Interseção papel × vínculo em listas clínicas/RIS, fila de laudos, PACS e visualizadores. **Muda o modo `organization` do Viewer para médicos:** o vínculo passa a valer sempre. | p28 |
| N4 | P2 | `report.assign` de uma unidade liberava rascunho, revisões, envio ao PACS e devolução de outra | `report.assign` conferido na unidade do exame | — |
| N5 | P2 | Produção médica de outras unidades com `report.production.all` de uma unidade | Exige a permissão em todas as unidades | p29 |
| N6 | P2 | Listagem aberta de pacientes sem vínculo para quem cadastra numa unidade | Só em busca dirigida (identificador ou nome com 3+ letras) | p30 |
| N7 | P2 | Equipamento de uma unidade consultava (C-FIND, MWL, C-MOVE/C-GET) a instituição inteira | Equipamento com unidade cadastrada só enxerga essa unidade | — |
| N8 | P2 | Central de Exames: pedido da B ligado a estudo da A aparecia na A | A unidade do pedido decide; o estudo só desempata sem unidade no pedido | — |
| N9 | P2 | C-STORE normal entrava sem unidade | Estudo novo herda a unidade do equipamento cadastrado (`no_dicom`) | — |
| N11 | P3 | Lote de liberação e lançadores não auditavam a recusa | `access.denied` também nesses caminhos | — |
| N12 | P3 | Upload de anexo lia até 25 MB antes de autorizar | Autoriza antes de ler o corpo | — |
| N10 | P3 | Críticos e qualidade filtram depois do limite (só disponibilidade, sem vazamento) | Pendente | — |

**Depois das correções da revisão A04** (commit 9b9b25b):
- `test_p0_isolamento_unidade`: **30 de 30 passam**.
- Suíte completa: **321 testes, OK** (3 pulados).
- Dois testes antigos foram ajustados:
  - `test_viewer_launch` passou a esperar o vínculo do médico também no modo `organization` (N3);
  - `test_ris_exam_center` dependia da data real e falhava depois de 11/11/2026 também no commit anterior. Foi corrigido sem mudar a regra.

## Decisões do proprietário de 12/11/2026 e o que foi feito

| # | Decisão | Situação |
|---|---|---|
| 1 | Médico: papel + vínculo vigente + permissão do recurso; o modo `organization` não contorna; sem exceção genérica | Em vigor (N3, teste p28). Registrado no ADR-0015. |
| 2 | Remover automaticamente as permissões clínicas dos perfis Financeiro existentes, registrando o estado anterior | Feito: `auth.harden_financial_roles`, chamado pelo `vyonix migrate` em cada instituição. Grava `role.permissions.hardened` com a lista anterior, o que saiu, o que ficou e quantos usuários têm o perfil. Ficam `core.*` e `report.production.*`. O perfil não aceita mais permissão clínica (422). Teste p32. |
| 3 | Compartilhamento entre unidades bloqueado por padrão; preparar a arquitetura da exceção | Continua bloqueado (`409 share_out_of_site`). Desenho no ADR-0015, **não habilitado**. |
| 4 | Simulação somente leitura dos 20 exames DEMO no computador do proprietário | **Não executada:** o computador do proprietário não estava acessível em 12/11. Pendência no relatório consolidado. |
| 5 | Merge em `develop` e CI | Ver `RELATORIO_CONSOLIDADO_SEGURANCA_0.3.2.md`. |
| 6 | Críticos e qualidade: filtrar antes do limite | Feito (N10): unidade no SQL antes do `LIMIT` em `/report/critical`, `/pacs/quality` e nas pendências de qualidade do painel do técnico. Teste p31. |
| 7 | Critérios de liberação da 0.3.2 | Acompanhados no relatório consolidado. A versão continua **bloqueada**. |

Sobre a decisão 2: se o financeiro precisar de dados de agendamento para faturamento, isso será uma permissão administrativa nova, com dados mínimos (sem nome de paciente nem dados clínicos). Ela não foi criada nesta etapa.

## Pendências

1. **Simulação e vinculação dos exames antigos sem unidade.** A aplicação depende da aprovação do proprietário sobre o relatório da simulação.
2. **Frontend.** Os menus seguem as permissões. Faltam os botões por exame (capabilities por unidade) na nova Central.
3. **Compartilhamento excepcional entre unidades.** Só o desenho (ADR-0015).
4. **Permissão administrativa de faturamento** com dados mínimos, se o financeiro precisar.
