# Manual do Usuário

**VYONIX DICOM Print {VERSION}**

> Este manual descreve apenas os recursos presentes nesta versão de homologação. O software não está validado para uso clínico.

## 1. Visão geral da tela

A janela do VYONIX tem três áreas:

- **Cabeçalho** com a marca VYONIX e o slogan *Precisão em cada imagem.*
- **Menu lateral** com 13 itens.
- **Área de conteúdo**, que mostra a página selecionada.

A barra inferior mostra a pasta de dados em uso e o aviso de que a versão não é destinada a uso clínico. Apenas uma janela do VYONIX pode ficar aberta por usuário. Em telas menores que 1320 × 880 (por exemplo, 1366 × 768), a janela abre maximizada.

## 2. Itens do menu nesta versão

| Item | Situação nesta versão |
|---|---|
| Dashboard | Disponível |
| Regras DICOM | Disponível (destinos por AE Title + porta) |
| Servidor DICOM | Disponível (recepção e impressão DICOM) |
| Impressoras | Disponível |
| Trabalhos de impressão | Disponível |
| Regras avançadas | Disponível (condições) |
| Calibração | Disponível |
| Perfis de impressão | Disponível |
| VYONIX Reception | Disponível (endereço do painel e usuários) |
| Histórico | Disponível |
| Configurações | Disponível |
| Licença | Disponível |
| Sobre o VYONIX | Disponível |

Todas as páginas estão implementadas.

## 3. Dashboard

Atualizado automaticamente a cada 5 segundos, com dados lidos do banco local:

- **Indicadores:** trabalhos recebidos, em fila, enviados à impressão e com falha nas últimas 24 horas.
- **Serviços:** estado real do servidor de recepção (Storage SCP); estado real do Print SCP e da fila de impressão; Serviço Windows aparece como *Não implementado* (Fase 7).
- **Configuração DICOM:** AE Title, endereço e porta configurados.
- **Equipamentos, Impressora selecionada, Alertas operacionais e Falhas recentes.**

## 4. Regras DICOM (antigo "Equipamentos DICOM")

Cada **Regra DICOM** é um destino: o equipamento envia para o IP deste computador, com o **AE Title de destino** e a **porta** da regra; o IP do equipamento não é necessário (Calling AE Title e IP/faixa são restrições opcionais, em *Restrições de origem*). Após salvar, a tela **Configurar destino no equipamento** mostra os dados a digitar na modalidade. Detalhes no *Guia de Configuração DICOM*. O texto abaixo descreve os demais recursos de cada regra (configurações de impressão, calibração, regras avançadas).


Lista os equipamentos que podem enviar imagens, com AE Title, IP, autorização, último contato e situação.

- **Adicionar / Editar:** abre o cadastro (nome, AE Title, modalidade, IP, porta, unidade, setor, fabricante, modelo, observações). Erros aparecem ao lado de cada campo.
- **Autorizar / bloquear:** libera ou impede o envio de imagens sem apagar o cadastro.
- **Testar conexão (C-ECHO):** o VYONIX chama o equipamento no IP e porta cadastrados e mostra o tempo de resposta.
- **Histórico:** eventos do equipamento (conexões, recusas, alterações).
- **Remover:** exclui o cadastro; se o equipamento já enviou imagens, ele é apenas desativado, para preservar o histórico.
- **Importar / Exportar:** copia os cadastros entre instalações em um arquivo JSON.
- **Pesquisar:** filtra por nome, modalidade, AE Title, IP, unidade, fabricante ou modelo.
- **Impressora associada** e **Perfil de impressão** podem ser escolhidos no cadastro.

Detalhes de configuração dos equipamentos estão no *Guia de Configuração DICOM*.

### 4.1 Configurações de impressão do equipamento

Selecione o equipamento e clique em **Configurações de impressão…**. Cada equipamento tem configurações **só dele**: duas tomografias podem usar papel, layout e calibração completamente diferentes, e alterar uma nunca muda a outra.

| Campo | Observação |
|---|---|
| Impressora, papel, orientação, layout (inclusive personalizado, até 8 × 8), cópias | "— herdar —" usa o próximo nível da hierarquia |
| Margens, espaçamento, margem adicional | em mm |
| Inverter escala de cinza | |
| Cabeçalho BMP / Rodapé BMP, espaços entre cabeçalho/rodapé e imagens | as artes são as mesmas para todos (ver 7.1); só a aplicação é individual |
| Impressão automática | "Não" deixa os trabalhos retidos até serem liberados (impressão manual) |
| Prioridade do pedido DICOM Print | equipamento prevalece / pedido prevalece / ignorar o pedido |
| Perfil de calibração da impressora | níveis de preto/branco, escala e deslocamento definidos na página Calibração |

- **Resultado final e origem:** mostra o valor final de cada configuração e de onde ele veio.
- **Pré-visualizar página:** monta a página exatamente como será impressa (com a última imagem recebida do equipamento ou com o padrão de teste) e mostra avisos, como resolução insuficiente.
- **Versões anteriores:** toda gravação cria uma versão; **Restaurar versão selecionada** volta a qualquer uma.
- **Duplicar de outro equipamento:** copia os valores (cópia independente, sem vínculo).
- **Comparar com…:** tabela lado a lado das configurações de dois equipamentos, com as diferenças marcadas.

