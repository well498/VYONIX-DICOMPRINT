# BLK-01 — Escopo do licenciamento e alternativas para a chave comprometida

* **Data:** 29/10/2026 · complementa `Plano_Substituicao_Revogacao_Chaves_2026-10-29.md`
* **Situação:** análise. **Nenhuma chave foi destruída, substituída, revogada ou gerada; nenhum arquivo foi
  alterado no DICOM Print; nenhuma instalação foi afetada.** Por decisão do proprietário (29/10), nada disso
  acontece neste momento.

## 1. Escopo confirmado no código

| Ponto | Evidência | Conclusão |
|---|---|---|
| Lista de chaves públicas aceitas | `app/licensing/keys.py` (`PUBLIC_KEYS`, `KEY_SCOPES`, `RESTRICTED_KEYS`) — pacote do **DICOM Print** | Uma lista só |
| Quem usa essa lista | DICOM Print (`app/licensing/license.py`) **e** a plataforma (`vyonix/licensing/service.py:67` importa `app.licensing.keys`) | A plataforma **depende do código do DICOM Print** para saber quais chaves aceitar |
| Formato e produto do documento | `vyonix_protocol/formats.py`: `PRODUCT_ID = "VYONIX-DICOM-PRINT"` nos dois; licença v3 = campos legados (PRINT) + mapa `modules` (core, pacs, ris, report…) | **Um mesmo documento** pode licenciar o Print e os módulos da plataforma; não há separação criptográfica entre os produtos |
| Chave de emissão | `vyx-2026-01` assina licenças, autorizações, revalidações e revogações dos dois produtos | O comprometimento atinge **os dois** |
| Chave do License Server | `vyx-srv-2026-01`, escopo só `authorization` | Atinge autorizações de uso online dos dois |
| Variante de homologação | `vyonix/build_flavor.py` + `vyonix/licensing/service.py:487` | O instalador de homologação **não usa licença**: não é afetado por nenhuma alternativa |
| Plataforma em clientes | Nenhuma publicação comercial (BLK-05) | Não há licença comercial da plataforma em uso |
| DICOM Print em campo | Pré-release r5 em homologação, laboratório BKL-10; ensaios em campo não autorizados (BLK-13) | Licenças do Print existentes: laboratório/homologação (inventário a confirmar pelo proprietário) |

## 2. Alternativas (para decisão; nenhuma executada)

| # | Alternativa | O que muda | Afeta o DICOM Print? | Impactos | Reversível? |
|---|---|---|---|---|---|
| **1** | **Rotação comum** (plano original, caminhos A/B) | Nova chave `vyx-2026-02` em `app/licensing/keys.py` + restrição da antiga à lista de documentos legítimos | **Sim** — altera o código do Print (exige autorização específica e nova versão do Print) | Fecha o risco nos dois produtos de uma vez; depende do License Manager (BLK-12) ou do caminho B; reemissão de licenças | Sim até publicar (`git revert`); publicação exige aprovação |
| **2** | **Separar a plataforma** (recomendada como primeiro passo) | A plataforma passa a ter a **própria lista** (`vyonix/licensing/keys.py`), com chave nova só da plataforma (ex.: `vyx-plat-2026-01`) e `product_id` próprio (ex.: `VYONIX-PLATFORM`); a lista do Print fica como está | **Não** — nenhum arquivo do Print muda | Fecha o risco **na plataforma** (que não tem clientes: nenhuma licença comercial a preservar); o Print continua exposto até a alternativa 1 ou 3; licenças de laboratório da plataforma precisam ser reemitidas; Print e plataforma passam a ter **documentos separados** | Sim (código; não publicado) |
| **3** | **Separar e, depois, rotacionar o Print** | 2 agora; 1 restrita ao Print quando o proprietário autorizar a mudança no Print | Só na segunda etapa, com autorização | Risco do Print continua até a segunda etapa; cada produto passa a ter sua chave (um vazamento futuro não atinge o outro) | Sim |
| **4** | Aguardar | Nada | Não | Documentos forjados com `vyx-2026-01` continuam aceitos pelos dois produtos | — |

**Recomendação técnica:** alternativa **3** (separar a plataforma agora, rotacionar o Print depois com autorização).
Ela não toca o DICOM Print, não afeta instalações (a plataforma não tem licenças comerciais e a homologação não usa
licença) e reduz o alcance de qualquer vazamento futuro.

## 3. O que cada alternativa exige do proprietário

* **Gerar a chave nova** no computador do fornecedor (o par de chaves nunca passa pela área de desenvolvimento;
  só a chave pública vem para o código).
* Alternativa 2/3: aprovar a separação do licenciamento (mudança estrutural: documentos distintos por produto) e
  reemitir as licenças de laboratório da plataforma com a chave nova.
* Alternativa 1 (ou a 2ª etapa da 3): autorizar a alteração do DICOM Print, escolher o caminho A ou B para a lista
  de documentos legítimos e aprovar a publicação.
* Em todas: a destruição das cópias da área de desenvolvimento continua **adiada** e só ocorre com aprovação
  específica (irreversível).

## 4. Preparação já possível sem efeito (não feita sem autorização)

* Ferramenta `tools/apply_key_rotation.py` (pronta, com `--dry-run`) aceita `--keys-file`: pode apontar para a
  lista própria da plataforma na alternativa 2 sem tocar `app/`.
* Teste a acrescentar junto com a mudança: documento assinado pela chave antiga recusado pela plataforma; licença do
  Print inalterada (mesmos testes do Print continuam aprovados).
