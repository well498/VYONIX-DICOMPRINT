# Manual do Usuário

**VYONIX DICOM Print {VERSION}**

> Este manual descreve apenas os recursos presentes nesta versão de homologação (Fase 1 — Fundação). O software não está validado para uso clínico.

## 1. Visão geral da tela

A janela do VYONIX tem três áreas:

- **Cabeçalho** com a marca VYONIX e o slogan *Precisão em cada imagem.*
- **Menu lateral** com 12 itens.
- **Área de conteúdo**, que mostra a página selecionada.

A barra inferior mostra a pasta de dados em uso e o aviso de que a versão não é destinada a uso clínico. Apenas uma janela do VYONIX pode ficar aberta por usuário.

## 2. Itens do menu nesta versão

| Item | Situação nesta versão |
|---|---|
| Dashboard | Disponível |
| Equipamentos DICOM | Não implementado — previsto na Fase 2 |
| Servidor DICOM | Não implementado — Fases 2 e 5 |
| Impressoras | Não implementado — Fase 4 |
| Trabalhos de impressão | Não implementado — Fase 4 |
| Regras automáticas | Não implementado — Fase 6 |
| Calibração | Não implementado — Fase 3 |
| Perfis de impressão | Não implementado — Fases 4 e 6 |
| Histórico | Disponível |
| Configurações | Disponível |
| Licença | Disponível (somente identificação da instalação) |
| Sobre o VYONIX | Disponível |

As páginas não implementadas mostram o escopo planejado e não executam nenhuma operação.

## 3. Dashboard

Atualizado automaticamente a cada 5 segundos, com dados lidos do banco local:

- **Indicadores:** trabalhos recebidos, em fila, enviados à impressão e com falha nas últimas 24 horas. Nesta versão permanecem em zero, pois a recepção e a impressão ainda não existem.
- **Serviços:** Storage SCP, Print SCP e Serviço Windows aparecem como *Não implementado*, com a fase prevista.
- **Configuração DICOM:** AE Title, endereço e porta configurados.
- **Equipamentos, Impressora selecionada, Alertas operacionais e Falhas recentes.**

## 4. Configurações

As configurações estão agrupadas em Instalação, DICOM — Recepção, DICOM — Impressão, Fila de impressão, Retenção de dados, Interface e Diagnóstico.

1. Altere os campos desejados.
2. Clique em **Salvar**. Todos os valores são validados antes de qualquer gravação.
3. Se algum valor for inválido, o campo é destacado com a explicação e nada é gravado.

Regras de validação principais:

- **AE Title:** até 16 caracteres ASCII imprimíveis, sem barra invertida; espaços nas extremidades são removidos.
- **Porta:** de 1 a 65535. Portas abaixo de 1024 (como 104) geram aviso sobre privilégios e firewall.
- **Endereço IP:** IPv4 ou IPv6 válido; `0.0.0.0` significa todas as interfaces.
- Recepção e impressão DICOM, quando habilitadas, devem usar portas e AE Titles diferentes.

Campos marcados com ⟳ só terão efeito quando os serviços DICOM existirem e forem reiniciados.

Outros botões:

- **Descartar alterações:** recarrega os valores gravados.
- **Restaurar padrões:** volta todas as configurações aos valores de fábrica (com confirmação).
- **Exportar / Importar:** salva ou carrega as configurações em um arquivo JSON, útil para replicar a configuração em outro computador. O ID da instalação nunca é exportado.

O **tema** (Seguir o Windows, Claro, Escuro) e o **nível de log** são aplicados imediatamente.

Toda alteração é registrada com usuário do Windows, data, hora, valor anterior e novo valor.

## 5. Histórico

**Eventos:** registros operacionais e de auditoria (inicialização, encerramento, alterações de configuração, falhas).

- Filtre por período, categoria, nível mínimo e texto; clique em **Filtrar**.
- São exibidos até 500 eventos; o rodapé informa o total encontrado.
- **Exportar CSV** gera um arquivo separado por ponto e vírgula, que abre diretamente no Excel.

**Alterações administrativas:** lista cada configuração alterada, com valor anterior, novo valor, usuário e motivo.

Os horários são mostrados no fuso horário do computador e armazenados em UTC. Nomes, IDs e outros dados de pacientes são mascarados automaticamente nos eventos e logs.

## 6. Licença

Mostra o **ID da instalação**, que será usado para solicitar a licença quando o licenciamento offline for entregue (Fase 8). Nesta versão nenhum recurso é bloqueado por licença.

## 7. Sobre o VYONIX

Versão, etapa de desenvolvimento, pastas de dados em uso e componentes de terceiros.

## 8. Logs

Os logs ficam em `%LOCALAPPDATA%\VYONIX\DICOM Print\logs\vyonix-ui.log`, em formato JSON (um registro por linha). Os arquivos são rotacionados a cada 10 MB, com até 10 arquivos anteriores; o histórico não é apagado ao reiniciar o programa.
