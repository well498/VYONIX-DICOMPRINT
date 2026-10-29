# Plano seguro de substituição e revogação das chaves de emissão (BLK-01)

* **Data:** 29/10/2026 · complementa `INC-2026-10-23_chave_vyx-2026-01.md`
* **Situação:** plano. **Nada foi alterado**: nenhuma chave gerada, nenhuma lista aplicada, nenhuma instalação
  afetada, nenhum arquivo apagado. Cada passo irreversível ou que afeta instalações tem aprovação explícita.
* **Escopo:** chaves `vyx-2026-01` (emissão: licenças, autorizações, revalidações, revogações) e `vyx-srv-2026-01`
  (License Server: autorizações). Afetam o DICOM Print, o VYONIX Core (mesma lista `app/licensing/keys.py`, usada por
  `vyonix/licensing/service.py`) e o License Server.

## 1. Investigação (29/10)

| Achado | Evidência | Consequência |
|---|---|---|
| A chave privada cifrada **e** o arquivo com a frase-senha de `vyx-2026-01` continuam juntos na pasta temporária da sessão de desenvolvimento | `scratchpad/keys/vyx-2026-01.private.pem` + `vyx-2026-01.passphrase.txt` (conteúdo não lido nesta investigação) | Quem tiver acesso a esta área consegue assinar licenças aceitas pelo produto |
| O mesmo vale para `vyx-srv-2026-01` (PEM + arquivo de frase-senha) | `scratchpad/keys/vyx-srv-2026-01.*` | A exposição da chave do License Server, antes "possível", passa a ser **considerada confirmada** (escopo: só autorizações de uso) |
| Cópias adicionais da PEM de `vyx-2026-01` | `scratchpad/r3/vyx-2026-01.private.pem` | Mais um local a destruir |
| O anexo de 23/10 com a frase-senha continua entre os anexos da conversa | 1 anexo de texto com frase-senha | Fora do controle do desenvolvimento; tratar como exposto |
| Repositório e pacotes | Varredura `tools/scan_private_keys.py` a cada build; histórico sem chave real | Sem chave privada distribuída |
| Restrição de chave (`RESTRICTED_KEYS`) | Vazia em `app/licensing/keys.py` | Hoje documentos forjados com `vyx-2026-01` **são aceitos** por todas as versões |
| Ferramenta de rotação | `tools/apply_key_rotation.py` + `tests/test_key_rotation_tool.py` | Pronta; precisa da chave pública nova e da lista de documentos legítimos |
| Dependência do License Manager | Recuperação da senha adiada por decisão do proprietário (BLK-12) | Os passos 2–3 do incidente (nova chave e lista exportada) ficam parados |

## 2. Princípios

1. A chave privada nova nasce **só** no computador do fornecedor e a frase-senha nunca sai de lá.
2. Nenhuma instalação perde a licença legítima: a chave antiga é **restrita** a uma lista de documentos, não removida.
3. Toda mudança chega aos clientes por uma **atualização oficial** (aprovação de publicação); quem não atualiza fica
   como está (sem efeito colateral, mas também sem a proteção).
4. Revogações assinadas pela chave antiga também passam pela lista: uma revogação forjada não derruba licença legítima.
5. Cada passo tem como desfazer, exceto a destruição de cópias e a aposentadoria definitiva (marcados).

## 3. Caminhos para os passos 2–3 (escolha do proprietário)

| Caminho | Como | Prós | Contras |
|---|---|---|---|
| **A — License Manager atual** | Recuperar o acesso (BLK-12), gerar `vyx-2026-02` e exportar a lista de documentos legítimos de `vyx-2026-01` | Lista completa e auditada | Depende da recuperação de senha adiada |
| **B — License Manager novo + lista pelas instalações** | Instalar o License Manager num computador **offline do fornecedor**, gerar `vyx-2026-02` lá; montar a lista de documentos legítimos a partir dos arquivos de licença das instalações conhecidas (laboratório e homologação), com uma ferramenta somente leitura que calcula os SHA-256 | Não depende da senha antiga | Documento legítimo que não estiver nas instalações conhecidas seria recusado após a atualização — só é seguro se o proprietário confirmar que **não há** licença comercial em clientes (BLK-05: nenhuma publicação comercial até hoje) |
| **C — Só a chave nova, sem restrição** | Acrescentar `vyx-2026-02` e passar a emitir com ela; manter `vyx-2026-01` aceita | Simples | **Não fecha** o risco: forjados com a chave antiga continuam aceitos. Não recomendado |

**Recomendação:** caminho **B** se o proprietário confirmar que não há licenças comerciais em clientes; senão **A**.

## 4. Sequência (com aprovações)

| # | Ação | Reversível? | Afeta instalações? | Aprovação |
|---|---|---|---|---|
| 1 | Proprietário escolhe o caminho (A ou B) e confirma o inventário de licenças emitidas | — | Não | **Sim** |
| 2 | Fornecedor gera `vyx-2026-02` no próprio computador; exporta só a **chave pública** | Sim (não usar a chave) | Não | — |
| 3 | Lista de documentos legítimos de `vyx-2026-01` (exportação do LM ou ferramenta somente leitura sobre os arquivos de licença) | Sim | Não | — |
| 4 | `tools/apply_key_rotation.py --dry-run` e depois sem `--dry-run`; testes; release **candidata** com a chave nova + restrição | Sim (`git revert`) | Não (só artefato de CI) | — |
| 5 | Homologar a candidata no laboratório: licença legítima continua aceita; documento forjado com a chave antiga é recusado; licença nova aceita | Sim | Só a máquina de teste | **Sim** (teste na instalação) |
| 6 | Publicar a atualização e reemitir as licenças com `vyx-2026-02` | Sim (nova versão) | Sim | **Sim** (publicação, BLK-05) |
| 7 | Aposentar `vyx-2026-01` no License Manager (não assinar mais nada com ela) | Parcial | Não | **Sim** |
| 8 | Repetir 2–7 para `vyx-srv-2026-01` (License Server) | Sim | Sim | **Sim** |
| 9 | **Destruir** as cópias de chaves e frases-senha da área de desenvolvimento (lista do item 1) | **Não** | Não | **Sim (irreversível)** |
| 10 | Quando não houver licença ativa da chave antiga, removê-la da lista numa atualização | Sim (nova versão) | Sim | **Sim** |

## 5. Riscos e mitigação durante a espera

* **Janela de risco:** até o passo 6, forjados com `vyx-2026-01` são aceitos. A ação de menor custo que reduz o risco
  já é o **passo 9** (destruir as cópias da área de desenvolvimento), que não depende do License Manager — mas é
  irreversível e por isso aguarda aprovação.
* **Revogação forjada:** com a restrição, revogações assinadas pela chave antiga fora da lista também são recusadas
  (`key_policy_error` vale para todos os tipos de documento).
* **Plataforma em homologação:** a variante de homologação não usa licença comercial; não é afetada.

## 6. Pendências que exigem decisão do proprietário

1. Caminho A ou B (e confirmação de que não há licença comercial em clientes, se B).
2. Autorizar a destruição das cópias da área de desenvolvimento (passo 9, irreversível).
3. Publicação da atualização (passo 6).
