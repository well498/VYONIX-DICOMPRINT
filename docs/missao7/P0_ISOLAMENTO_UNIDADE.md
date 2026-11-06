# P0 BLOQUEANTE 0.3.2 — Isolamento por unidade

Decisão do proprietário: 05/11/2026, 22:05. Ramo: `p0-isolamento-unidade`.
Agentes: A01, A02, A04, A07 e A08. A04 escreveu a lista de correções, A07 a bateria de testes e A08 a migração e a simulação.

## Regra aplicada no backend

O módulo é `vyonix/auth/scope.py`.

| Regra do proprietário | Como ficou |
|---|---|
| 1. Cada técnico vê só as suas unidades | Toda rota que lê ou altera exame, pedido, agendamento, paciente, laudo ou imagem confere a permissão **na unidade do objeto**. As listas filtram no SQL, antes do LIMIT. |
| 2. Quem tem várias unidades alcança só essas | `scope.sites()` devolve o conjunto exato de unidades do papel. Papel em todas as unidades = sem filtro. |
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

A migração `clinical_0001` (novo ramo `clinical`, depois de `core_0004`) só **acrescenta**; não apaga nem altera nada que já existe:

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

## Pendências e decisões do proprietário

1. **Financeiro em instalações existentes.** O papel "financeiro" já ativado continua com `ris.schedule.read` até o administrador removê-lo. O ajuste automático alteraria um papel que pode ter sido personalizado, por isso fica para aprovação.
2. **Compartilhar exame com usuário de outra unidade.** Hoje é recusado. A permissão `ris.exam.share.cross_site` foi reservada, mas não foi criada.
3. **Simulação dos 20 estudos DEMO.** Rodar na instância do proprietário somente com autorização dele.
4. **Frontend.** Os menus já seguem as permissões. Faltam os botões por exame (capabilities por unidade) na nova Central.
