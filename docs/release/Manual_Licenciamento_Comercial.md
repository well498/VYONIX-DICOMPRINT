# Licenciamento Comercial por Assinatura

**VYONIX DICOM Print {VERSION}** · gestão comercial no VYONIX License Manager e no VYONIX License Server

> Documento administrativo (fornecedor). Não distribuir às clínicas. As regras descritas aqui devem refletir o contrato comercial de cada cliente.

## 1. Componentes

| Componente | Onde roda | Papel |
|---|---|---|
| **VYONIX License Client** | Dentro do VYONIX DICOM Print de cada clínica | Verifica licença e autorizações (somente chaves públicas), calcula o estado comercial, consulta o servidor (licenças online), aplica arquivos de renovação (offline) |
| **VYONIX License Manager** | Computador do administrador (portátil ou instalado) | Emissão de licenças, **Gestão Comercial** das assinaturas offline, autorizações offline assinadas, administração remota do servidor |
| **VYONIX License Server** | Servidor do fornecedor (Windows ou Linux), separado das clínicas | Assinaturas online, autorizações com validade limitada, suspensões programadas, reativações, histórico, auditoria e cobrança (Banco Inter, opcional) |

A **licença** identifica cliente, computador (Hardware ID), instalação (Installation ID), recursos, limites e a **política comercial** (assinada, não alterável na clínica): validação online ou offline, dias de aviso, dias de carência e tolerância sem contato com o servidor.

A **autorização de uso** (`vyonix-authorization`) traz a situação comercial atual — período pago, carência, suspensão programada ou aplicada, reativação. É assinada pelo License Manager (arquivo `.vyauth`) ou pelo License Server (resposta online). Cada autorização tem número de sequência crescente: uma autorização antiga nunca substitui uma mais nova.

## 2. Modalidades

Demonstração (5 dias), **Mensal**, **Trimestral**, **Semestral**, **Anual**, **Período personalizado** e **Permanente**. A licença permanente **não é suspensa** por inadimplência de mensalidade nem de manutenção opcional: a Gestão Comercial recusa suspender uma licença permanente (eventual contrato de manutenção é tratado à parte e não afeta o funcionamento).

## 3. Estados comerciais

| Estado | Quando | Efeito no VYONIX da clínica |
|---|---|---|
| **ATIVA** | Pago até o vencimento | Normal |
| **PRÓXIMA DO VENCIMENTO** | A partir de *N* dias antes do vencimento (padrão 5) | Normal; aviso ao administrador da clínica |
| **EM ATRASO** | Vencida, dentro da carência (padrão 7 dias) | Normal; aviso ao administrador |
| **SUSPENSÃO PROGRAMADA** | Suspensão marcada para uma data após a carência | Normal; aviso com a data |
| **SUSPENSA** | Data da suspensão programada alcançada, suspensão aplicada, ou fim da carência com suspensão automática prevista em contrato | Novas operações licenciadas suspensas (ver seção 6) |
| **EXPIRADA** | Fim da carência sem pagamento confirmado (sem suspensão explícita) | Igual a SUSPENSA |
| **REATIVADA** | Regularizada após SUSPENSA/EXPIRADA (exibida por 3 dias) | Normal |

O estado é calculado pela mesma rotina no License Manager, no License Server e no VYONIX (a partir dos dados assinados), sempre com o **horário confiável** do VYONIX Time Integrity: atrasar o relógio do Windows não desfaz um vencimento nem uma suspensão. Todas as transições ficam no histórico (estado anterior, novo estado, data, responsável, origem e motivo).

**Estado financeiro × conectividade.** A situação comercial é independente da situação técnica de contato com o servidor. *Falta de internet não é inadimplência* (seção 7).

## 4. Políticas configuráveis

Gestão Comercial → **Políticas comerciais…** (administrador comercial). Os valores valem para as próximas licenças emitidas (são gravados e assinados nelas) e para a avaliação das assinaturas.

| Política | Padrão |
|---|---|
| Avisos começam (dias antes do vencimento) | 5 |
| Carência após o vencimento | 7 dias |
| Prorrogação máxima por concessão | 30 dias |
| Validade de cada autorização online | 7 dias |
| Tolerância sem contato com o servidor | 10 dias |
| Suspensão automática ao fim da carência | Desligada (ligar somente se o contrato prever) |
| Perfis que podem conceder prorrogação | Administrador comercial, Operador financeiro |
| Ações que exigem confirmação de um administrador comercial | Programar suspensão, Suspender, Reativar |
| Endereço e impressão digital do License Server | — (obrigatório para emitir licenças online) |

Por assinatura (Gestão Comercial → **Plano e valor…**): plano, mensalidade, CNPJ, **contrato prevê suspensão por inadimplência**, suspensão automática e **requisitos operacionais da clínica** (ex.: plantão 24 h, comunicar o diretor técnico).

