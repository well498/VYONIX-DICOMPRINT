# MISSÃO 2 — Auditoria integral de segurança do VYONIX Medical Platform (0.3.0 → 0.3.1)

Data: 04/11/2026 · Prioridade: P0 · Base auditada: `develop` 726ff0b (0.3.0) · Correções: ramo `m2-seguranca`
(02771ae, d325a6c, def985e, d7ed073 e seguintes), versão **0.3.1**.

> **Limites desta auditoria.** Nenhum sistema é invulnerável. Testes aprovados **não** equivalem a certificação de
> segurança nem a conformidade regulatória (LGPD, CFM, ANVISA). Tudo o que está marcado "validado" foi validado em
> **ambiente local Linux** (PostgreSQL de testes, dados sintéticos) e, quando indicado, em CI Windows; **nada** foi
> executado no computador do proprietário. O P0 só fecha com a confirmação do proprietário no Windows.

## A. Resumo executivo

* Seis especialistas (A01, A02, A03, A04, A06, A08) auditaram a plataforma em paralelo, somente leitura, com provas
  executadas localmente; A05 analisou a UX de segurança; A07 validou as correções de forma independente (duas
  rodadas).
* **Achados graves comprovados na 0.3.0** (alta/P1): (1) **qualquer médico da mesma unidade editava, liberava
  (assinando em seu nome) e adendava o laudo de outro médico** e podia iniciar o laudo de exame atribuído a outro;
  (2) **administrador de uma unidade se promovia a administrador da instituição** e redefinia a senha do
  administrador principal; (3) **papéis por unidade alcançavam outras unidades** (técnico abria exames, administrador
  de unidade alterava configurações e lia a auditoria, vinculava médicos a outras unidades, mudava prazos e o PACS).
* **Todos esses foram corrigidos na 0.3.1**, com testes que demonstram a recusa (13 testes em
  `tests_platform/test_m2_security.py`; 9 deles falham na 0.3.0 — evidência da falha original) e revalidação
  independente do A07.
* Autenticação, armazenamento de senhas (scrypt), cookies de sessão, CSRF (106 rotas), isolamento entre
  instituições (RLS forçado, 60 políticas), SQL parametrizado e ausência de segredos reais no histórico Git
  **resistiram** aos testes.
* **Recomendação de liberação:** a **0.3.0 não deve ser usada** além de testes (contém as falhas acima). A **0.3.1**
  pode seguir para a **homologação pelo proprietário** — não para produção com dados reais — até que as decisões da
  seção G (firewall, recepção DICOM, MFA obrigatório para administradores, backup cifrado, credenciais do Core) sejam
  tomadas e as P1 residuais tratadas.

## B. Tabela de vulnerabilidades

Severidade: Alta/P1 · Média/P2 · Baixa/P3. Estado: **Corrigida** (código + teste + revisão independente),
**Mitigada** (parcial), **Aberta** (backlog), **Decisão** (depende do proprietário).

