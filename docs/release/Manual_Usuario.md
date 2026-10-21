# Manual do Usuário

**VYONIX DICOM Print {VERSION}**

> Este manual descreve apenas os recursos presentes nesta versão de homologação. O software não está validado para uso clínico.

## 1. Visão geral da tela

A janela do VYONIX tem três áreas:

- **Cabeçalho** com a marca VYONIX e o slogan *Precisão em cada imagem.*
- **Menu lateral** com 12 itens.
- **Área de conteúdo**, que mostra a página selecionada.

A barra inferior mostra a pasta de dados em uso e o aviso de que a versão não é destinada a uso clínico. Apenas uma janela do VYONIX pode ficar aberta por usuário. Em telas menores que 1320 × 880 (por exemplo, 1366 × 768), a janela abre maximizada.

## 2. Itens do menu nesta versão

| Item | Situação nesta versão |
|---|---|
| Dashboard | Disponível |
| Equipamentos DICOM | Disponível |
| Servidor DICOM | Disponível (recepção e impressão DICOM) |
| Impressoras | Disponível |
| Trabalhos de impressão | Disponível |
| Regras automáticas | Disponível |
| Calibração | Disponível |
| Perfis de impressão | Disponível |
| Histórico | Disponível |
| Configurações | Disponível |
| Licença | Disponível |
| Sobre o VYONIX | Disponível |

As páginas não implementadas mostram o escopo planejado e não executam nenhuma operação.

## 3. Dashboard

Atualizado automaticamente a cada 5 segundos, com dados lidos do banco local:

- **Indicadores:** trabalhos recebidos, em fila, enviados à impressão e com falha nas últimas 24 horas.
- **Serviços:** estado real do servidor de recepção (Storage SCP); estado real do Print SCP e da fila de impressão; Serviço Windows aparece como *Não implementado* (Fase 7).
- **Configuração DICOM:** AE Title, endereço e porta configurados.
- **Equipamentos, Impressora selecionada, Alertas operacionais e Falhas recentes.**

## 4. Equipamentos DICOM

Lista os equipamentos que podem enviar imagens, com AE Title, IP, autorização, último contato e situação.

- **Adicionar / Editar:** abre o cadastro (nome, AE Title, modalidade, IP, porta, unidade, setor, fabricante, modelo, observações). Erros aparecem ao lado de cada campo.
- **Autorizar / bloquear:** libera ou impede o envio de imagens sem apagar o cadastro.
- **Testar conexão (C-ECHO):** o VYONIX chama o equipamento no IP e porta cadastrados e mostra o tempo de resposta.
- **Histórico:** eventos do equipamento (conexões, recusas, alterações).
- **Remover:** exclui o cadastro; se o equipamento já enviou imagens, ele é apenas desativado, para preservar o histórico.
- **Importar / Exportar:** copia os cadastros entre instalações em um arquivo JSON.

Detalhes de configuração dos equipamentos estão no *Guia de Configuração DICOM*.

## 5. Servidor DICOM

Mostra o estado da recepção (em execução, parado ou erro, com o motivo), o AE Title, o endereço e a porta, as associações ativas e os eventos DICOM recentes.

- **Iniciar / Parar / Reiniciar:** controla o servidor.
- **Testar (C-ECHO local):** verifica o próprio servidor.

O cartão **Print SCP — impressão DICOM** tem os mesmos controles para o servidor de impressão (AE Title padrão `VYONIX_PRINT`, porta `11113`). Equipamentos que "imprimem em filme" podem usar o VYONIX como impressora DICOM: cada filme vira um trabalho em *Trabalhos de impressão*, com origem "DICOM Print".

Com o serviço Windows instalado (padrão), os servidores e a fila rodam no serviço, mesmo com a janela fechada; os botões desta tela comandam o serviço. Sem o serviço, os servidores rodam enquanto a janela estiver aberta.

## 5A. Impressoras

Lista as impressoras do Windows e a impressora virtual **VYONIX PDF (arquivo)**.

- **Atualizar lista:** consulta o Windows de novo (driver, porta, papéis, resoluções, cor, situação).
- **Definir como padrão do VYONIX:** impressora usada quando nenhum perfil indica outra. Sem ela, vale a impressora padrão do Windows. Se nenhuma estiver definida, os trabalhos falham com uma mensagem clara; o VYONIX nunca troca para o PDF por conta própria.
- **Imprimir página de teste:** imprime o padrão de teste (escala de cinza e régua de 10 cm).
- **VYONIX PDF** grava cada trabalho em `C:\ProgramData\VYONIX\DICOM Print\output\pdf`, no tamanho real do papel. Impressoras que pediriam um nome de arquivo (como "Microsoft Print to PDF") gravam em `output\arquivo`, sem abrir janela.

