# Backup e restauração do VYONIX PACS

Backup das **imagens** do PACS, independente do motor DICOM. O backup do **banco** (índice, cadastros, auditoria)
continua sendo feito pelo VYONIX DEPLOY antes de cada atualização; os dois se complementam.

> Ferramenta de desenvolvimento e homologação. Não foi validada em ambiente clínico. O backup contém dados de
> pacientes: grave-o em pasta com acesso restrito (somente administradores e o sistema) e, se for externo, em mídia
> cifrada.

## Comandos (servidor da clínica, como administrador)

```
VyonixPlatform.exe --data "C:\ProgramData\VYONIX\Platform" pacs-backup --dest "E:\Backup\PACS"
VyonixPlatform.exe pacs-verify --src "E:\Backup\PACS"
VyonixPlatform.exe --data "C:\ProgramData\VYONIX\Platform" pacs-restore --src "E:\Backup\PACS"
```

| Comando | O que faz | O que **não** faz |
|---|---|---|
| `pacs-backup` | Copia cada imagem indexada, conferindo o SHA-256 registrado na entrada; incremental (só o que mudou); grava `manifest.json` | Não apaga nada no motor, no índice nem no destino; não copia imagem com integridade violada no motor (ela aparece no relatório e o comando termina com código 1) |
| `pacs-verify` | Confere cada arquivo do backup contra o manifesto (faltando, alterado, sobrando) | Não altera o backup |
| `pacs-restore` | Confere o backup e reenvia pela entrada normal do PACS (validação, SHA-256, índice, auditoria); devolve ao motor arquivos que sumiram com o índice intacto | Não sobrescreve conteúdo divergente; recusa backup adulterado ou incompleto; recusa backup de outra organização |

Todos os comandos que tocam o PACS ficam na auditoria (`pacs.backup.export`, `pacs.backup.restore`).

## Backup automático diário

Ao ativar o PACS, o VYONIX DEPLOY configura o backup diário feito pelo serviço **VyonixWorker**:

* destino padrão `C:\ProgramData\VYONIX\Backups\PACS`; outro destino pela opção `pacs_backup_dir` da
  configuração do DEPLOY (ex.: um segundo disco `E:\VYONIX-Backup`). O padrão fica **no mesmo disco** das imagens:
  protege contra exclusão e corrupção, não contra perda do disco — copie para mídia externa;
* a partir da hora `pacs_backup_hour` (padrão 2, hora local), uma vez por dia; se o servidor estava desligado no
  horário, roda na primeira verificação seguinte (a cada 5 min);
* incremental, conferido contra o manifesto ao final; resultado em `last_run.json` no destino;
* falha (motor parado, disco cheio, integridade violada) fica registrada e é tentada de novo em 1 hora;
* permissões da pasta: só sistema, administradores e `NT SERVICE\VyonixWorker`;
* o monitoramento técnico (`/api/v1/health/detail`, componente `pacs_backup`) indica “atenção” se ainda não houve
  backup, se o último falhou ou se tem mais de 36 h — sem expor o caminho nem dados de pacientes;
* modo cloud: sem backup automático (é por organização, pelo comando `pacs-backup --org`).

Destino em compartilhamento de rede não é suportado nesta versão (a conta virtual do serviço não tem credencial
de rede).

## Verificação contínua da integridade

O VyonixWorker relê, a cada hora, um lote de 500 imagens do motor e confere o SHA-256 registrado na entrada; ao
terminar o acervo, recomeça. Imagem corrompida ou ausente **não é alterada**: fica na auditoria
(`pacs.integrity.failure`), no estado `ProgramData\VYONIX\Platform\pacs\integrity.json` e no monitoramento
(estado “falha”), até ser recuperada pelo backup (`pacs-restore`) — a volta seguinte limpa a pendência.
Teste: `tests_platform/test_pacs_integrity_task.py`.

## Cenários de recuperação testados (dados sintéticos)

| Cenário | Resultado esperado | Teste |
|---|---|---|
| Backup repetido | Só copia o que mudou | `tests_platform/test_pacs_backup.py` |
| Imagem corrompida no motor | Não é copiada; aparece no relatório | idem |
| Backup adulterado ou com arquivo faltando | Verificação aponta; restauração recusada | idem |
| Backup de outra organização | Restauração recusada | idem |
| Armazenamento do motor perdido, índice intacto | Arquivos devolvidos ao motor e religados ao índice | idem; `test_pacs_orthanc.py` (Orthanc real, CI) |
| Motor e índice perdidos | Restauração explícita para a organização recriada | `test_pacs_backup.py` |
| Agendamento diário, incremental, repetição no mesmo dia, falha do motor e nova tentativa, monitoramento | Conforme a seção acima | `tests_platform/test_pacs_backup_task.py` |
| Pasta, permissões e configuração criadas pela ativação no Windows | Pasta criada e componente visível no monitoramento | aceitação 2.9 do DEPLOY (CI Windows) |

## Pendências

Retenção de várias cópias (o backup é um espelho incremental); destino em rede com credencial no cofre;
teste de volume (tempo e espaço para estudos reais).
