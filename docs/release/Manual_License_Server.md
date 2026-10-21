# Manual do VYONIX License Server

**VYONIX License Server {LS_VERSION}** · servidor central de licenças do VYONIX DICOM Print {VERSION}

> Uso exclusivo do fornecedor. O servidor não vai às clínicas e é separado do servidor DICOM delas.

## 1. Função

Validação online e controle comercial centralizado: assinaturas (contratos), planos, vencimentos, situação financeira confirmada, **autorizações de uso assinadas com validade limitada**, suspensões programadas, reativações, histórico, auditoria e integração de cobrança (Banco Inter, opcional). É opcional para clientes offline e necessário para suspensão e reativação remotas.

Não recebe nem armazena imagens DICOM, nomes de pacientes ou informações clínicas: a consulta das instalações aceita somente os campos `v`, `product_id`, `license_id`, `installation_id`, `hardware_id`, `nonce`, `known_seq`, `app_version` e `client_time` (qualquer outro campo é recusado).

## 2. Requisitos

- **Windows:** `VYONIX_License_Server.exe` (console, sem instalação, sem Python).
- **Linux ou Windows com Python 3.12:** código-fonte (`python -m license_server …`) com a biblioteca `cryptography`.
- Endereço público estável (DNS), porta TCP (padrão **8743**) liberada no firewall, relógio sincronizado (NTP) no servidor.
- Certificado TLS: o servidor gera um autoassinado (a impressão digital é gravada nas licenças online) ou usa o certificado da empresa (`tls/cert.pem` e `tls/key.pem` na pasta de dados).
- Chave de assinatura do servidor: **`vyx-srv-2026-01`** (impressão digital `7265:AF0F:E7A8:B327:084F:7BDC`), entregue como arquivo `.pem` cifrado + frase-senha. Só ela (ou outra incluída no VYONIX por atualização oficial) produz autorizações aceitas. Escopo: **somente autorizações de uso** — essa chave não emite licenças, revalidações nem listas de revogação.

## 3. Instalação

```
VYONIX_License_Server.exe init --data D:\VYONIX-LS --admin comercial ^
    --hostname licencas.suaempresa.com.br --port 8743 ^
    --key-file vyx-srv-2026-01.private.pem --key-id vyx-srv-2026-01
```

O comando pede a senha do administrador e a frase-senha da chave (ou use `VYONIX_LS_KEY_PASSPHRASE`), confere que a chave corresponde à chave pública embutida no VYONIX, cria o banco, o certificado e o arquivo `server.json`, e mostra a **impressão digital do certificado** (`certificate_pin`).

No License Manager: Gestão Comercial → **Políticas comerciais…** → informe o endereço (`https://licencas.suaempresa.com.br:8743`) e a impressão digital. As licenças emitidas com **Validação: Online** passam a levar esses dados assinados.

## 4. Execução

```
set VYONIX_LS_KEY_PASSPHRASE=…        (ou "signing_passphrase_file" em server.json)
VYONIX_License_Server.exe serve --data D:\VYONIX-LS
```

Para iniciar com o computador (Windows): Agendador de Tarefas → *Ao iniciar o sistema* → executar `serve` com uma conta de serviço que tenha acesso somente à pasta de dados; defina a frase-senha em `signing_passphrase_file` (arquivo com permissão restrita à conta do serviço). Em Linux, uma unidade systemd equivalente (`ExecStart=python3 -m license_server serve --data /srv/vyonix-ls`, `EnvironmentFile` com a frase-senha, `User=` dedicado).

Tarefas periódicas internas: avaliação de vencimentos/carências e avisos (5 min), consulta das cobranças em aberto no banco (30 min), limpeza de números de consulta e sessões.

## 5. `server.json`

| Chave | Uso |
|---|---|
| `bind`, `port`, `hostnames`, `public_url` | Escuta e endereço público |
| `signing_key_id`, `signing_key_file`, `signing_passphrase_file` | Chave de assinatura (PEM cifrado) |
| `tls_cert`, `tls_key` | Certificado TLS (substitua pelo da empresa, se desejar; atualize a impressão digital no License Manager) |
| `admin_networks` | Redes que podem usar a API administrativa (padrão: redes privadas e local) |
| `webhook_secret` | Segredo da URL de notificações do banco |
| `session_minutes` | Sessão administrativa (padrão 30 min, renovada a cada uso) |
| `inter` | Integração Banco Inter (ver documento próprio) |