| ID | Sev. | Componente | Descrição | Evidência (original) | Correção | Teste | Estado |
|---|---|---|---|---|---|---|---|
| R-01 | Alta | Laudos | Médico não responsável edita, envia para revisão, libera (inclusive em lote), adenda e lê o rascunho de outro | A03 test_r01/r09 (PUT 200, FINALIZE 200 em nome de outro) | `report/authorship.py`; `_author` em todas as rotas de escrita | test_r01 | Corrigida |
| R-02 | Alta | Laudos | Médico inicia o laudo de exame atribuído a outro; registro de início com responsável falso | A03 test_r02 (201) | `authorship.check_open` sob a trava do exame | test_r02 | Corrigida |
| S-01 | Alta | Usuários/papéis | Delegação comparava só nomes de permissões: admin de unidade vira global e redefine senha do admin principal | A04 prova_auth (200/200) | `check_grant` por par (permissão, unidade); proibido alterar os próprios papéis | test_s01 | Corrigida |
| S-02 | Alta | Autorização | Papel de unidade alcançava outras unidades e a instituição (estudos, preparação, configurações, auditoria) | A04 prova_unidade (200) | `needs_global`, `_site`, filtros por `sites_for` | test_s02, test_r04 | Corrigida |
| V-01 | Alta | Autorização | (revalidação) admin de unidade vinculava médico a outra unidade, mudava prazos de todas e cadastrava nós PACS | A07 proofs_i (201/200/201) | `needs_global`/`require_global` em pacs.admin, physicians, sla, branding, templates, procedimentos | test_v01_v02 | Corrigida |
| R-03 | Média | RIS | Médico devolve para correção exame de outro (troca indireta de médico) | A03 test_r03 | `_return_allowed` | test_r03 | Corrigida |
| R-04 | Média | RIS | Técnico de uma unidade agia em exame de outra (check/anexo/encaminhar/cancelar/compartilhar) | A03 test_r04 | `_site` em todas as rotas `/ris/prep/*` | test_r04 | Corrigida (exame sem unidade: ver V-03) |
| R-05 | Média | RIS/Clínico | Conciliação mudava a prioridade efetiva depois do início do laudo | A03 test_r07 | prioridade congelada em `report_starts`; efeito auditado | test_r05 | Corrigida |
| V-02 | Média | Laudos | Coordenação/quem distribui de uma unidade via fila e críticos de outra | A07 | `_scope` por unidades do papel | test_v01_v02 | Corrigida |
| V-03 | Média | Escopo | Regressão da 1ª correção: estudos do PACS chegam sem unidade e papéis por unidade ficavam sem acesso | A07 | exame sem unidade = alcançado por papel de qualquer unidade | test_r04 | Mitigada (atribuir unidade na entrada: backlog) |
| S-03 | Média | Autenticação | MFA de administradores desligado por padrão; `admin_vyonix` fora da regra; sem reautenticação em operações administrativas | A04 | — | — | **Decisão** (G-3) |
| S-04 | Média | Weasis | Credenciais do visualizador sobreviviam a saída, troca/redefinição de senha, papéis, bloqueio e remoção do MFA | A04/A02 D-07, A07 V-06 | `_revoke_viewer` | test_s04 | Corrigida |
| D-01 | Média | DICOM Q/R | Nó sem IP é autenticado só pelo AE Title (consulta, worklist, MPPS) | A02 D01 | — | — | Aberta (P1 backlog) |
| D-02 | Média | DICOM Store | Orthanc aceita C-STORE de qualquer equipamento; política `any` | A02 D02 | — | — | **Decisão** (BLK-15, G-2) |
| D-03 | Média | Nuvem | Modo nuvem roteia só pelo AE chamado | A02 D03 | — | — | Aberta (modo nuvem não instalado) |
| D-04/W-06 | Média | Firewall | Regras sem restrição de origem nos perfis Domínio/Privado | A02/A06 (código) | — | — | **Decisão** (G-1) |
| A1-01 | Média | Arquitetura | Core exposto à rede guarda credenciais `owner` e `service` (ignoram RLS) | A01 | — | — | **Decisão** (G-5) |
| B-01 | Média | Logs | Parâmetros SQL (nome de paciente) no log da aplicação em erro de banco | A08 leak.py | `hide_parameters=True` | revisão A07 | Corrigida |
| B-02 | Média | PostgreSQL | Valores das consultas lentas no Log de Eventos | A08 | `log_parameter_max_length=0` (+on_error) | — (Windows) | Corrigida (validar no Windows) |
| W-04 | Média | Logs | Busca de paciente (`?q=`) no log de acesso | A06 | filtro `_NoQuery` | https_probe A07 | Corrigida |
| B-03/W-05 | Média | Backup | Dumps e backup do PACS sem criptografia; `secrets.json` preso à máquina | A08/A06 | — | — | **Decisão** (G-4) |
| W-01 | Média | TLS | TLS 1.2 negociava CBC/SHA-1; lista incluía NULL/anônimas | A06 | `ssl_ciphers` ECDHE+AEAD, mínimo TLS 1.2 | https_probe A07 | Corrigida |
| W-02 | Média | TLS | Certificado autoassinado sem IP da rede no SAN | A06 | — | — | Aberta (estratégia na seção H) |
| W-03/B-06 | Média | Instalador | Segredos gravados antes das ACLs das pastas | A06/A08 (código) | — | — | Aberta (P1, exige teste Windows) |
| W-07 | Média | Docs | Repositório público com senhas de exemplo no roteiro | A06 | roteiros sem senhas | — | Corrigida |
| W-08 | Média | Supply chain | ZIP do PostgreSQL sem SHA fixado; dependências sem hashes; sem lockfile npm | A06 | — | — | Aberta |
| R-06/V-04 | Baixa | Concorrência | Liberação/salvamento simultâneos davam 500 | A03/A07 | `StaleDataError`/`IntegrityError` → 409 | revisão A07 | Corrigida |
| R-07 | Baixa | Laudos | `row_version` opcional (sobrescrita silenciosa) | A03 test_r06 | obrigatório em salvar/revisão/liberar | test_r07 | Corrigida (lote: V-08 aberta) |
| D-06 | Baixa | PACS | WADO série/instância/frames sem trilha | A02 | `open_study` | — | Corrigida |
| S-06 | Baixa | Login | Limite de tentativas respondia 400 | A04 | 429 + `Retry-After` | test_s06 | Corrigida |
| S-10 | Baixa | Cabeçalhos | Sem Permissions-Policy, COOP, CORP | A04 | adicionados | — | Corrigida |
| W-09/V-07 | Baixa | HTTPS | Conexão parcial ficava aberta (40–60 s) | A06/A07 | 10 s para decidir e para o handshake | https_probe A07 | Mitigada (pós-TLS e `redirect=False`: aberta) |
| B-04 | Baixa | Banco | App podia alterar `platform.alembic_version` | A08 | migração `core_0004` (REVOKE) | test_b04 | Corrigida |
| B-08 | Baixa | Banco | Curingas `%`/`_` não escapados em buscas (sem injeção) | A08 | escape na fila de preparação | — | Mitigada (auditoria, RIS: aberta) |
| V-05 | Baixa | Usuários | Admin de unidade assumia conta sem papel | A07 | só admin de todas as unidades | test_v05 | Corrigida |
| S-05 | Baixa | Sessão | Sem expiração absoluta; token não renovado após MFA | A04 | — | — | Aberta |
| S-07 | Baixa | Auditoria | 403/CSRF não auditados; login inexistente grava o texto digitado | A04 | — | — | Aberta |
| S-08 | Baixa | STOW | Corpo inteiro em memória (até 1 GB) | A04 (potencial) | — | — | Aberta |
| S-09 | Baixa | Segredos | DPAPI de máquina sem entropia | A04 (potencial) | — | — | Aberta |
| S-11 | Baixa | Nuvem | `login-available` revela logins de outras instituições | A04 | — | — | Aberta |
| D-05,D-08,D-09 | Baixa | PACS | AE reservado em rota cloud; Storage Commitment sem limite; sem TLS DICOM/ATNA | A02 | — | — | Aberta |
| B-05,B-07 | Baixa | Banco | FKs sem tenant; cadeia de auditoria sem chave | A08 | — | — | Aberta |
| R-08,R-09 | Baixa | Auditoria/papéis | Lacunas de auditoria (cancelar, prazo, compartilhamento); médico gerencia modelos da instituição | A03 | — | — | Aberta |
| V-08,V-09 | Baixa | Laudos | Lote sem `row_version`; não responsável comunica achado crítico | A07 | — | — | Aberta (V-09 possivelmente intencional) |
| A1-07, W-10..W-12 | Baixa | Infra | `/health` mostra versão; logs sem ACL própria; serviços sem redução de privilégios | A01/A06 | — | — | Aberta |