**Hierarquia** (da maior para a menor prioridade): regras do equipamento → configurações gerais do equipamento → pedido DICOM Print (conforme a política) → perfil padrão da modalidade → configurações globais do VYONIX. Com a política "pedido prevalece", o pedido DICOM fica acima de tudo; com "ignorar", ele não é usado. Uma escolha manual (ex.: reimprimir com outra impressora) vale só para aquele trabalho.

### 4.2 Regras do equipamento

**Regras do equipamento…** abre as regras que valem só para ele. Cada regra tem condições e prioridade próprias e pode definir impressora, papel, orientação, layout, cópias, margens, espaçamento, brilho, contraste, gama, inversão, cabeçalho, rodapé, impressão automática ou manual, prioridade do pedido DICOM Print e perfil de calibração. É possível criar, editar, duplicar, ativar/desativar e excluir; a página **Regras automáticas** também importa, exporta e restaura versões anteriores.

### 4.3 Calibração de imagem

**Calibração de imagem…** (também em Calibração → *Calibração de imagem por equipamento*). A janela abre mesmo sem nenhuma imagem recebida.

1. **Selecionar imagem para calibração:** *Imagem padrão de teste* (escala de cinza numerada, gradiente, áreas claras e escuras, barras, círculo, quadrado e triângulo, régua de 10 cm), *Receber de equipamento DICOM* (lista as imagens recebidas daquele equipamento, com data, modalidade, identificação técnica e miniatura — sem dados do paciente) ou *Abrir imagem do computador* (DICOM com ou sem extensão, JPG, PNG, BMP).
2. **Ajustes:** brilho, contraste e gama de **−5,0 a +5,0** (0,0 = neutro). Cada controle tem seta para baixo/para cima (±0,5), campo numérico, barra deslizante, valor atual, botão ↺ (restaura o valor salvo) e marca ● de alteração não salva. O campo numérico aceita passo fino de 0,1 ou 0,2. Teclado: Ctrl+1/2/3 escolhe o controle, Ctrl+↑/↓ = ±0,5, PgUp/PgDn no controle = ±0,5.
3. **Pré-visualização:** *Imagem Original | Imagem Ajustada* lado a lado ou antes/depois, zoom (ajustar, 50, 100, 200 %), valores atuais e indicador "Processando…". A imagem ajustada é gerada em segundo plano pelo **mesmo processamento da impressão** (inclusive a calibração da impressora usada pelo equipamento); a original não é alterada.
4. **Salvar no perfil do equipamento** (pede confirmação antes de substituir uma calibração existente), **Restaurar ajustes**, **Cancelar sem salvar**, **Reverter para calibração anterior**.

**Fórmulas** (sobre a imagem normalizada 0–1, em ponto flutuante, antes de virar 8 bits): contraste = ganho 2^(C/5) em torno do cinza médio; brilho = deslocamento de 0,05 × B (±25 % nos extremos); gama γ = 2^(G/5) aplicado como saída = entrada^(1/γ) — gama positivo clareia os tons médios. São parâmetros iniciais de engenharia, a avaliar nos testes de qualidade de impressão.

### 4.4 Teste de calibração 3 × 3 e calibração progressiva

1. Escolha **Comparar** (Gama × Contraste, Brilho × Contraste ou Gama × Brilho; o terceiro fica fixo), o **Incremento** (0,1; 0,2; 0,5 ou 1,0), a impressora e o papel (A4 ou A3).
2. **Pré-visualizar folha** mostra a página inteira; **GERAR E IMPRIMIR TESTE DE CALIBRAÇÃO — 9 IMAGENS** imprime. A folha tem título, equipamento, modalidade, impressora, papel, data e hora, e as nove versões em 3 linhas × 3 colunas (linhas = primeiro parâmetro, colunas = segundo). Cada imagem tem uma faixa própria com `IMAGEM 05 | B +0,5 | C +1,0 | G −0,5`, sem texto sobre a imagem. Perto de −5/+5 os valores são deslocados para continuarem distintos, e a folha avisa.
3. Compare no papel, informe a **melhor imagem** (1–9) e clique em **Aplicar combinação escolhida**: os valores dela viram o novo centro e o incremento passa para o próximo menor.
4. Gere quantas rodadas quiser; o histórico das rodadas (modo, incremento, centro, imagem escolhida, trabalho) fica na janela e no banco.
5. **Salvar no perfil do equipamento** grava o resultado; a versão anterior pode ser recuperada com **Reverter para calibração anterior**.

A escolha visual na folha não comprova qualidade diagnóstica.

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

Ações: **Pré-visualizar página** (as páginas exatamente como serão impressas, com avisos de resolução), **Detalhes** (configurações aplicadas com a origem de cada uma, histórico de estados e imagens), **Reter**, **Liberar**, **Tentar de novo**, **Reprocessar com config. atuais**, **Reimprimir…** (cria um novo trabalho, com outra impressora ou número de cópias se você quiser) e **Cancelar trabalho**.

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

