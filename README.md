# VYONIX DICOM Print

*Precisão em cada imagem.*

Plataforma de gerenciamento de impressão de imagens médicas DICOM para Windows 10 e 11 (64 bits).

> **Versão de desenvolvimento 1.0.0.dev3.**
> Este software **não está validado para uso clínico** e **não possui declaração de conformidade DICOM**.
> Recepção DICOM, impressão e licenciamento ainda não estão implementados (ver "Situação").

## Situação

| Área | Estado |
|---|---|
| Arquitetura, contratos entre módulos, modelo de dados completo (migração v1) | ✅ Fase 1 |
| Diretórios em ProgramData/LocalAppData, logs JSON rotativos com redação de dados de paciente | ✅ Fase 1 |
| Configurações validadas e auditadas, histórico de alterações, eventos com filtros e exportação CSV | ✅ Fase 1 |
| Interface: Dashboard, Configurações, Histórico, Licença (ID da instalação), Sobre; tema claro/escuro | ✅ Fase 1 — **validar no Windows** |
| Equipamentos, Storage SCP (C-ECHO/C-STORE), controle de acesso administrativo | Fase 2 |
| Pipeline de imagem, pré-visualização, calibração | Fase 3 |
| Impressoras Windows, layouts, fila persistente | Fase 4 |
| DICOM Print SCP e declaração de conformidade | Fase 5 |
| Motor de regras e perfis | Fase 6 |
| Serviço Windows, IPC, bandeja | Fase 7 |
| Licenciamento offline, instalador, distribuição | Fase 8 |

As páginas das áreas não implementadas existem no menu e informam explicitamente a fase prevista; nada é simulado.

A arquitetura completa (diagramas, modelo de dados, dependências, riscos e plano por fases) está em
[`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

## Requisitos

* Para usar: Windows 10 64 bits (1809+) ou Windows 11.
* Para desenvolver: Python 3.12 (64 bits) — <https://www.python.org/downloads/windows/>

## Instalação (desenvolvimento)

No PowerShell, dentro da pasta do projeto:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

Para gerar o ícone e os PDFs da release, use um Python 3.12 separado com `requirements-tools.txt`.

## Execução

```powershell
# Interface gráfica
python -m app

# Verificação sem interface: cria pastas, migra o banco e imprime um resumo (código 0 = ok)
python -m app --check

# Pasta de dados isolada (recomendado em desenvolvimento e testes)
python -m app --data-dir C:\vyonix-dev

# Logs também no terminal, em nível DEBUG
python -m app --console-log --log-level DEBUG
```

Códigos de saída: `0` ok · `2` falha de inicialização (ex.: banco corrompido) · `3` dependência ausente · `4` interface já aberta.

## Onde ficam os dados

| Conteúdo | Pasta |
|---|---|
| Banco, imagens, cache, backups, logs do serviço | `%ProgramData%\VYONIX\DICOM Print\` |
| Logs da interface, exportações | `%LOCALAPPDATA%\VYONIX\DICOM Print\` |
| Com `--data-dir` ou `VYONIX_HOME` | `<pasta>\machine\` e `<pasta>\user\` |

Nada é gravado na pasta do programa. Antes de qualquer migração de esquema, um backup do banco é criado em `backups\`.

## Testes

```powershell
python -m pytest            # ou: python -m unittest discover -s tests -t .
```

* 60 testes cobrem caminhos, migrações, integridade do banco, logs, redação de dados de paciente,
  validação e auditoria de configurações, eventos e a máquina de estados de trabalhos.
* `tests/test_ui_smoke.py` abre a janela principal em modo *offscreen* e percorre as 12 páginas;
  ele é ignorado automaticamente quando o PySide6 não está instalado.

### Roteiro manual da Fase 1 (Windows)

1. `python -m app --data-dir C:\vyonix-dev` — a janela abre com o cabeçalho VYONIX e 12 itens no menu.
2. Dashboard: serviços aparecem como "Não implementado" com a fase prevista; contadores em 0; alerta de uso clínico.
3. Configurações: digite `CT\1` no AE Title e salve — o campo é marcado com erro e nada é gravado.
   Use `CLINICA`, porta `104`, salve — aparece o aviso de porta privilegiada e de reinício.
4. Altere o tema para "Escuro" e salve — a interface muda na hora.
5. Histórico → Alterações administrativas mostra as mudanças com usuário e horário; Eventos → Exportar CSV abre no Excel.
6. Licença mostra o ID da instalação; o mesmo ID aparece em `python -m app --check --data-dir C:\vyonix-dev`.
7. Tente abrir uma segunda janela — o sistema informa que já está aberto.
8. Feche a interface e confira `C:\vyonix-dev\user\logs\vyonix-ui.log` (JSON por linha, sem dados de paciente).

## Estrutura

```text
app/
  core/        contratos (Protocol) e DTOs entre módulos; erros
  utils/       caminhos, tempo UTC, logging estruturado, recursos
  security/    validadores e redação de dados de paciente
  database/    conexão SQLite, migrações, repositórios
  services/    fachadas usadas pela interface (configurações, dashboard)
  jobs/        máquina de estados dos trabalhos
  ui/          PySide6 — única camada que importa Qt
  dicom/ imaging/ printing/ rules/ devices/ licensing/ service/   (fases 2–8)
assets/        logotipo e ícone VYONIX (SVG originais)
docs/          arquitetura
tests/         testes automatizados
```

## Marca

VYONIX é uma identidade visual própria, sem vínculo com outras empresas. A disponibilidade jurídica e
comercial do nome (INPI, domínios) deve ser verificada antes da distribuição.
