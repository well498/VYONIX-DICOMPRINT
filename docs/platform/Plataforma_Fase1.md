# VYONIX Platform — Fase 1 (Core)

Estado: **em desenvolvimento**. Não declarado pronto para uso clínico nem homologado. Nenhuma
conformidade regulatória é declarada por este documento.

## 1. O que a Fase 1 entrega

| Etapa | Entrega | Onde |
|---|---|---|
| 1.1 | Monorepo (Print intacto), CI da plataforma com PostgreSQL 17 real, teste de arquitetura | `.github/workflows/platform.yml`, `tests_platform/` |
| 1.2 | Banco, organizações, unidades, isolamento por clínica (row level security forçado) | `vyonix/db`, `vyonix/tenancy` |
| 1.3 | Usuários, papéis por unidade, permissões, sessões, MFA TOTP, bloqueio | `vyonix/auth` |
| 1.4 | Auditoria encadeada (SHA-256) e imutável | `vyonix/audit` |
| 1.5 | Configurações por módulo com esquema e histórico | `vyonix/settings` |
| 1.6 | Outbox/inbox transacional e processador de eventos | `vyonix/events` |
| 1.7 | Registro de módulos (manifestos, dependências, licença) | `vyonix/modules` |
| 1.8 | Cadastro clínico comum, mescla reversível, conciliação | `vyonix/clinical` |
| 1.9 | Licença v3 por módulo, demonstrações assinadas, compatibilidade v2 | `vyonix/licensing`, `vyonix_protocol`, License Manager |
| 1.10 | API HTTPS e interface web (React + TypeScript) com testes no Chromium | `vyonix/api`, `web/` |

O pacote Python chama-se `vyonix` (o nome `platform` colide com a biblioteca padrão).

## 2. Executar (servidor EDGE)

Requisitos: Python 3.12+, PostgreSQL 17, Node 22 (somente para compilar a interface).

```
pip install -r requirements-platform.txt
cd web && npm install && npm run build && cd ..
set VYONIX_ADMIN_PASSWORD=...            (ou digite quando pedido)
python -m vyonix init --admin-url postgresql://postgres@127.0.0.1:5432/postgres --org minha-clinica --org-name "Minha Clínica"
python -m vyonix serve                    (HTTPS na porta 8444; certificado próprio ou autoassinado gerado)
python -m vyonix worker                   (processador de eventos, em outro processo)
python -m vyonix migrate                  (após atualizar a versão)
python -m vyonix status
```

`init` usa a URL de administrador do PostgreSQL só durante a execução (não é gravada). As senhas dos
três papéis do banco são aleatórias e ficam protegidas por `vyonix.secrets` (DPAPI de máquina no
Windows; arquivo com permissão restrita nos demais). `config.json` só contém referências
`{secret:...}`.

Empacotamento PyInstaller e instalador (DEPLOY) não fazem parte da Fase 1.

## 3. Segurança implementada

- **Banco:** papéis `<prefixo>_owner` (migrações), `_app` (API; não é dono das tabelas; RLS forçado),
  `_service` (processador; sem DDL). Todas as 24 tabelas com `tenant_id` têm `FORCE ROW LEVEL
  SECURITY`; sem clínica definida na transação nada é visível nem gravável. Os consumidores de eventos
  rodam com o papel da aplicação no tenant do evento.
- **Acesso:** scrypt; mensagem única para usuário inexistente/senha errada/bloqueio; bloqueio após N
  erros (padrão 5 / 15 min, configurável); limite de tentativas por IP; sessão em cookie `HttpOnly`,
  `Secure`, `SameSite=Strict`, expiração deslizante; token anti-CSRF por sessão; troca de senha
  obrigatória no primeiro acesso; MFA TOTP (RFC 6238) com segredo cifrado (AES-GCM), proteção contra
  reuso do código e 10 códigos de recuperação de uso único; a clínica sempre mantém um administrador.
- **Auditoria:** encadeada por clínica com bloqueio consultivo; `UPDATE/DELETE/TRUNCATE` revogados do
  papel da aplicação e bloqueados por gatilho para os demais; verificação aponta registros alterados.
- **HTTP:** CSP `'self'`, `X-Frame-Options: DENY`, `nosniff`, sem referrer, `no-store` na API, HSTS em
  HTTPS; erros estruturados sem pilha.
- **Eventos** levam apenas identificadores internos (nenhum nome, documento ou dado clínico).

## 4. Licenciamento modular (licença v3)

A licença v3 é o mesmo documento assinado `vyonix-license` com `"schema": 3` e o mapa `modules`. Os
campos legados (tipo, vencimento, recursos, política comercial) continuam valendo para o DICOM Print e
descrevem o **contrato**. O módulo PRINT é sempre derivado dos recursos da licença.