## 5. Perfis

| Perfil | License Manager / License Server |
|---|---|
| **Administrador comercial** | Tudo: chaves, usuários, políticas, revogação, confirmações |
| **Operador financeiro** | Gestão Comercial: pagamentos confirmados, cobranças, prorrogação, programar suspensão/suspender/reativar (com confirmação do administrador quando configurado) |
| **Suporte técnico** | Reativação por troca de hardware/reinstalação, revalidação, autorizações offline; sem ações financeiras |
| **Emissor** | Clientes, solicitações, emissão, renovação, reativação |
| **Consulta** | Somente leitura |

Na clínica, os perfis são separados e **não comerciais**: *Administrador da clínica*, *Técnico da clínica*, *Supervisor da recepção* e *Recepcionista*. Somente o administrador da clínica (senha de administrador do VYONIX) vê os detalhes comerciais na página Licença; recepção e técnicos veem apenas um aviso neutro ("funções licenciadas suspensas — procure o administrador da clínica"), sem valores ou situação financeira.

## 6. Suspensão controlada

**Pré-condições verificadas pelo sistema** (a operação é recusada com o motivo se alguma faltar):

1. inadimplência confirmada — período pago encerrado e nenhum pagamento confirmado que o cubra;
2. avisos registrados para aquele vencimento (aviso prévio ou de atraso);
3. fim da carência (inclusive prorrogações);
4. contrato da assinatura prevê suspensão por inadimplência;
5. licença não permanente;
6. confirmação, pelo operador, de que **a política contratual e os requisitos operacionais da clínica foram verificados**;
7. confirmação de um administrador comercial diferente do operador, quando a ação está em *confirm_actions*.

**O que a suspensão faz:** recusa novas operações licenciadas — recepção DICOM (C-STORE), DICOM Print, regras automáticas, impressão automática de novos exames e novas impressões pela recepção.

**O que a suspensão nunca faz:** apagar, cifrar ou alterar imagens; impedir a exportação dos exames; eliminar histórico; destruir filas, regras ou configurações; alterar calibrações ou artes BMP; interromper abruptamente trabalhos já aceitos.

- **Trabalhos aceitos antes da suspensão são concluídos:** o processador da fila continua imprimindo os trabalhos criados — ou cujas imagens foram recebidas — antes do instante da suspensão. Trabalhos posteriores aguardam na fila e são processados após a reativação.
- **Exportação sempre disponível:** Licença → *Exportar exames armazenados…* (ou `Vyonix.exe --license export --file PASTA`) copia os arquivos DICOM originais, conferidos por SHA-256, com manifesto sem nome de paciente.
- **Acesso administrativo mantido:** página Licença, histórico, diagnóstico, importação de autorização, configurações, Reception (consulta e controle de retirada).
- A suspensão comercial aparece como **"Assinatura suspensa"**, distinta de falha técnica (ex.: "Autorização local vencida", "Licença de outro computador", "Funções suspensas" por integridade do relógio).

## 7. Validação online, tolerância e falhas de rede

- O VYONIX consulta o servidor a cada 6 horas (configurável de 1 a 24 h) e pelo botão **Verificar agora no License Server**. Envia apenas: License ID, Installation ID, Hardware ID, versão, um número aleatório de uso único e a sequência da última autorização. **Nenhuma imagem, nome de paciente ou informação clínica.**
- A resposta é uma autorização assinada pela chave do servidor (escopo *authorization*), conferida quanto a assinatura, licença, instalação, computador, número de uso único (resposta antiga ou repetida é recusada) e sequência.
- Conexão HTTPS (TLS 1.2+). Com a **impressão digital do certificado** gravada na licença, o VYONIX só aceita aquele certificado; sem ela, vale a cadeia de certificação do Windows (ou um arquivo de autoridade configurado).
- Situações técnicas distintas: **contato normal**, **internet ou DNS indisponível**, **License Server indisponível**, **servidor recusou a consulta** (licença não registrada, instalação divergente), **resposta inválida — suspeita de adulteração** (registrada como evento de segurança). Nenhuma delas altera o estado comercial.
- **Tolerância:** cada autorização online vale 7 dias; sem contato, o VYONIX continua funcionando por mais 10 dias (padrões). Só depois disso entra em **"Autorização local vencida"** — estado técnico, com mensagem explícita de que não indica inadimplência. Um único contato bem-sucedido (ou um arquivo de autorização) libera na hora.
- Uma suspensão programada já recebida é aplicada na data, mesmo sem novo contato.

## 8. Funcionamento sem internet (offline)

Licenças offline não consultam servidor. A renovação é um **arquivo de autorização** `.vyauth` (Gestão Comercial → *Exportar autorização offline*), importado pelo administrador da clínica em Licença → *Importar autorização / renovação…*.