## C. Correções aplicadas (0.3.1)

* **Autoria e responsabilidade do laudo** (`vyonix/report/authorship.py`): responsável = quem iniciou
  (`report_starts.physician_id`, imutável) ou, antes, a atribuição/reserva aberta. Exceções explícitas: revisor
  designado e compartilhamento temporário `report`. A interface recebe `can_write` e abre o editor só leitura para
  os demais; "Iniciar laudo" desabilitado em exame de outro médico.
* **Escopo por unidade:** `needs_global`/`Ctx.require_global` para ações da instituição; `_site` nas rotas de
  preparação; filtros por `sites_for` em estudos e filas; exame sem unidade alcançado por papel de qualquer unidade
  (V-03; os estudos do PACS ainda entram sem unidade).
* **Delegação:** `check_grant` por (permissão, unidade); ninguém altera os próprios papéis; conta sem papel só pelo
  administrador de todas as unidades.
* **Regras aprovadas preservadas:** exclusividade do Técnico em Radiologia e bloqueio de médico/prioridade após o
  início do laudo (testes `test_report_start_lock`, `test_ris_technician` aprovados; prioridade agora também
  congelada na conciliação).
* **Concorrência:** `row_version` obrigatório; conflitos → 409.
* **Visualizador externo:** revogação em todos os eventos de credencial.
* **Logs:** sem parâmetros SQL, sem valores no PostgreSQL, sem query string no acesso.
* **HTTPS:** TLS ≥ 1.2, ECDHE+AEAD, 10 s para decidir/handshake; Permissions-Policy, COOP, CORP; 429 no login.
* **Banco:** `core_0004` (aditiva) revoga escrita do app/serviço na versão das migrações.
* **VYONIX DICOM Print:** não modificado.

