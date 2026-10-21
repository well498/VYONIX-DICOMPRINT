# Integração com o Banco Inter

**VYONIX License Server {LS_VERSION}** · camada opcional de cobrança

> O VYONIX funciona sem banco. A integração roda **somente no VYONIX License Server**; credenciais, certificados e tokens bancários **nunca** são instalados nas clínicas.

## 1. Arquitetura

```
License Server ──(TLS mútuo + OAuth2)──► API Cobrança v3 do Banco Inter
      ▲                                         │
      └──── POST /v1/billing/inter/<segredo> ◄──┘  (aviso: só indica o que consultar)
```

- Camada `vyonix_commercial.billing`: interface comum de provedores (criar cobrança, consultar situação, interpretar aviso) — outros bancos podem ser acrescentados sem alterar o restante.
- `InterProvider`: OAuth2 *client credentials* (`POST /oauth/v2/token`, escopos `boleto-cobranca.read boleto-cobranca.write`), certificado da aplicação em **TLS mútuo**, `POST /cobranca/v3/cobrancas` (emissão de boleto com Pix), `GET /cobranca/v3/cobrancas/{codigoSolicitacao}` (consulta), `PUT /cobranca/v3/cobrancas/webhook` (cadastro da URL de avisos).
- Endereços padrão: produção `https://cdpj.partners.bancointer.com.br`; sandbox `https://cdpj-sandbox.partners.uatinter.co` (configuráveis — confira a documentação vigente do Inter antes da homologação).

## 2. Regras de segurança financeira

1. **Boleto emitido não quita.** A cobrança fica "emitida"; o período pago só muda com pagamento confirmado.
2. **O aviso do banco não é prova de pagamento.** Cada aviso é registrado (chave: código da cobrança + situação + data), e a situação é **consultada no banco** pelo canal autenticado. Só a situação `RECEBIDO` confirma o pagamento.
3. **Avisos repetidos são ignorados** (mesma chave) e o pagamento é idempotente pela referência `inter:<codigoSolicitacao>` — nunca quita duas vezes.
4. `MARCADO_RECEBIDO` (baixa manual informada no banco) vira **"conferência manual"**: o operador financeiro confere e registra o pagamento.
5. Comprovante enviado pelo cliente ou promessa de pagamento: apenas registro (*Comprovante — não quita*).
6. Se a consulta ao banco falhar, o aviso é descartado do registro e o servidor responde 503 para que o banco reenvie.
7. A URL de avisos contém um segredo aleatório (`webhook_secret`); segredo errado → 404 e registro na auditoria. Em produção, publique o servidor atrás de um proxy que exija o certificado de cliente do Inter (TLS mútuo) na rota de avisos.

Situações mapeadas: `RECEBIDO` → paga; `MARCADO_RECEBIDO` → conferência manual; `A_RECEBER`, `EM_PROCESSAMENTO` → emitida; `ATRASADO`, `PROTESTO` → vencida; `CANCELADO`, `FALHA_EMISSAO` → cancelada; `EXPIRADO` → expirada.

## 3. Configuração (`server.json`)

```json
"inter": {
  "base_url": "https://cdpj-sandbox.partners.uatinter.co",
  "client_id": "…",
  "client_secret_file": "inter/client_secret.txt",
  "cert_file": "inter/aplicacao.crt",
  "key_file": "inter/aplicacao.key",
  "account": null
}
```

Arquivos na pasta de dados do servidor, com permissão restrita à conta do serviço. O `client_secret` não é exibido em registros.

Cadastre a URL de avisos no Inter: `https://licencas.suaempresa.com.br:8743/v1/billing/inter/<webhook_secret>`.

## 4. Operação

- **Emitir cobrança:** `POST /v1/admin/subscriptions/{id}/charge` com `due_date`, valor (padrão: mensalidade), CNPJ/CPF e endereço do pagador → código da cobrança registrado no histórico.
- **Conciliação:** automática pelos avisos e, a cada 30 minutos, pela consulta das cobranças em aberto.
- **Pagamento confirmado:** período pago estendido pelo plano; se a assinatura estava SUSPENSA/EXPIRADA, ela é **REATIVADA** e as instalações online recebem a autorização na próxima consulta.

## 5. Homologação

O adaptador foi verificado contra uma reprodução local da API (TLS mútuo real, autenticação, emissão, consulta, avisos repetidos e falsos). Antes de produção: homologar no **sandbox do Inter** com a conta contratante (emissão, pagamento simulado, aviso, consulta, cancelamento), conferir os nomes de campos e situações na documentação vigente e registrar o resultado no *Roteiro de Testes Manuais* (M-90 a M-93).
