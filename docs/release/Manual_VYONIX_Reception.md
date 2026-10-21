# Manual do VYONIX Reception

**VYONIX DICOM Print {VERSION}** · painel da recepção no navegador

O VYONIX Reception é o painel operacional da recepção: pesquisa de exames, impressão sob demanda, impressão excepcional, prevenção de impressão duplicada e controle de retirada. Ele roda no computador do VYONIX (no serviço Windows) e é aberto pelo navegador dos computadores da recepção, na rede local.

## 1. Acesso

- Endereço: **https://IP-do-computador-VYONIX:8443/** (mostrado em *VYONIX Reception* no programa).
- Na primeira vez, o navegador avisa que o certificado não é de uma autoridade conhecida (o certificado é gerado pelo próprio computador VYONIX). Confirme a exceção ou instale o certificado da instituição (`cert.pem` + `key.pem` na pasta indicada na tela).
- Entre com seu **usuário e senha**. Senhas provisórias devem ser trocadas em **Senha** (canto superior direito). A sessão expira após 60 minutos sem uso (configurável). Cinco senhas erradas bloqueiam o usuário por 15 minutos.
- O painel só aceita computadores da **rede local** (endereços privados) — não o exponha à internet. Todas as ações e consultas ficam registradas.

## 2. Perfis

| Perfil | Pode |
|---|---|
| **Recepcionista** | Pesquisar, ver a composição das páginas, **IMPRIMIR EXAME** (primeira impressão), **IMPRIMIR AGORA**, controle de retirada |
| **Supervisor da recepção** | Tudo da recepcionista + **reimpressão** (impressão duplicada, com motivo), cancelar entrega, relatórios |
| **Técnico** | Recepção + configurações técnicas no programa (regras DICOM, impressoras, calibração) |
| **Administrador** | Tudo, inclusive usuários |

Os usuários são criados no programa VYONIX, em **VYONIX Reception → Usuários e perfis** (exige a senha de administrador). As configurações técnicas não ficam no navegador.

## 3. Controle de Impressão

Pesquise por **nome do paciente, ID do paciente, número de atendimento, Accession Number** ou descrição; filtre por **regra/equipamento, período, situação da impressão e situação da retirada**. Os botões de **modalidade** (CT, CR, MR…) filtram rapidamente e mostram a quantidade de exames. A lista se atualiza sozinha a cada 15 segundos.

Situações da impressão:

| Situação | Significado |
|---|---|
| Recebendo imagens / Aguardando conclusão | O equipamento ainda está enviando, ou o VYONIX aguarda o intervalo sem novas imagens que conclui o recebimento |
| Disponível | Recebido; regra **sob demanda**: aguardando a recepção |
| Pendente de impressão | Pedido na fila |
| Preparando impressão / Aguardando impressora | Montando as páginas / enviando à impressora |
| **Enviado ao spooler** | O Windows aceitou o documento (não garante que o papel saiu) |
| **Impressão confirmada** | O driver informou que imprimiu |
| Falha / Cancelado | Ver o histórico do exame |

Ao clicar em um exame: dados de identificação, regra e origem, imagens recebidas, histórico do exame (quem consultou, imprimiu, reimprimiu, entregou) e trabalhos de impressão.

- **Visualizar páginas** — mostra a composição exatamente como será impressa.
- **IMPRIMIR EXAME** — imprime com as configurações da regra (libera o exame sob demanda).
- **IMPRIMIR AGORA…** — impressão excepcional: escolha outra impressora e o número de cópias **sem alterar a regra**.

### Prevenção de duplicidade

- Se o exame já foi impresso, o VYONIX avisa (quantas vezes, quando, onde, quem) antes de imprimir de novo. A reimpressão exige o perfil **Supervisor** (ou superior) e o **motivo** (configurável).
- Exame já na fila não é enviado de novo.
- Cliques repetidos, retransmissões do navegador e pedidos simultâneos são ignorados (cada pedido tem um identificador único).
- Ficam registrados: usuário, data e hora, impressora, páginas, cópias, motivo e resultado.

## 4. Controle de Retirada

Independente da impressão (imprimir **não** marca como entregue):

**Aguardando preparação → Em preparação → Pronto para retirada → Entregue**, além de **Entrega pendente** e **Entrega cancelada**. Para **Entregar…**, informe a quem o exame foi entregue (nome e/ou documento). Cancelar uma entrega é exclusivo do supervisor.

## 5. Alertas

Impressora indisponível, falha de impressão, exame incompleto (sem novas imagens e não concluído), trabalho parado na fila, impressão duplicada, espaço em disco insuficiente e exames prontos aguardando retirada. Os limites ficam em *Configurações → VYONIX Reception* no programa.

## 6. Relatórios (supervisor)

Por **modalidade, regra/equipamento, impressora, usuário ou dia**, em um período: exames, trabalhos, folhas enviadas ao spooler (estimativa de consumo), folhas **confirmadas** pelo driver, reimpressões e falhas, e a **economia estimada** pela impressão sob demanda (exames não impressos × páginas estimadas). Exportação em CSV.

## 7. Privacidade (LGPD)

Os dados de identificação aparecem somente para usuários autenticados; cada consulta é registrada; os dados são apagados junto com as imagens no prazo de retenção. Não deixe o painel aberto em computadores sem supervisão (a sessão expira por inatividade).
