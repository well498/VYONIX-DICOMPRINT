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

## Cenários de recuperação testados (dados sintéticos)

| Cenário | Resultado esperado | Teste |
|---|---|---|
| Backup repetido | Só copia o que mudou | `tests_platform/test_pacs_backup.py` |
| Imagem corrompida no motor | Não é copiada; aparece no relatório | idem |
| Backup adulterado ou com arquivo faltando | Verificação aponta; restauração recusada | idem |
| Backup de outra organização | Restauração recusada | idem |
| Armazenamento do motor perdido, índice intacto | Arquivos devolvidos ao motor e religados ao índice | idem; `test_pacs_orthanc.py` (Orthanc real, CI) |
| Motor e índice perdidos | Restauração explícita para a organização recriada | `test_pacs_backup.py` |

## Pendências

Agendamento automático do backup e retenção de cópias pelo DEPLOY; destino em rede com credencial no cofre;
teste de volume (tempo e espaço para estudos reais).