**Limite documentado:** não é possível garantir suspensão remota imediata de uma licença offline válida. A suspensão ocorre no **vencimento da autorização** (fim do período pago + carência) ou quando uma **atualização local confiável** (arquivo assinado com suspensão programada/aplicada) é importada. Também não há proteção absoluta contra restauração integral de imagem de disco em computador permanentemente desconectado.

## 9. Reativação

| Forma | Como | Registro |
|---|---|---|
| **Automática online** | Pagamento confirmado no servidor (manual ou conciliação bancária) → na próxima consulta o VYONIX recebe a autorização REATIVADA | Histórico do servidor (pagamento, reativação, responsável) e da clínica (origem "License Server", emitida por) |
| **Administrativa** | Gestão Comercial → *Reativar…* com motivo (acordo, erro de cobrança) e, se o período já terminou, data até a qual fica liberada | Histórico com operador e confirmação do administrador |
| **Offline** | Pagamento confirmado no License Manager → *Exportar autorização offline* → importação na clínica | Histórico do License Manager e da clínica (origem "arquivo de renovação", aplicado por, emitido por) |

A reativação preserva configurações, filas, calibrações, imagens e histórico — nada é reinstalado.

## 10. Pagamentos

- **Somente pagamento confirmado quita:** *Registrar pagamento…* exige a referência do documento bancário (número do boleto, código da cobrança, ID da transação Pix). O registro é idempotente: a mesma referência não quita duas vezes.
- **Boleto emitido, comprovante enviado pelo cliente ou promessa de pagamento não quitam:** use *Comprovante (não quita)…* para registrar o contato; nada muda no período pago.
- Pagamento após o vencimento: o novo período conta a partir do vencimento anterior (período contratado), não da data do pagamento.
- Integração bancária (opcional): ver *Integração com o Banco Inter*.

## 11. Gestão Comercial (License Manager)

Colunas: cliente, CNPJ, instalação, plano, mensalidade, vencimento, último pagamento confirmado, dias de atraso, situação, validação, licença, último contato. Abas: **Histórico**, **Notificações**, **Suspensões**, **Reativações**, **Pagamentos**, **Cobranças**, **Autorizações**.

Ações: Emitir licença, Renovar, Reemitir (.vylic), Registrar pagamento, Comprovante (não quita), Conceder carência, Programar suspensão, Cancelar suspensão, Suspender conforme a política, Reativar, Exportar autorização offline, Publicar licença no servidor, Plano e valor, Auditoria.

**Origem dos dados:** *Este License Manager* (assinaturas offline) ou *Conectar ao License Server…* (assinaturas online, pela API autenticada; o usuário e a senha são os do servidor). A chave privada do License Manager nunca é enviada ao servidor.

## 12. Fluxos de trabalho

**Cliente online (mensal):** Políticas → endereço e impressão digital do servidor → emitir a licença com *Validação: Online* → *Conectar ao License Server* → *Publicar licença no servidor* (plano e valor) → o cliente instala a licença; o VYONIX passa a consultar o servidor.

**Cliente offline (mensal):** emitir com *Validação: Offline* → a cada pagamento confirmado: *Registrar pagamento* → *Exportar autorização offline* → enviar o `.vyauth` ao cliente.

**Inadimplência:** avisos automáticos (PRÓXIMA DO VENCIMENTO, EM ATRASO) → contato com o cliente → se necessário, *Conceder carência* (perfis autorizados, com motivo) → após a carência: verificar contrato e requisitos operacionais → *Programar suspensão* (preferível: dá data ao cliente) → regularização: *Registrar pagamento* (reativação automática).

**Troca de computador:** suporte técnico → *REATIVAR / EMITIR NOVA LICENÇA* (motivo) → a assinatura acompanha a nova licença (mesmo período pago, histórico preservado) → para clientes online, publicar a nova licença no servidor.

## 13. Auditoria e LGPD

License Manager e License Server mantêm auditoria encadeada (cada registro contém o resumo do anterior; alterações fora do aplicativo são detectadas): emissão, renovação, alteração de plano, carência, suspensão, reativação, pagamentos, autorizações, falhas de validação e tentativas de uso indevido (consulta de outra instalação, notificação bancária com segredo errado). No VYONIX, o histórico de licença, assinatura e conectividade fica na página Licença.

Dados tratados: razão social, CNPJ, contato comercial e identificadores técnicos (resumos de hardware, IDs VYONIX). Nenhum dado de paciente transita no licenciamento. Clientes podem ser anonimizados no License Manager mantendo o histórico técnico.

## 14. Limites

- Proteções locais (hardware, instalação, TPM, cofre selado, horário confiável) dificultam, mas não impedem de forma absoluta, adulteração e clonagem em computadores controlados integralmente pelo usuário.
- Licenças offline não são suspensas remotamente de imediato (seção 8).
- A integração com o Banco Inter foi testada contra uma reprodução local da API; requer homologação no sandbox do banco com as credenciais da conta.
