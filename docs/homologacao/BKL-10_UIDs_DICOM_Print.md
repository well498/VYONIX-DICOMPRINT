# BKL-10 — UIDs DICOM no VYONIX DICOM Print: diagnóstico e proposta para aprovação

Situação: **aguardando aprovação expressa do proprietário**. A correção está somente na branch
`bkl-10-uid-root` (commit `caeab74`), sem merge em `develop` e sem alterar a versão em testes laboratoriais.
Em `develop` entraram apenas testes de caracterização (`tests/test_uid_handling.py`, commit `a43ff48`), sem
mudança no código do Print.

## 1. Descrição

O DICOM Print cria UIDs com a raiz `1.2.826.0.1.3680043.8.498`, registrada para o projeto pydicom e não para a
VYONIX. Os UIDs gerados assim chegam a 64 caracteres, o limite do padrão.

## 2. Diagnóstico

| Ponto | Arquivo | O que acontece hoje |
|---|---|---|
| C-STORE recebido | `app/dicom/storage.py` | O arquivo é gravado byte a byte e os UIDs da modalidade são mantidos. UID inválido é recusado com 0xA900. Repetição idêntica é tratada como duplicata; mesmo SOP com outro conteúdo gera conflito e o original é mantido. |
| Film Session, Film Box, Presentation LUT | `app/dicom/print_model.py` | Usa o UID informado pela modalidade no N-CREATE. Só gera um quando a modalidade não informa (PS3.4 H), com a raiz do pydicom. |
| Image Box | `print_model.py` | Sempre gerado pelo SCP, com a raiz do pydicom. |
| Imagens Secondary Capture derivadas do filme | `app/dicom/print_intake.py` | SOP e série (uma por filme) gerados com a raiz do pydicom. Classe SOP SC padrão `1.2.840.10008.5.1.4.1.1.7`. |
| Estudo por associação | `app/dicom/print_scp.py` | Gerado com a raiz do pydicom. |
| Filme de teste da interface | `app/ui/application.py` | Usa `generate_uid()` padrão, que também cai na raiz do pydicom. |
| Imagem do autoteste | `app/imaging/selftest.py` | Mesma situação do filme de teste. |
| Encaminhamento ao PACS | — | Não existe nesta versão: o Print não envia objetos ao PACS. |

**Causa raiz:** a geração de UIDs não está centralizada, e todos os pontos de geração usam a raiz de
terceiros, de forma explícita ou pelo padrão do pydicom.

**Unicidade:** está garantida hoje. O sufixo vem de UUID4.

**Falha funcional:** nenhuma foi observada.

**Regras DICOM aplicáveis:**
- PS3.5 §9.1: até 64 caracteres, só dígitos e pontos, sem zero à esquerda nos componentes.
- PS3.5 §9.2: a raiz deve pertencer à organização.
- PS3.5 §B.2: a forma `2.25.<UUID>` dispensa raiz registrada.

**Achado secundário:** a validação aceita componentes com zero à esquerda, por exemplo `1.2.03.4`. Recusar esses
UIDs quebraria equipamentos antigos. Proposta: continuar aceitando e registrar um aviso no log.

**Rastreabilidade:** o DICOM Print transmite só pixels, sem os UIDs dos exames de origem. Por isso o objeto
derivado não tem como referenciar o original. A rastreabilidade fica no registro do trabalho de impressão e da
associação (AE, IP, equipamento, horário). Isso não muda com a correção.

## 3. Proposta (implementada na branch)

- Criar `app/dicom/uids.py` com:
  - `new_uid()`, que gera `2.25.<UUID>` com até 44 caracteres, sem raiz de terceiros, único sem coordenação e
    funcionando offline;
  - `is_strict()`, que verifica a conformidade com a PS3.5 §9.1.
- Trocar todos os pontos de geração listados acima para `new_uid()`.
- Manter sem alteração:
  - os UIDs recebidos;
  - os UIDs que a modalidade informa no N-CREATE;
  - as classes SOP padronizadas;
  - as regras de impressão (layout, cópias, orientação, papel, densidade);
  - o banco de dados, sem migração.
- `storage.py`: registrar um aviso no log quando um UID recebido tiver zero à esquerda. O UID continua aceito e
  é gravado sem alteração.
- Identificadores do serviço de impressão (número do trabalho, fila, impressora) são separados dos UIDs DICOM e
  não mudam.

## 4. Testes (dados sintéticos e simuladores pynetdicom em 127.0.0.1, impressora virtual PDF)

| # | Cenário | Onde | Resultado local |
|---|---|---|---|
| 1 | Recepção com UIDs válidos | `test_uid_handling.ReceivedUids` | aprovado |
| 2 | Preservação byte a byte e dos UIDs no banco | idem, inclusive C-STORE de ponta a ponta | aprovado |
| 3 | Geração só nos objetos novos; UIDs informados pela modalidade mantidos | `PrintGeneratedUids` | aprovado |
| 4 | Unicidade (20 000 e 50 000 gerações; SOP, Image Box, série, estudo) | `PrintGeneratedUids`, `test_uid_root.Generator` | aprovado |
| 5 | UIDs inválidos (letras, mais de 64 caracteres, estudo vazio) recusados com 0xA900, nada gravado | `ReceivedUids` | aprovado |
| 6 | Recepção repetida (duplicata) e conflito de conteúdo (original mantido) | `ReceivedUids` | aprovado |
| 7 | Regras de impressão (layout 2x2, 2 cópias, trabalho concluído) | `PrintGeneratedUids`, `test_uid_root.PrintFlow` | aprovado |
| 8 | Compatibilidade com o PACS | Não se aplica: o Print não encaminha ao PACS. A entrada do PACS da plataforma aceita qualquer UID válido (`tests_platform`). | — |
| 9 | Fluxo completo sem resolução de nomes nem conexão TCP externa | `test_uid_handling.Offline` | aprovado |
| 10 | Regressão: suíte completa do Print | `tests/` | `develop`: 330 aprovados, 26 ignorados; branch: 335 aprovados, 26 ignorados |
| — | Interface Windows na branch | `ui-windows` (run 40609234009) | em execução |

No teste offline, a descoberta do IP local (`app/utils/net.py`) faz um `connect` UDP que não envia pacotes. Esse
comportamento foi permitido no teste e documentado.

**Nenhum teste físico** (impressora real ou modalidade real) foi feito com a branch. Os ensaios do laboratório
continuam na versão atual.

## 5. Riscos

- **Formato diferente dos UIDs novos** (`2.25.`, mais curtos): o padrão permite, mas um SCU que validasse o
  prefixo seria afetado. Risco baixo; deve ser verificado no laboratório com as modalidades de teste antes da
  adoção.
- **Objetos já gravados** mantêm os UIDs antigos. Não há reescrita nem migração; os dois formatos convivem.
- **Aviso de zero à esquerda:** pode gerar volume de log com equipamentos antigos. Não altera a recepção.

## 6. Reversão

- Antes da aprovação: basta não fazer o merge da branch.
- Depois do merge: `git revert` do commit da correção. Não há mudança de esquema nem de dados, e os UIDs já
  gerados continuam válidos.

## 7. Decisão solicitada

Aprovar o merge de `bkl-10-uid-root` em `develop`, para entrar numa próxima versão de laboratório. Alternativa:
o proprietário obtém uma raiz própria registrada e `new_uid()` passa a usá-la. Nos dois casos, validar no
laboratório antes de qualquer ensaio em campo.
