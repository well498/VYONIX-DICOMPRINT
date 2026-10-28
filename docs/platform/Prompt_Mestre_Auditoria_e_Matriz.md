# Prompt Mestre (28/10/2026) — Auditoria do código e matriz de funcionalidades

Documento de referência: "PROMPT MESTRE — Licenciamento Centralizado, Administração Multi-Institucional,
Autenticação, Perfis Dinâmicos e Integração dos Módulos" (anexo do proprietário, 28/10/2026, 14h29).
Auditoria feita sobre a `develop` em `111fee9` (código, migrações, testes e documentação).

Legenda: **Existe** = implementado e coberto por testes executados; **Parcial** = parte implementada (o que falta
está dito); **Falta** = não implementado. Nada aqui é validação para uso clínico.

## 1. O que já existe (base para reutilizar, não reconstruir)

| Componente | Onde | Testes |
|---|---|---|
| Organizações (instituições) isoladas por RLS no PostgreSQL, unidades, usuários, papéis com permissões, papéis personalizados, vários papéis por usuário (por organização ou por unidade), auditoria encadeada, configurações versionadas | `vyonix/tenancy`, `vyonix/auth`, `vyonix/audit`, `vyonix/settings` | `tests_platform/test_core.py`, `test_tenant_isolation`, `test_architecture` |
| Senhas com scrypt e sal aleatório (hash), senha provisória com troca obrigatória, bloqueio por tentativas, sessões com expiração e revogação, CSRF, MFA (TOTP) opcional/obrigatório, confirmação de senha no ato | `vyonix/auth/service.py`, `passwords.py`, `totp.py` | `test_core.py`, e2e `test_1` |
| Licença modular v3 da plataforma (somente verificação; emissão no License Manager), estados comerciais por módulo, suspensão sem apagar dados, leitura sem licença vigente | `vyonix/licensing`, `vyonix_commercial` | `test_licensing.py` |
| DICOM Print: licença offline (Hardware ID, Installation ID, TPM, Ed25519, Time Integrity, DEMO), assinatura comercial com autorização **online** (License Server, número de uso único, tolerância) e **offline** (`.vyauth`) | `app/licensing/*`, `license_server/`, `license_manager/` | `tests/` (Print, r5) |
| License Manager independente (emissão offline, contratos, cobrança) e License Server (autorizações online, cobrança Banco Inter) | `license_manager/`, `license_server/` | `tests/test_license_manager_ui.py`, selftest |
| PACS (STOW/QIDO/WADO, C-STORE, C-FIND/C-MOVE/C-GET, MWL/MPPS, backup, integridade, retenção-relatório), Viewer OHIF, RIS (agenda, salas, MWL, MPPS, Central de exames), REPORT/Telelaudo T1–T8 + assinatura manuscrita | `vyonix/pacs`, `vyonix/ris`, `vyonix/report`, `viewer/` | platform 186 local; viewer CI; e2e 8/8 |
| Fila de telelaudo: escopo do médico por unidade com vínculo vigente, atribuição manual com prioridade e prazo, reatribuição, liberação conclui | `vyonix/report/queue.py` | `test_report_queue.py` |
| Início com pendências por papel | `web/src/pages/dashboard.tsx` | e2e |

## 2. Matriz por seção do Prompt Mestre

