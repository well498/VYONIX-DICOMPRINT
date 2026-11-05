# MISSÃO 3 — Cloud First, Gateway DICOM, Multiunidades (05/11/2026)

**Situação:** etapa de análise concluída pelos 8 agentes; **nada implementado, nada contratado**. Proposta consolidada
(documento compartilhável): https://claude.ai/artifact/Hr9bWjmCRfLk4wY8STBezu — aguardando decisões D1–D9 do proprietário.

* Relatórios resumidos (fiéis) dos agentes: `Relatorio_A0x.md`; estudo J4Care: `Estudo_J4Care.md`.
* Rascunhos de migrações aditivas (NÃO aplicados ao código; provados em banco descartável, 28/28 verificações):
  `migracoes_rascunho/` (core_0005 regiões/gateways, core_0006 escopo por região + HMAC da auditoria, pacs_0011 origem
  do estudo + recibos/manifestos) e a fila local do Gateway (`gateway_queue.sql`). Antes de entrar em
  `vyonix/db/migrations/versions/` precisam de aprovação (D1/D3/D5) e revisão — a numeração será ajustada.
* Estimativa de custos AWS: `estimativa_custos_aws.py` (premissas no código; preços de lista sa-east-1 consultados em
  05/11/2026; itens não confirmados marcados como estimativa).
* Protótipos A05 (17 telas, HTML + PNG): entregues ao proprietário; não versionados por serem material de discussão.

## Decisões pendentes (D1–D9)
D1 arquitetura (Gateway próprio + central VYONIX, motor trocável) · D2 BLK-16 só em testes · D3 perfil/instalador
Gateway + fila SQLite · D4 AWS sa-east-1 e conta de laboratório (nada contratado sem autorização) · D5 armazenamento por
instituição (S3 + KMS) · D6 banco único RLS × instância dedicada · D7 retenção/exclusão local · D8 pareceres jurídicos
(LGPD, GPLv3 Orthanc, MPL dcm4chee) · D9 perguntas dos protótipos.

## Fase 0 (P1, vale já para a versão atual — aguarda aprovação de início)
Unidade gravada na entrada do exame; emissor do identificador do paciente por unidade; escopo de imagens e de
`report.production.all` pela unidade do papel; privilégios explícitos (REVOKE) em toda tabela nova.
