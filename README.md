# VYONIX DICOM Print

*Precisão em cada imagem.*

Plataforma de gerenciamento de impressão de imagens médicas DICOM para Windows 10 e 11 (64 bits).

> **Versão 1.0.0 (revisão 4) para homologação — 8 fases, prompt atualizado, prompt definitivo (licenciamento,
> TPM, DEMO, Time Integrity, License Manager), arquitetura DICOM simplificada com o painel VYONIX Reception e
> licenciamento comercial por assinatura com o VYONIX License Server.**
> Este software **não está validado para uso clínico**. A declaração de conformidade DICOM incluída é de homologação
> e foi verificada com equipamento simulado (pynetdicom), não com equipamentos reais.

## Situação

| Área | Estado | Verificação automatizada no Windows (CI) |
|---|---|---|
| Fundação: banco, migrações, logs com redação de PHI, configurações auditadas | ✅ Fase 1 | testes + instalador |
| Equipamentos, Storage SCP (C-ECHO/C-STORE), senha de administrador, retenção | ✅ Fase 2 | SCP real em loopback |
| Decodificação (incl. RLE, JPEG, JPEG 2000, JPEG-LS), pipeline, calibração | ✅ Fase 3 | autoteste de codecs |
| Layout, impressoras Windows (GDI/spooler), VYONIX PDF, fila persistente, perfis | ✅ Fase 4 | Microsoft Print to PDF |
| DICOM Print SCP (Basic Grayscale/Color Print Management) | ✅ Fase 5 | SCU simulado |
| Regras automáticas com prioridade e simulação | ✅ Fase 6 | testes |
| Serviço Windows, named pipe autenticado, bandeja | ✅ Fase 7 | serviço instalado, C-ECHO, impressão pelo serviço |
| Licenciamento v2: Hardware ID, Installation ID, TPM, Time Integrity, DEMO 120 h | ✅ | instalar/atualizar/desinstalar/reinstalar, DEMO, chave não oficial recusada |
| VYONIX License Manager (portátil + instalador opcional), banco próprio | ✅ | autoteste dos dois modos com a solicitação real |
| Regras DICOM por porta + Called AE (sem IP obrigatório), várias portas | ✅ | C-STORE/C-ECHO reais em testes; serviço instalado |
| VYONIX Reception (HTTPS, perfis, impressão sob demanda, duplicidade, retirada, relatórios) | ✅ | API testada; painel servido pelo serviço instalado |
| Assinatura comercial: estados, carência, suspensão controlada, reativação, autorizações assinadas | ✅ | 30 testes obrigatórios (c01–c30) |
| VYONIX License Server (API HTTPS, admin, tolerância, revogação online) e Gestão Comercial no License Manager | ✅ | autoteste do executável, servidor HTTPS em execução |
| Banco Inter (cobrança, consulta, conciliação) | ⚠️ preparado | testado contra reprodução local da API; sandbox do Inter pendente |

Quatro artefatos: `VYONIX_DICOM_Print_Setup_v1.0.0_x64.exe` (clientes), `VYONIX_License_Manager.exe`,
`VYONIX_License_Manager_Setup.exe` e `VYONIX_License_Server.exe` (somente fornecedor). Código compartilhado:
o protocolo [`vyonix_protocol/`](vyonix_protocol) e a gestão comercial [`vyonix_commercial/`](vyonix_commercial)
(o VYONIX instalado usa apenas o cálculo de estados). Detalhes: `docs/release/Licenciamento_e_Ativacao.md`,
`docs/release/Manual_Licenciamento_Comercial.md`, `docs/release/Manual_License_Server.md`,
`docs/release/Integracao_Banco_Inter.md` e `docs/release/Manual_License_Manager.md`.

Não verificado: equipamentos DICOM reais, impressão em papel em impressoras físicas, Windows 10/11 limpos
(o CI usa Windows Server 2022), assinatura digital do instalador.

A arquitetura completa (diagramas, modelo de dados, dependências, riscos e plano por fases) está em
[`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

Continuidade do projeto (Prompt Mestre §53–§55, §64): estado, backlog e registro de sessões em
[`VYONIX_PROJECT_STATE.md`](VYONIX_PROJECT_STATE.md); rastreabilidade de requisitos em
[`VYONIX_REQUIREMENTS_TRACEABILITY.md`](VYONIX_REQUIREMENTS_TRACEABILITY.md); decisões em [`docs/adr/`](docs/adr/README.md).

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
license_manager/   VYONIX License Manager (emissão e Gestão Comercial; não vai às clínicas)
license_server/    VYONIX License Server (validação online; não vai às clínicas)
vyonix_protocol/   formatos e assinatura de licenças/autorizações (compartilhado)
vyonix_commercial/ estados comerciais, assinaturas, pagamentos e cobrança (compartilhado)
assets/        logotipo e ícone VYONIX (SVG originais)
docs/          arquitetura
tests/         testes automatizados
```

## Marca

VYONIX é uma identidade visual própria, sem vínculo com outras empresas. A disponibilidade jurídica e
comercial do nome (INPI, domínios) deve ser verificada antes da distribuição.