| § | Requisito | Situação | Observação / o que falta |
|---|---|---|---|
| 2 | Plataforma modular com serviços comuns | **Existe** | Core comum (auth, organizações, licenças, auditoria); módulos com manifesto |
| 3.1 | Licenciamento no painel administrativo (substituir o License Manager) | **Falta** | Emissão hoje só no License Manager (desktop). Integrar exige **chave privada no servidor da plataforma** — ver riscos (BLK-01: chave atual comprometida) |
| 3.2 | PACS/Telelaudos com bloqueio no servidor por instituição, contrato, módulo, situação comercial, limites e permissões | **Parcial** | Módulo + licença + permissão no servidor: existe. Contrato e situação comercial vêm da licença assinada (não de um cadastro de contratos da plataforma); limites de usuários/unidades: existe; políticas de aviso/contingência/exportação: parcial |
| 3.3 | DICOM Print online (ativação por código, autorização assinada, validação 7 d, tolerância 30 d) e offline | **Parcial** | Online por License Server e offline por arquivo: existem. Falta **ativação por código** contra a plataforma e parâmetros por plano/contrato vindos da plataforma |
| 3.4 | Segurança das licenças | **Existe** (no Print) | Ed25519, Hardware ID, TPM, Time Integrity, revogação, sequência; **BLK-01** (chave comprometida) segue bloqueando produção |
| 4 | Administrador Geral VYONIX (global) | **Falta** | Não há nível global; organizações são criadas por linha de comando (`vyonix init`). Acesso excepcional a dados clínicos com justificativa e prazo: falta |
| 5 | Administrador institucional | **Parcial** | Papel `administrador` por organização (usuários, papéis, unidades, configurações, estações). Falta **proteção contra escalada** (hoje quem gerencia usuários pode conceder qualquer papel/permissão) |
| 6 | Cadastros independentes por instituição | **Existe** | Contas são por organização (RLS); desativar numa não afeta outra |
| 7 | Login só com usuário e senha; instituição identificada pelo servidor; login único na plataforma | **Parcial** | Instalação local (edge): já é só usuário e senha. Nuvem (várias instituições no mesmo servidor): hoje exige o campo "Organização" e o login só é único dentro da organização → falta o **diretório global de logins** |
| 8 | Perfis dinâmicos e opcionais (modelos) | **Parcial** | Papéis personalizados existem; papéis padrão são sempre criados. Faltam os modelos Coordenador do CDI, Gestor de Telelaudos, Financeiro, Técnico de Suporte e a ativação só dos necessários |
| 9 | Várias funções na mesma conta | **Existe** | Vários papéis por usuário; permissões calculadas no servidor. Falta impedir acúmulo que contorne restrições (ex.: técnico não libera laudo mesmo com outro papel sem CRM) |
| 10 | Painel do Técnico em Radiologia | **Parcial → painel feito (28/10)** | Agenda, MPPS, Central de exames, Imagens (qualidade), Conciliação. Faltam painel próprio consolidado, falhas de transmissão, reenvio e "encaminhar para fila de laudos" |
| 11 | Médicos: próprio, vários, rede VYONIX, híbrido | **Parcial** | A e B existem (cadastro, vínculos, fila). C (médicos da rede VYONIX entre instituições) e D: **falta** — exige acesso entre organizações controlado por contrato |
| 12 | Distribuição dinâmica (automática, reserva transacional, recuperação de reservas, transferência) | **Parcial** | Atribuição manual com prioridade/prazo e reatribuição existem. Faltam atribuição automática, reserva ("pegar" exame) com expiração e regras |
| 13 | Estação de laudos (painel, estação, perfil) | **Parcial** | Lista, editor, modelos, Viewer em nova aba, rascunho salvo manualmente. Falta reorganizar em três áreas, salvamento automático, produção diária/mensal, histórico. **Pré-visualização da assinatura pendente: corrigida** (`0d3e05d`: política de conteúdo permite `blob:`; teste e2e confere a imagem carregada) |
| 14 | Distinção senha × imagem × assinatura digital; versões e adendos | **Existe** | Três situações rotuladas; PAdES preparado (BLK-14) |
| 15 | Produção e remuneração médica | **Falta** | Dados de base existem (atribuição, liberação, prioridade); faltam regras, valores, fechamento de período |
| 16 | Assistente de cadastro de instituições | **Falta** | Depende do §4 |
| 17 | Segurança multi-tenant | **Existe** | RLS em todas as tabelas de organização (teste de arquitetura), escopo por organização em toda sessão, testes de acesso cruzado |
| 18 | RBAC com permissões efetivas e delegação limitada | **Parcial** | Permissões efetivas: existe. **Delegação limitada: falta** |
| 19 | Auditoria | **Existe** | Login, falhas, usuários, papéis, licenças, estudos, laudos, assinatura; sem senhas/tokens |
| 20 | Compatibilidade do DICOM Print (Windows 7, offline) | **Existe** | Nenhuma mudança no Print nesta etapa |
| 21–22 | Testes e homologação com Clínica Alfa, Hospital Beta, CDI Gama | **Parcial** | Testes por funcionalidade existem; o roteiro integrado com as três instituições fictícias será criado na Fase 9 |

