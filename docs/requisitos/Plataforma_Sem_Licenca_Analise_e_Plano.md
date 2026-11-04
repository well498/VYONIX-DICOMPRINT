# Plataforma sem licença local, Hardware ID ou ativação — análise de impacto e plano (04/11/2026)

Origem: decisão do proprietário de 04/11/2026 03:35 — "O VYONIX Medical Platform não deverá depender de licença
local, Hardware ID ou ativação para funcionar. Preserve o licenciamento específico do VYONIX DICOM Print, sem
modificá-lo." Estado: **ANÁLISE — implementação aguardando aprovação do plano** (mudança de arquitetura que afeta o
instalador em homologação).

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
