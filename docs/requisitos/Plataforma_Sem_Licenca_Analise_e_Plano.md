# Plataforma sem licença local, Hardware ID ou ativação — análise de impacto e plano (04/11/2026)

Origem: decisão do proprietário de 04/11/2026 03:35 — "O VYONIX Medical Platform não deverá depender de licença
local, Hardware ID ou ativação para funcionar. Preserve o licenciamento específico do VYONIX DICOM Print, sem
modificá-lo." Estado: **APROVADO pelo proprietário em 04/11/2026 03:43 (4 pontos). L1+L2 implementados (testes locais); L3 e L4 em seguida.**

## Situação atual (levantamento no código)
- `vyonix/licensing/service.py`: licenciamento modular v3 com Installation ID, **Hardware ID**, TPM, cofre selado em
  `ProgramData\VYONIX\Licensing` e registro do Windows — **compartilhado com o DICOM Print** (uma licença v3 instalada
  na plataforma vale também para o Print e vice-versa).
- Pontos que bloqueiam a plataforma sem licença: `require_module`/`module_ok` em 20 lugares — rotas do PACS (3),
  RIS (1), Laudos (1), Administração (6), tarefas do PACS (backup, sincronização, consulta DICOM: 5), monitoração (1),
  ativação de módulos no instalador `vyonix_deploy/modules.py` (2) e a página web "Licença e módulos".
- Instalador de homologação já roda sem licença (variante de compilação `homologacao`), com faixa "sem licença".
- CI 2.9 testa "Ativação do módulo PRINT: direito assinado → … → habilitação" (recusa sem licença).

## Proposta (fases, sem apagar nada)
| Fase | O que muda | O que NÃO muda |
|---|---|---|
| L1 | Módulos da plataforma (PACS, RIS, Laudos, Clínico) funcionam por **configuração** do administrador da clínica; `require_module` passa a conferir só se o módulo está habilitado; tarefas do PACS não param por licença | Banco, dados, auditoria |
| L2 | Sai da web "Licença e módulos"; entra "Sistema e atualizações" (versão, instalação, atualizações, serviços — quadro 12c) | — |
| L3 | Instalador/DEPLOY: ativação de módulos da plataforma sem direito assinado; CI 2.9 reescrito para a nova regra; variante "homologação" deixa de diferir por licença (continua só com a faixa de homologação e dados fictícios) | Pasta `ProgramData\VYONIX\Licensing` e registro **não são apagados nem alterados** (são do DICOM Print) |
| L4 | Código de licenciamento da plataforma fica sem uso (removido depois de uma versão estável); tabelas de licença antigas mantidas, só leitura (sem migração destrutiva) | Licenciamento do **DICOM Print**: intocado (código, cofre, Hardware ID, License Manager dele) |

## Riscos e pontos para o proprietário decidir
1. **Controle comercial**: sem licença, a plataforma não limita usuários, unidades, módulos ou prazo por contrato.
   Confirma que não haverá controle comercial dentro da plataforma (ou será contratual/externo)?
2. **DICOM Print**: hoje uma licença instalada pela plataforma também licencia o Print. Depois da mudança, o Print
   é licenciado só pelo próprio Print (fluxo dele, sem alteração). Confirma?
3. **Instalações existentes**: documentos de licença já instalados ficam guardados (não apagados) e deixam de ser
   exigidos.
4. **Momento**: o instalador 0.2.0 (a58edb6) em validação **não** muda. A mudança entra numa versão seguinte, com CI
   completo (comercial + homologação, incluindo atualização sobre 0.2.0 sem perder dados).

## Inventário de dependências plataforma × DICOM Print (antes de alterar componentes compartilhados)
| Componente compartilhado | Onde fica | Quem usava na plataforma | Situação após L1/L2 |
|---|---|---|---|
| Cofre selado de licenciamento | `ProgramData\VYONIX\Licensing` + registro do Windows | `context.build` montava `Machine` (cofre, TPM, horário confiável) a cada início do Core | **Não é mais montado** pela plataforma; nada lido ou gravado (teste `test_no_licensing_component_and_no_shared_vault_access`) |
| Installation ID / Hardware ID / TPM | cofre + hardware | página e rotas `/license*` | rotas e página retiradas; código guardado sem uso (L4) |
| Horário confiável (TimeIntegrity, processo "core") | cofre | gravado a cada verificação de licença | não é mais gravado pela plataforma |
| Lista de revogação / autorizações (.vyauth) | cofre | rotas de licença | sem uso |
| Pasta `Licensing` e ACLs dos serviços Core/Worker | instalador (`plans.py`) | criação da pasta e permissão de escrita | **mantidas sem alteração** em L1/L2 (são do DICOM Print); revisão em L3 sem remover nada |
| Relatório do DEPLOY (`vyonix_deploy/report.py`) | DEPLOY | lê Installation ID para o relatório | revisão em L3 (somente leitura) |
| Ativação de módulos pelo DEPLOY (`vyonix_deploy/modules.py`) e CI 2.9 | DEPLOY/CI | exigia direito assinado | **L3**: ativação por configuração; 2.9 reescrito |
| Módulo PRINT da plataforma (integração com trabalhos de impressão) | plataforma | exigia licença para habilitar | habilitado por configuração; o licenciamento do produto DICOM Print continua no próprio Print |
| Tabelas `licensing.*` | PostgreSQL | consultadas a cada requisição (cache) | **preservadas**, não consultadas; sem migração destrutiva |

## L1 + L2 — implementado (commit deste registro)
- Removidas as consultas de licença de PACS (rotas e tarefas: sincronização, backup, consulta DICOM/worklist), RIS,
  Laudos, administração (limites de usuários e unidades), monitoração e habilitação de módulos.
- Módulos: habilitar/desabilitar por configuração (`core.modules.manage`); a lista não mostra mais "licença".
- Página web "Licença e módulos" e "Contratar e demonstrar" retiradas; nova **"Sistema e atualizações"**
  (`GET /api/v1/system`, `core.settings.read`): versão, situação e diagnóstico dos serviços, banco de dados, cópias
  de segurança, histórico de atualizações (leitura do DEPLOY), módulos e DICOM Print como produto separado.
- Testes: `test_unlicensed_platform` (4, plataforma montada sem licenciamento: PACS, Viewer, RIS, Laudos/Telelaudos,
  administração, tarefas, monitoração, cofre intocado); ajustados os que dependiam do comportamento antigo
  (`test_api`, `test_core`, `test_monitoring`, `test_e2e_web`). tests_platform 274 OK; tests_deploy OK;
  testes do DICOM Print (`tests/`) OK sem alteração.

## L3 — implementado (testes locais; CI pendente)
- DEPLOY: ativação de módulos sem etapa "direito assinado"; não monta o licenciamento; o identificador da instalação
  nos relatórios do DEPLOY passa a ficar na pasta do DEPLOY (`VYXP-…`), sem ler/gravar o cofre do DICOM Print.
- CI 2.9 reescrito: ativação sem licença + módulo planejado recusado + pasta de licenciamento do DICOM Print
  idêntica antes/depois (SHA-256 de cada arquivo). O 2.8 (Installation ID do DICOM Print preservado) continua.
- Homologação: atualização a partir do instalador 0.2.0 (a58edb6, run 41778895463); passo 4 confere
  `GET /system` (licença não exigida). Versão da plataforma e do DEPLOY: 0.3.0.
- Testes: `tests_deploy/test_unlicensed_deploy.py` (2). Locais: tests_platform 274 OK, tests_deploy OK.