## D. Testes

| Grupo | Aprovados | Reprovados | Não executados / manuais |
|---|---|---|---|
| `tests_platform` (local) | 291 (3 pulados) | 0 | — |
| `test_m2_security` (proteção) | 13 | 0 (9 reprovam em 726ff0b, como esperado) | — |
| `tests_deploy` (local) | 67 | 0 | — |
| `tests` DICOM Print (local) | 337 (26 pulados) | 0 | — |
| Provas A07 (autoria, unidade, delegação, bloqueio, R-05/R-07, Weasis, HTTPS, corrida de liberação) | ver relatório A07 | V-01..V-07 → corrigidos e revalidados | Windows, `/pacs/*` entre unidades |
| CI Windows (comercial/homologação) | a preencher após a execução | — | — |
| Proprietário (Windows) | — | — | **Roteiro `docs/homologacao/Roteiro_Homologacao_Windows_0.3.md`** |

Os 15 testes obrigatórios da missão (A07) — situação: autenticação ✔, recuperação de senha (não existe fluxo
self-service; redefinição pelo administrador ✔ e restrita por unidade ✔), sessões ✔, CSRF ✔ (106 rotas), XSS ✔
(sanitização do laudo), SQLi ✔ (sem SQL dinâmico alcançável), autorização por recurso ✔ (após correções),
isolamento entre instituições ✔ e entre unidades ✔ (após correções), rate limiting ✔ (429), uploads (anexos,
DOCX ✔; STOW em memória: S-08 aberto), concorrência ✔ (409), permissões administrativas ✔ (após V-01), PACS
(isolamento pela API ✔; DICOM por AE: D-01/D-02 abertos), preservação de dados (CI de atualização por cima da 0.2.0
— a repetir na 0.3.1), regressão clínica ✔ (suítes completas).

## E. Agentes e evidências

| Agente | Papel na missão | Situação | Evidência |
|---|---|---|---|
| A01 Arquiteto | Superfície, fronteiras, modelo de ameaças | EXECUTADO | relatório (10 achados) |
| A02 PACS/DICOM | Q/R, Store, cloud, Weasis, TLS DICOM | EXECUTADO, provas | `test_m2_provas.py`, 28 testes PACS OK |
| A03 RIS/Telelaudos | Fluxos clínicos, autoria, concorrência | EXECUTADO, provas | `test_m2_proofs.py` (9 provas) |
| A04 Segurança/LGPD (líder) | Autenticação, sessões, autorização, segredos | EXECUTADO, provas | `a04/prova_*.py` |
| A05 UX/UI | UX de segurança e protótipo | EXECUTADO | `a05/Prototipo_Seguranca_UX.html` (não implementado) |
| A06 Windows/DevOps | TLS, firewall, CI, backup; roteiro Windows | EXECUTADO, teste local TLS | roteiro salvo |
| A07 QA | Validação independente (2 rodadas) | EXECUTADO, VALIDADO | `a07/test_a07_m2.py`, `https_probe.py` |
| A08 Banco | SQL, papéis, RLS, logs, backup | EXECUTADO, provas | `prov.py`, `rls.py`, `leak.py` |

Provas e relatórios ficam no scratchpad da sessão (não versionados, por conterem saídas de execução); os resumos
fiéis estão em `scratchpad/agentes/m2/relatorios/`.

## F. Modelo de ameaças (consolidado)