| Item | Regra |
|---|---|
| `kind: contract` | O módulo segue o contrato (assinatura ou permanente): período pago, carência, suspensão e reativação vêm das autorizações de uso (online ou `.vyauth`) — mesmo cálculo do License Server. |
| `kind: demo` | Demonstração própria do módulo: 5, 15, 30 dias ou prazo personalizado (1–90), contada da primeira aplicação; deve ser aplicada até `activate_by` (30 dias da emissão). |
| Prorrogação | Nova licença com o mesmo `grant_id` e mais dias: conta da ativação original. |
| Conversão | O módulo passa a `contract` (License Manager → Licenças → **Módulos…**). |
| Limites | Core: `users`, `sites` (conferidos ao criar/reativar). PRINT: equipamentos e impressoras, aplicados pelo próprio Print. |
| Licença v2 | Continua aceita: Core e PRINT seguem o contrato da licença. |
| Sem licença | Core funciona com até 3 usuários e 1 unidade, para permitir instalar a licença. |

**Identidade compartilhada:** o Core usa o mesmo cofre selado, Installation ID, Hardware ID, Time
Integrity e lista de revogação do DICOM Print no mesmo servidor. Uma licença v3 instalada vale para os
dois (o Print aceita v3 — coberto por teste).

**Demonstração pelo painel comercial:** *Contratar e demonstrar* gera um pedido (`VYXR2-…` /
`.vyreq`) com módulos, prazo desejado e contato. Nada é concedido pelo servidor da clínica: o
fornecedor importa o pedido no License Manager (campos pré-preenchidos), emite a licença assinada e a
clínica a aplica em *Licença e módulos*. O License Manager recusa uma segunda demonstração do mesmo
módulo para o mesmo computador sem justificativa registrada.

**Suspensão comercial** desabilita as funções licenciadas do módulo; nunca apaga dados nem bloqueia a
consulta do cadastro clínico (o módulo clínico não exige licença).

**Limites honestos:** nenhuma proteção offline é absoluta. Uma restauração completa do disco (cofre,
registro e banco juntos) a um estado anterior não pode ser detectada só pelo computador; a validação
online reduz esse risco. O licenciamento do modo CLOUD (por organização, sem vínculo com um servidor)
ainda não está disponível: o Core em modo `cloud` recusa licenças com mensagem explícita.

## 5. API (prefixo `/api/v1`)

Acesso: `auth/login`, `auth/logout`, `auth/me`, `auth/password`, `auth/mfa/{enroll,confirm,verify}`.
Administração: `users` (+ `roles`, `reset-password`, `unlock`, `mfa`), `roles`, `permissions`,
`organization`, `sites`, `settings/{módulo}/{chave}` (+ `history`), `modules/{código}/{enable,disable}`,
`audit`, `audit/verify`. Licença: `license`, `license/request`, `license/install`,
`license/authorization`, `license/check-online`. Clínico: `patients` (+ `identifiers`),
`patients/merge`, `merges/{id}/undo`, `procedures`, `orders` (+ `status`), `studies` (+ `reconcile`).
Saúde: `health`.

Erros: `{"error": código, "message": texto, "details": {...}}` — 401 sessão, 402 sem licença do
módulo, 403 permissão/CSRF/etapa pendente, 404, 409 conflito (inclusive edição concorrente), 422
validação, 423 bloqueio.

## 6. Testes

`python -m pytest tests_platform` com `VYONIX_TEST_ADMIN_URL` apontando para um PostgreSQL de teste
(um banco e papéis temporários são criados e removidos). Sem a variável os testes são **pulados com
motivo** — o CI falha se algum teste for pulado. A interface precisa estar compilada (`web/dist`) para
os testes no Chromium. Capturas de tela: `VYONIX_E2E_SHOTS=pasta`.

Conjuntos: arquitetura (dependências entre pacotes, nenhuma assinatura/chave privada na plataforma,
toda tabela com tenant protegida por RLS), fundação (RLS, auditoria, acesso, MFA, configurações,
módulos, eventos concorrentes), clínico (mescla e desfazer, conciliação, concorrência otimista,
eventos sem dados pessoais), licenciamento (License Manager real emitindo; demonstração, prorrogação,
conversão, prazo de ativação, reinstalação do banco, recusas, limites, suspensão comercial com dados
preservados, Print aceitando v3), API (cookie, CSRF, papéis, limites, fluxo de licença) e ponta a
ponta no navegador (administrador, técnico e recepcionista).
