# Relatório consolidado de segurança — versão 0.3.2 (P0 isolamento por unidade)

Data: 12/11/2026. `develop` em **4014570** (merge de `p0-isolamento-unidade`, c54b7b7), autorizado pelo proprietário em 12/11/2026.

**Situação: a versão 0.3.2 continua BLOQUEADA.** Faltam os critérios 2 (revisão final), 4 e 7 (aprovação do proprietário) e 8 (autorização para instalar).

## 1. O que foi verificado, e onde

| Nível | O que rodou | Resultado |
|---|---|---|
| **Local** (contêiner Linux, PostgreSQL 16) | `tests_platform` completo, antes do merge (c54b7b7) | 323 testes, OK, 3 pulados |
| **Local** | Isolamento por unidade (`test_p0_isolamento_unidade`) | 32 de 32 |
| **CI** `platform` (43210691816) | Suíte da plataforma, com isolamento e migrações | Aprovado |
| **CI** `viewer` (43210692069) | Visualizador | Aprovado |
| **CI** `deploy-windows`, envio (43210691887) | Instalador comercial e aceitação real no Windows | Aprovado |
| **CI** `deploy-windows`, homologação (43210699158) | Instala a **0.3.1 do proprietário** (SHA-256 `526605F9…28E4`), atualiza por cima, roteiro de 15 passos | Aprovado |
| **CI** `Windows release` (43210691820) | VYONIX DICOM Print (código não alterado) | Aprovado |
| **Homologação real no Windows do proprietário** | — | **Não executada** (depende de autorização) |

Testes locais e CI não equivalem à homologação final.

## 2. Critérios de liberação (decisão 7 do proprietário)

| # | Critério | Situação | Evidência |
|---|---|---|---|
| 1 | Aprovação do CI | **Atendido** | 5 execuções aprovadas em 4014570 |
| 2 | Revisão independente de segurança concluída | **Parcial** | A04 revisou em 09/11 (3 P1 e 9 P2/P3, todos corrigidos). Falta a A04 reconferir as correções e as mudanças de 12/11. |
| 3 | Nenhuma falha P0 aberta | **Atendido** | Nenhum P0 ou P1 aberto conhecido |
| 4 | Testes de isolamento por instituição e unidade aprovados | Testes passam (local e CI); **falta a aprovação do proprietário** | `test_p0_isolamento_unidade` (32), `test_m2_security` |
| 5 | Permissões dos perfis existentes verificadas | **Atendido no CI**; no computador do proprietário, só na atualização | Passo 1 da homologação: perfil Financeiro sem permissão clínica e estado anterior na auditoria |
| 6 | Atualização a partir da 0.3.1 validada | **Atendido no CI** | Execução 43210699158: migrações aplicadas, backup antes da atualização, dados preservados |
| 7 | Relatório consolidado apresentado | Este documento | — |
| 8 | Autorização expressa para instalar e homologar no Windows | **Pendente** | — |

## 3. O que mudou na segurança

Detalhe em `P0_ISOLAMENTO_UNIDADE.md` e no ADR-0015.

- **Regra única:** papel com a permissão na unidade do objeto, mais vínculo vigente (médico), mais a permissão do recurso. Vale em rotas, consultas SQL, PACS (DICOMweb e DIMSE) e visualizadores (OHIF e Weasis).
- **Exame sem unidade:** restrito a quem atua em todas as unidades.
- **Listas:** filtradas no SQL antes do limite, inclusive críticos e qualidade.
- **Alterações:** toda mudança de médico, prioridade, estado ou informação revalida a unidade.
- **Financeiro:** sem agenda, exames, imagens ou laudos. Perfis existentes são corrigidos na atualização, com registro do estado anterior.
- **Auditoria:** recusas por escopo gravam `access.denied`.
- **Compartilhamento entre unidades:** bloqueado. A exceção está só desenhada.

## 4. Achados e situação

| Origem | Achados | Situação |
|---|---|---|
| A07, bateria escrita antes da correção | 15 de 24 cenários falhavam | Todos passam |
| A04, revisão de 09/11 | N1–N3 (P1), N4–N9 (P2), N10–N12 (P3) | Todos corrigidos; N1–N3, N5, N6 e N10 com teste dedicado |
| Decisões de 12/11 | Paginação, perfis Financeiro | Feitos e testados |

Sem teste dedicado (conferidos só por leitura do código): N4, N7, N8, N9, N11 e N12.

## 5. Riscos e limites conhecidos

1. **Exames antigos sem unidade.** Depois da atualização, usuários restritos a uma unidade não os veem até a vinculação. A simulação somente leitura no computador do proprietário **não foi executada**: o computador não estava acessível em 12/11.
2. **A ferramenta de simulação só existe a partir desta versão.** Na 0.3.1 instalada, a simulação tem de ser feita por leitura pela API, ou depois da atualização.
3. **Equipamentos DICOM sem unidade cadastrada** continuam consultando a instituição inteira, e os exames que enviam entram sem unidade quando há mais de uma.
4. **Tokens do visualizador** não são revogados quando os papéis mudam; são revalidados a cada uso.
5. **Limite de registros `access.denied`:** acima de 20 por minuto por usuário, o excedente é descartado sem registro de resumo.
6. **Frontend:** os botões por exame ainda não refletem a unidade; o backend recusa.
7. **Número da versão:** o sistema ainda se identifica como 0.3.1; muda só na liberação.

## 6. Decisões que dependem do proprietário

1. Aprovar (ou não) os testes de isolamento (critério 4).
2. Deixar o computador acessível para a simulação somente leitura dos 20 exames DEMO.
3. Autorizar a instalação e a homologação da 0.3.2 no Windows (critério 8), depois dos itens acima.