## 3. Ordem adotada e decisões técnicas

1. **Fase 2 (agora):** diretório global de logins (identificador único na plataforma; contas continuam
   independentes), login sem campo de organização na nuvem, proteção contra escalada de privilégios, modelos
   de perfil opcionais e painel do técnico.
2. **Fase 3–4:** administração institucional completa e nível global VYONIX (organizações, contratos,
   administrador inicial, acesso excepcional auditado a dados clínicos).
3. **Fase 5–6:** licenciamento no painel. **Decisão pendente do proprietário** antes de mover a emissão para a
   plataforma: onde fica a chave privada de emissão (servidor da plataforma, HSM/serviço de chaves, ou
   License Manager mantido como assinador offline), e a nova chave que substitui a comprometida (BLK-01).
   Até lá, o License Manager **não** é removido (exigência do §3.1).
4. **Fase 7:** médicos da rede VYONIX e distribuição automática/reserva.
5. **Fase 8:** produção e remuneração (regras de valor exigem a política comercial do proprietário; o sistema
   registra e calcula, sem pagar).

Decisões desta auditoria:

* **Login na instalação local (edge)**: a instalação serve uma organização; o login já é único nela. O
  diretório global vale para o servidor de nuvem (várias instituições); o campo "Organização" continua aceito
  pela API para contas antigas com o mesmo login em duas organizações (migração sem perda: esses logins
  ficam fora do diretório até serem renomeados, e o relatório os lista).
* **Delegação**: ninguém concede permissão que não possui; papel de administrador só por administrador.

## 4. Riscos e pendências

* BLK-01 (chave de licenças comprometida) continua bloqueando produção e a emissão integrada.
* Médicos da rede VYONIX entre instituições mudam o modelo de isolamento (acesso entre organizações): será feito
  por compartilhamento explícito por exame/contrato, nunca por acesso amplo.
* Remuneração: valores e regras são política comercial — o sistema não define valores sozinho.

## 5. Andamento

| Data | Fase | Entrega | Testes |
|---|---|---|---|
| 28/10 | 1 | Esta auditoria e matriz | — |
| 28/10 | 2 | Diretório global de logins (`core_0002`), login só com usuário e senha na nuvem, delegação limitada, modelos de perfil opcionais e estruturas | `test_access_multiinst.py` 4/4 |
| 28/10 | 2 | Painel do técnico (`/ris/technician-panel`, página própria): exames do dia, recebidos no PACS, recusas na recepção DICOM, pendências de qualidade; técnico registra chegada/início/conclusão (`ris.exam.perform`), não agenda, não cancela, não libera laudos | `test_ris_technician.py`; e2e `test_5` |
| 28/10 | 3–4 | Administração global VYONIX: organização operadora (`kind = operator`, `vyonix operator-init`), papel `admin_vyonix` sem permissões clínicas, assistente de cadastro (dados, CNPJ conferido, módulos contratados, estrutura, unidades, gestor com senha provisória e troca obrigatória), listagem só administrativa, desativar/reativar (sessões encerradas, login bloqueado, nada apagado), menu só na operadora (`core_0003`) | `test_platform_admin.py` 2/2; e2e `test_e2e_cloud.py` (servidor em nuvem, Chromium) |

Pendências da Fase 2: reenvio de estudo a uma estação DICOM cadastrada e "encaminhar para a fila de laudos"
pelo técnico — retomadas no pedido "Central de Exames / Painel do Técnico" (28/10, 18h12); (feito em seguida: painel "Perfis da instituição" e conferência do login na tela de Usuários).
