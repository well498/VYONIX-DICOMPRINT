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
| Servidor DICOM | Recepção disponível; impressão DICOM na Fase 5 |
| Impressoras | Disponível |
| Trabalhos de impressão | Disponível |
| Regras automáticas | Não implementado — Fase 6 |
| Calibração | Disponível |
| Perfis de impressão | Disponível (regras automáticas na Fase 6) |
| Histórico | Disponível |
| Configurações | Disponível |
| Licença | Disponível (somente identificação da instalação) |
| Sobre o VYONIX | Disponível |

As páginas não implementadas mostram o escopo planejado e não executam nenhuma operação.

## 3. Dashboard

Atualizado automaticamente a cada 5 segundos, com dados lidos do banco local:

- **Indicadores:** trabalhos recebidos, em fila, enviados à impressão e com falha nas últimas 24 horas.
- **Serviços:** estado real do servidor de recepção (Storage SCP); Print SCP e Serviço Windows aparecem como *Não implementado*, com a fase prevista.
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

Nesta versão, o servidor funciona enquanto o VYONIX estiver aberto.

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

Um perfil define papel, orientação, layout, cópias, margens, espaçamento, resolução, cabeçalho, rodapé, informações do exame e numeração. Campos "não definir" herdam o valor do próximo nível. Precedência: padrão do sistema < perfil da impressora < perfil da modalidade < perfil do equipamento < escolha manual.

**Dados do paciente:** nome e ID no cabeçalho ficam desligados por padrão (LGPD). Quando ligados, são lidos do arquivo DICOM só no momento da impressão; não vão para o banco, os logs nem o nome do documento no spooler.

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

Mostra o **ID da instalação**, que será usado para solicitar a licença quando o licenciamento offline for entregue (Fase 8). Nesta versão nenhum recurso é bloqueado por licença.

## 10. Sobre o VYONIX

Versão, etapa de desenvolvimento, pastas de dados em uso e componentes de terceiros.

## 11. Logs

Os logs ficam em `%LOCALAPPDATA%\VYONIX\DICOM Print\logs\vyonix-ui.log`, em formato JSON (um registro por linha). Os arquivos são rotacionados a cada 10 MB, com até 10 arquivos anteriores; o histórico não é apagado ao reiniciar o programa.