## 6. Usuários

`VYONIX_License_Server.exe user-add --data PASTA --username fin1 --role financial` (perfis `admin`, `financial`, `support`, `viewer`). Senhas com scrypt, bloqueio de 15 minutos após 5 erros, limite de tentativas por endereço.

## 7. API

Todas as rotas exigem HTTPS. Respostas em JSON; erros com `{"error": "..."}`.

| Rota | Acesso | Descrição |
|---|---|---|
| `GET /v1/health` | público | Situação, versão e chave carregada |
| `POST /v1/authorize` | instalações | Consulta de autorização (campos da seção 1). Respostas: 200 com `authorization` assinada; 404 licença não registrada; 403 instalação/computador divergentes; 409 número repetido ou licença substituída; 429 excesso de consultas |
| `POST /v1/admin/login` / `logout` / `GET me` | usuários | Sessão (`Authorization: Bearer <token>`) |
| `GET /v1/admin/subscriptions[?search=&state=]` | todos | Assinaturas com estado calculado e resumo |
| `GET /v1/admin/subscriptions/{id}` | todos | Histórico, avisos, pagamentos, cobranças, autorizações, suspensões e reativações |
| `POST /v1/admin/subscriptions/{id}/{ação}` | conforme perfil | `payment`, `claim`, `grace`, `schedule-suspension`, `cancel-suspension`, `suspend`, `reactivate`, `edit`, `charge`, `offline-authorization` |
| `POST /v1/admin/licenses` | admin, financeiro | Registra a licença (`.vylic`, assinatura conferida) e cria/atualiza a assinatura |
| `POST /v1/admin/licenses/{id}/revoke` | admin | Revogação (a próxima autorização leva a revogação) |
| `GET/PUT /v1/admin/settings`, `GET /v1/admin/plans`, `PUT /v1/admin/plans/{código}` | consulta / admin | Políticas e planos |
| `POST /v1/admin/evaluate` | todos | Avaliação imediata |
| `GET /v1/admin/audit` | todos | Auditoria encadeada e verificação da cadeia |
| `GET/POST /v1/admin/users` | admin | Usuários |
| `POST /v1/billing/inter/{segredo}` | banco | Aviso de pagamento (confirmado por consulta ao banco) |

**Proteções:** TLS 1.2+; negociação TLS em thread própria; corpo limitado a 512 KB; sessões com token aleatório (só o resumo SHA-256 é guardado); permissões por perfil; API administrativa restrita às redes configuradas; limites de taxa por endereço e por licença; número de uso único por consulta (repetição recusada); autorizações com validade curta e sequência crescente; respostas assinadas (Ed25519); auditoria encadeada com IP.

## 8. Backup

Copie a pasta de dados com o serviço parado (ou use a API de backup do SQLite): `license_server.db`, `server.json`, `keys/` (PEM cifrado), `tls/`. Guarde a frase-senha da chave separada do backup.

## 9. Autoteste

`VYONIX_License_Server.exe selftest [--report r.json]` cria uma pasta temporária com chaves descartáveis, sobe o servidor HTTPS em 127.0.0.1 e executa: login administrativo, registro de licença, API sem token (401), consulta de autorização pelo mesmo código do VYONIX (certificado fixado, assinatura e número de uso único conferidos), repetição recusada (409), certificado divergente recusado e verificação da auditoria.

## 10. Rotação da chave do servidor

`VYONIX_License_Server.exe genkey --out nova.pem --key-id vyx-srv-AAAA-NN` gera a nova chave cifrada e imprime a linha pública. Inclua a linha (escopo *authorization*) no VYONIX DICOM Print em uma atualização oficial; depois que as clínicas atualizarem, troque `signing_key_id`/`signing_key_file`. Mantenha a chave antiga na lista do produto até a troca.
