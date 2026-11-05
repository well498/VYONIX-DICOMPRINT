# A01 — Relatório final (Missão 4, Fase 4)
**O que fiz:** só li o código em /home/claude/vyonix-dicomprint (0.3.1) e as evidências em m4/export (log_testes.tsv, JSON exportado, 01/02). NÃO acessei a instância. Testes locais não rodaram: PostgreSQL de teste em 127.0.0.1:55432 recusou conexão, 0 testes executados. Especificação detalhada: m4/agentes/A01.md.

## 1. 409 intermitente em GET /ris/prep — causa provável (P2)
- `prep.queue` (vyonix/ris/prep.py:507-588) não grava nada. A escrita vem da AUTENTICAÇÃO: `auth.authenticate` renova `AuthSession.expires_at` quando passou mais de 60 s (vyonix/auth/service.py:448-450), dentro de uma sessão que faz commit (vyonix/api/app.py:217-218; vyonix/db/session.py:63-72).
- `AuthSession` herda `row_version` como `version_id_col` (vyonix/db/base.py:46-50; vyonix/auth/models.py:64). O Painel dispara vários GETs paralelos com o mesmo cookie. Dois deles leem a versão N e ambos fazem `UPDATE ... WHERE row_version=N`. O segundo afeta 0 linhas, gera `StaleDataError` e o handler devolve 409 "alterado por outra pessoa" (app.py:122-126).
- Explica a intermitência: só ocorre quando a renovação vence (>60 s) e há requisições simultâneas. Qualquer rota pode ser afetada, não só /ris/prep. Não reproduzido localmente.
- **Correção:** renovar com `UPDATE` condicional sem controle de versão (`update(AuthSession).where(id==…, expires_at < new_exp-60s)`), ou tirar `version_id_col` de `AuthSession`, ou ignorar `StaleDataError` só nesse "touch". Teste: 10 GETs paralelos após 61 s → nenhum 409.

## 2. M4-INST-01: pacs "enabled" sem motor (P1)
- **Evidência real:** auditoria exportada mostra `module.enable` pacs/ris/report com ator **admin** às 07:41 (seq 4-6), 8 min após `organization.create` pelo VYONIX DEPLOY (seq 1). A habilitação veio da tela Sistema (web/src/pages/system.tsx:69, POST /modules/pacs/enable), não do DEPLOY.
- **Código:** `registry.enable` só verifica `available`/dependências (vyonix/modules/registry.py:65-83; rota routes_admin.py:293-297). Não verifica `pacs_orthanc_url`/motor (vyonix/pacs/__init__.py:25). O preparo do motor existe só na ativação pelo DEPLOY (vyonix_deploy/modules.py:160-167: engine_steps + teste `engine_probe` antes de habilitar). O instalador não ativa módulos: `DeployConfig.modules` (vyonix_deploy/config.py:54) não é usado em nenhum plano. O STOW 503 é consequência correta (routes_pacs.py:45).
- Quando o atalho rodou depois, `ModuleEnableStep` já viu o módulo habilitado e só aplicou as etapas do motor.
- **Correção (sem implementar):** (a) no Core, módulos com infraestrutura (pacs) só habilitam com motor configurado e respondendo; senão 409 `infra_required` "Ative pelo VYONIX DEPLOY"; botão substituído por instrução. (b) `/modules` e `/health/detail` mostram "habilitado — motor não configurado" (degradado). (c) Instalador de homologação executa a ativação no fim da instalação ou usa `cfg.modules`. (d) Teste: instalação nova + POST enable pacs sem motor → 409.

## 3. Conclusões arquiteturais (com evidência real)
- **Edge = 1 instituição** (login na org padrão, routes_auth.py:56-60; /platform só operadora/cloud). Hospital Modelo, Rede Estadual, Regiões e setores: NÃO IMPLEMENTADO no edge.
- **Estudos sem unidade (P1, F1):** todos os 19 estudos DEMO com `site_id=null` (02_stow.md). A conciliação não herda a unidade do pedido/atendimento (vyonix/clinical/service.py:373-401; Order sem `site_id`, só `encounter_id`, clinical/models.py:53-58). A fila inclui estudos sem unidade para quem tem papel restrito (prep.py:514-515), por isso o técnico da Satélite atribuiu exames da Matriz (T-RIS-C2-*). O isolamento por unidade é ineficaz para imagens.
- PUT /settings substitui o valor inteiro (campos omitidos voltam ao padrão) (P2). Unidades sem DELETE (P3). Texto de limite por licença obsoleto (sites.tsx:18) (P3).

## 4. Recomendações priorizadas
1. **P1:** propagar a unidade na conciliação (encounter.site_id → study.site_id) e decidir a política para estudos sem unidade (não visíveis a papéis restritos, ou fila "sem unidade" só global).
2. **P1:** impedir habilitar pacs sem motor (item 2) e incluir o caso no teste de instalação limpa.
3. **P2:** corrigir a renovação de sessão (item 1); o front-end pode repetir GET em 409 como mitigação.
4. **P2:** PUT de configurações com fusão parcial, ou documentar substituição total.
5. **P3:** multi-instituição só validável em cloud de teste; ajustar textos e catálogo (viewer "planejado").