## 5B. Trabalhos de impressão

Cada série recebida vira um trabalho depois de alguns segundos sem novas imagens (*Configurações → Fila de impressão*). Estados:

| Estado | Significado |
|---|---|
| Recebido / Validando / Processando | Na fila, em preparação |
| Aguardando impressão | Páginas prontas, enviando ao Windows |
| Enviado ao sistema de impressão | Aceito pelo spooler do Windows; **não significa papel impresso** |
| Concluído | Saída confirmada (PDF gravado e conferido, ou o driver informou que imprimiu) |
| Falhou | Erro; tentativas automáticas quando o problema é passageiro (ex.: impressora offline) |
| Retido | Aguardando liberação manual |
| Cancelado | Cancelado pelo usuário |

Ações: **Detalhes** (configurações aplicadas com a origem de cada uma, histórico de estados e imagens), **Reter**, **Liberar**, **Tentar de novo**, **Reprocessar com config. atuais**, **Reimprimir…** (cria um novo trabalho, com outra impressora ou número de cópias se você quiser) e **Cancelar trabalho**.

**Sem impressão duplicada:** se o equipamento reenviar a mesma série, nada é impresso de novo, e o Histórico registra o reenvio. Para outra cópia, use Reimprimir. Se o programa for fechado durante o envio ao Windows, o trabalho volta como *Retido*: confira se a impressão saiu antes de liberar.

## 5C. Calibração

Ajuste a resposta de cada impressora sobre o padrão de teste ou sobre uma imagem recebida: brilho, contraste, gama, níveis de preto e branco, inversão, escala (%) e deslocamento (mm). **Imprimir página de teste** usa os valores dos controles, mesmo antes de salvar o perfil. Meça a régua de 10 cm no papel: se medir 9,8 cm, ajuste a escala para cerca de 102 %. Salve como perfil e associe-o à impressora.

## 5D. Perfis de impressão

Um perfil define papel, orientação, layout, cópias, margens, espaçamento, resolução, cabeçalho, rodapé, informações do exame e numeração. Campos "não definir" herdam o valor do próximo nível. Precedência: padrão do sistema < perfil da impressora < perfil da modalidade < perfil do equipamento < regra automática < pedido DICOM Print < escolha manual.

**Dados do paciente:** nome e ID no cabeçalho ficam desligados por padrão (LGPD). Quando ligados, são lidos do arquivo DICOM só no momento da impressão; não vão para o banco, os logs nem o nome do documento no spooler.

## 5E. Regras automáticas

Uma regra tem **condições** (todas precisam valer; sem condições, vale para todos os trabalhos) e **ações**. Exemplos:

- *Modalidade é igual a MG* → papel A3, layout 1 × 2.
- *Horário entre 19:00-07:00* e *Unidade é igual a Pronto-socorro* → impressora do plantão.
- *Equipamento AE Title começa com US_* e *Número de imagens maior ou igual a 20* → reter para liberação manual.

As regras ativas são avaliadas da **prioridade menor para a maior** (use **Subir/Descer**). Quando duas regras definem a mesma configuração, vale a de maior prioridade (a avaliada primeiro); as seguintes só completam o que falta. A ação **Parar** encerra a avaliação. Textos são comparados sem diferenciar maiúsculas e acentos.

**Simular…** mostra, para um trabalho hipotético (equipamento, modalidade, horário etc.), por que cada regra se aplica ou não e o resultado final com a origem de cada valor. Nada é impresso. Os detalhes de cada trabalho real também mostram a avaliação das regras na hora da criação.

**Reprocessar com config. atuais** (em Trabalhos) reavalia as regras e perfis atuais, mantendo o que veio do pedido DICOM Print.

## 5F. Ícone na bandeja

O ícone do VYONIX ao lado do relógio mostra o estado dos serviços. Clique nele para abrir a janela; o menu tem **Abrir o VYONIX** e **Sair do VYONIX**. Fechar a janela no **X** a mantém na bandeja (desligável em *Configurações → Interface*). Sair da janela não para o serviço Windows.

## 6. Senha de administrador