## 5E2. VYONIX Reception

Mostra o endereço do painel da recepção (https://…:8443/), a situação do servidor e os **usuários e perfis** (Administrador, Técnico, Supervisor da recepção, Recepcionista). O uso do painel está no *Manual do VYONIX Reception*.

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

### 7.1 Identidade da Impressão (cabeçalho e rodapé BMP)

Em **Configurações → Identidade da Impressão**: um único `header.bmp` e um único `footer.bmp`, 3000 × 206 px, BMP RGB 24 bits, fundo branco, usados em A4 e A3, retrato e paisagem e em todas as modalidades. Os modelos originais são brancos.

- **Alterar Cabeçalho/Rodapé:** escolha um BMP. Se não tiver 3000 × 206, o VYONIX oferece convertê-lo preservando a proporção (sem deformar nem cortar), centralizado e com o restante em branco. A arte anterior fica guardada como `*.anterior.bmp`.
- **Visualizar** e **Restaurar … Original**.
- No papel, a arte ocupa a largura útil (descontada a área não imprimível informada pelo driver), mantém a proporção 3000:206, fica centralizada e tem espaço reservado — as imagens nunca ficam embaixo dela. A altura impressa varia com a largura disponível; *Altura máxima* limita o tamanho mantendo a proporção.
- Cada equipamento liga ou desliga cabeçalho e rodapé e define espaços e margens adicionais (4.1).
- As artes ficam em `C:\ProgramData\VYONIX\DICOM Print\print_templates` e são preservadas nas atualizações. Arquivo ausente ou corrompido: a página sai sem o elemento e o trabalho registra o aviso.

### 7.2 Backup do banco de dados

Backup automático diário (mantidos os 14 mais recentes) e **Fazer backup agora**. Cada backup é verificado (integridade) ao ser criado. **Como restaurar…** explica a restauração: fechar o VYONIX, parar o serviço e executar `Vyonix.exe --restore-backup <arquivo>` como administrador — o banco atual é guardado antes da troca.

## 8. Histórico

**Eventos:** registros operacionais e de auditoria (inicialização, encerramento, alterações de configuração, falhas).

- Filtre por período, categoria, nível mínimo e texto; clique em **Filtrar**.
- São exibidos até 500 eventos; o rodapé informa o total encontrado.
- **Exportar CSV** gera um arquivo separado por ponto e vírgula, que abre diretamente no Excel.

**Alterações administrativas:** lista cada configuração alterada, com valor anterior, novo valor, usuário e motivo.

Os horários são mostrados no fuso horário do computador e armazenados em UTC. Nomes, IDs e outros dados de pacientes são mascarados automaticamente nos eventos e logs.

## 9. Licença

O licenciamento é **offline**: o VYONIX nunca se comunica com a internet. Detalhes completos (políticas, DEMO, Time Integrity, limites) estão em *Licenciamento e Ativação*.

Na primeira abertura, sem licença, aparece a **tela de ativação** com quatro botões: **Iniciar demonstração de 5 dias**, **Ativar licença comercial**, **Exportar solicitação** e **Visualizar Hardware ID**. A mesma página fica no menu **Licença**, que mostra ainda:

- a situação (licença válida, demonstração com o tempo restante, vencida, de outro computador, de outra instalação, revogada ou funções suspensas) e o motivo;
- tipo, edição, cliente, License ID, emissão, vencimento, recursos e quantidades de equipamentos e impressoras autorizados;
- VYONIX Hardware ID, VYONIX Installation ID, componentes considerados, situação do TPM e do Time Integrity;
- **Exportar diagnóstico…**, **Importar revalidação…**, **Importar lista de revogação…** e **Remover licença**;
- as impressoras que ocupam as vagas da licença (**Liberar vaga** com a senha de administrador);
- o histórico das licenças desta instalação e o histórico de integridade temporal.

Para ativar: **Exportar solicitação** (escolha o motivo) → envie o arquivo `.vyreq` ao administrador → importe o `.vylic` recebido em **Ativar licença comercial** (exige a senha de administrador, se definida).

Sem licença válida nem demonstração ativa, **recepção DICOM, impressão, Print SCP e regras ficam suspensos**; o restante do programa funciona e as configurações são preservadas. O Painel avisa antes do vencimento (15 dias; 24 horas na demonstração). Nas versões de desenvolvimento (`.dev`), a situação é exibida, mas nada é suspenso.

## 10. Sobre o VYONIX

Versão, etapa de desenvolvimento, pastas de dados em uso e componentes de terceiros.

## 11. Logs

Os logs ficam em `%LOCALAPPDATA%\VYONIX\DICOM Print\logs\vyonix-ui.log`, em formato JSON (um registro por linha). Os arquivos são rotacionados a cada 10 MB, com até 10 arquivos anteriores; o histórico não é apagado ao reiniciar o programa.