| Atacante | Vetores principais | Controles | Risco residual |
|---|---|---|---|
| Não autenticado (rede local) | login, `/health`, DICOM 4242/4243, TLS | mensagem e tempo únicos, bloqueio, 429, CSRF, TLS forte | Médio: C-STORE aberto (D-02), AE sem IP (D-01), firewall sem origem (D-04) |
| Autenticado sem privilégio | rotas por ID | `needs` + escopo + autoria | Baixo |
| Outra instituição | IDs, sessão forjada | RLS forçado, sessão por tenant | Baixo (web); médio no DICOM em nuvem (D-03) |
| Médico em estudo não autorizado | troca de IDs, laudo alheio | vínculos, autoria (R-01/R-02) | Médio: imagens com escopo `organization` por padrão (A1-03) |
| Admin institucional excedendo | papéis, unidades, configurações | delegação por unidade, `needs_global` | Médio: MFA opcional (S-03); admin `*` inclui dados clínicos (A1-04) |
| Equipamento DICOM desconhecido | C-STORE, C-FIND, MPPS | Q/R recusa AE desconhecido; Orthanc sem FIND/MOVE | Médio (D-01/D-02) |
| Credenciais comprometidas | sessão, Weasis | revogação, expiração ociosa | Médio: sem MFA obrigatório; sem expiração absoluta (S-05) |
| Serviço interno comprometido | Core, Worker | contas virtuais, ACLs | Alto impacto: Core tem `owner`/`service` (A1-01) |
| Atacante na rede | interceptação, conexões lentas | TLS 1.2+ AEAD, timeouts | Médio: certificado autoassinado (W-02); DICOM sem TLS |

## G. Decisões do proprietário (não executadas — alteram serviços ativos/instalação)

1. **Firewall** (D-04/W-06): limitar 8444/4242/4243 à sub-rede local (ou às origens informadas). Risco: estações de
   outra sub-rede/VPN perdem acesso.
2. **Recepção DICOM** (D-02, BLK-15): recusar equipamentos não cadastrados na associação e exigir IP nos nós.
3. **MFA obrigatório** para administradores e `admin_vyonix`; reautenticação ao conceder papel em todas as unidades
   (A05 P1).
4. **Backup cifrado** com chave de recuperação guardada fora do servidor.
5. **Credenciais do Core**: retirar `owner` do serviço e substituir o uso de `service` no login por função restrita.
6. **Interface de usuários** (A05 P1): papel novo sem unidade pré-escolhida e confirmação para "todas as unidades".
7. **Unidade dos exames do PACS** (V-03): mapear AE/estação → unidade na entrada, para fechar o escopo por unidade.

## H. Homologação e backlog priorizado

**Homologação:** CI (a executar na 0.3.1) × local (concluída) × proprietário (pendente, roteiro
`docs/homologacao/Roteiro_Homologacao_Windows_0.3.md`). **Estratégia de certificado (A06):** IP fixo + nome DNS
interno; CA da instituição (AD CS ou CA raiz pequena com chave **fora** do servidor); certificado do servidor com
FQDN e IP no SAN, validade ≤ 397 dias, instalado pelo `.pfx` que o DEPLOY já aceita; distribuir só a raiz (GPO,
`certutil -addstore Root`, perfil no celular). Não desativar validação de certificados.

**Backlog (Missão 2 + pendências da Missão 1):**

| Pri | Item |
|---|---|
| P0 | Validação do proprietário no Windows (0.3.1) |
| P1 | Decisões G-1..G-7; D-01 (IP obrigatório para nós de consulta/envio); W-03/B-06 (ACL antes dos segredos); S-03 |
| P1 | Teste de interface do técnico para troca de médico/prioridade (pendência M1); teste de concorrência com Barrier (parcialmente coberto pela corrida de liberação do A07) |
| P2 | W-02 certificado com IP/CA; W-08 hashes e lockfile; B-03 backup cifrado; S-05; S-07; S-08; residuais de leitura `/patients`, `/orders`, `/users` por unidade; A05 P2 |
| P2 | Comparação completa da estrutura de licenciamento do DICOM Print no critério 2.13; investigar falha intermitente do teste do Print (M1) |
| P3 | Limpeza final do código de licença obsoleto (L4); mensagens de módulo desativado (`NotLicensed`/402 → "módulo desativado"); V-08; V-09; B-05; B-07; B-08 restantes; D-05/D-08/D-09; A1-07; W-09 residual; W-10..W-12; R-08/R-09 |