Em **Configurações → Senha de administrador**, defina uma senha (mínimo de 8 caracteres). Com senha definida, estas ações pedem a senha: salvar, importar ou restaurar configurações; cadastrar, editar, autorizar, remover ou importar equipamentos; iniciar, parar ou reiniciar o servidor DICOM. Depois de digitada, a senha vale pelo tempo de *Bloquear administração após* (padrão 10 minutos sem uso). **Bloquear agora** encerra o desbloqueio. Cinco senhas erradas seguidas bloqueiam novas tentativas por um minuto.

Sem senha definida, o Dashboard mostra um alerta.

## 7. Configurações

As configurações estão agrupadas em Instalação, DICOM — Recepção, DICOM — Impressão, Fila de impressão, Retenção de dados, Interface e Diagnóstico.

1. Altere os campos desejados.
2. Clique em **Salvar**. Todos os valores são validados antes de qualquer gravação.
3. Se algum valor for inválido, o campo é destacado com a explicação e nada é gravado.

Regras de validação principais:

- **AE Title:** até 16 caracteres ASCII imprimíveis, sem barra invertida; espaços nas extremidades são removidos.
- **Porta:** de 1 a 65535. Portas abaixo de 1024 (como 104) geram aviso sobre privilégios e firewall.
- **Endereço IP:** IPv4 ou IPv6 válido; `0.0.0.0` significa todas as interfaces.
- Recepção e impressão DICOM, quando habilitadas, devem usar portas e AE Titles diferentes.

Ao salvar campos marcados com ⟳, o servidor DICOM é reiniciado automaticamente.

Outros botões:

- **Descartar alterações:** recarrega os valores gravados.
- **Restaurar padrões:** volta todas as configurações aos valores de fábrica (com confirmação).
- **Exportar / Importar:** salva ou carrega as configurações em um arquivo JSON, útil para replicar a configuração em outro computador. O ID da instalação nunca é exportado.

O **tema** (Seguir o Windows, Claro, Escuro) e o **nível de log** são aplicados imediatamente.

Toda alteração é registrada com usuário do Windows, data, hora, valor anterior e novo valor.

## 8. Histórico

**Eventos:** registros operacionais e de auditoria (inicialização, encerramento, alterações de configuração, falhas).

- Filtre por período, categoria, nível mínimo e texto; clique em **Filtrar**.
- São exibidos até 500 eventos; o rodapé informa o total encontrado.
- **Exportar CSV** gera um arquivo separado por ponto e vírgula, que abre diretamente no Excel.

**Alterações administrativas:** lista cada configuração alterada, com valor anterior, novo valor, usuário e motivo.

Os horários são mostrados no fuso horário do computador e armazenados em UTC. Nomes, IDs e outros dados de pacientes são mascarados automaticamente nos eventos e logs.

## 9. Licença

O licenciamento é **offline**: o VYONIX nunca se comunica com a internet.

1. Clique em **Gerar código de solicitação** e envie o código (botões **Copiar** ou **Salvar em arquivo…**) ao fornecedor. O código contém o ID da instalação, um identificador do computador (hash, sem números de série), a versão e o nome da unidade — nenhum dado de paciente.
2. O fornecedor devolve um arquivo `.vylic`, assinado digitalmente (Ed25519).
3. Clique em **Instalar licença…** (exige a senha de administrador) e escolha o arquivo.

A página mostra a edição, o licenciado, a validade, os recursos e o limite de equipamentos. A licença vale só para esta instalação e este computador: reinstalar o Windows ou copiar o VYONIX para outro computador exige nova licença. Um arquivo alterado, de outra instalação ou com o relógio do Windows atrasado é recusado e registrado no Histórico. O Dashboard avisa 30 dias antes do vencimento.

| Edição | Recursos | Equipamentos autorizados |
|---|---|---|
| Essencial | Recepção DICOM, impressão e fila | 2 |
| Profissional | + Impressão DICOM (Print SCP) e regras automáticas | 10 |
| Corporativo | Todos | sem limite |

Sem licença válida, a versão comercial funciona em **modo de avaliação**: tudo funciona, mas as páginas impressas recebem no rodapé a marca "NÃO LICENCIADO — USO PARA AVALIAÇÃO". **Nesta versão de homologação a licença é verificada e exibida, mas nada é limitado.**

## 10. Sobre o VYONIX

Versão, etapa de desenvolvimento, pastas de dados em uso e componentes de terceiros.

## 11. Logs

Os logs ficam em `%LOCALAPPDATA%\VYONIX\DICOM Print\logs\vyonix-ui.log`, em formato JSON (um registro por linha). Os arquivos são rotacionados a cada 10 MB, com até 10 arquivos anteriores; o histórico não é apagado ao reiniciar o programa.
