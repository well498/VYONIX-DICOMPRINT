# VYONIX Viewer — auditoria e análise de lacunas (referência: J4Care SMooTH Viewer)

* **Data:** 29/10/2026 · escopo: VYONIX Viewer (OHIF 3.13.13, MIT, compilado sem alterações com `viewer/vyonix.js`),
  DICOMweb do PACS, RIS e laudos. DICOM Print fora do escopo.
* **Fonte J4Care:** só o material público. O site descreve o SMooTH Viewer como visualizador web *zero-footprint*
  de imagens e documentos, aderente a padrões; as páginas de produto bloqueiam leitura automatizada (robots) e não
  há documentação técnica pública. **A lista de funcionalidades de referência adotada é a do pedido do proprietário
  (comparação, protocolos, linha do tempo, documentos, interface).** Nada da J4Care foi copiado (código, interface,
  identidade visual).
* **Não é validação diagnóstica.** Nenhuma aptidão diagnóstica é declarada.

## 1. Arquitetura atual (restrição de baixo risco)

* O Viewer é o OHIF oficial compilado pelo CI `viewer.yml` **sem alterações no código**; a VYONIX só configura
  (`viewer/vyonix.js`): fonte DICOMweb da mesma origem, sem tour, sem servidores externos.
* Toda imagem passa pela API do CORE (`/api/v1/pacs/dicomweb`): sessão do VYONIX, índice por organização (RLS),
  auditoria de abertura (`pacs.study.open`), CSP própria (`vyonix/api/viewer.py`).
* Evoluções que exigem **código no OHIF** (extensão/mode próprio) foram tratadas como dependência, não feitas agora.

## 2. Situação por funcionalidade

Legenda: **T** = implementado e testado (CI viewer/plataforma) · **O** = disponível no OHIF compilado, sem teste
VYONIX · **P** = parcial · **A** = ausente · **N** = implementado nesta entrega.

| Área | Funcionalidade | Situação | Evidência / observação |
|---|---|---|---|
| Básico | Lista de estudos, abrir, renderizar, navegar imagens e séries | **T** | `tests_viewer/test_viewer_e2e.py` |
| Básico | Janela/nível, zoom, girar, inverter, medir distância | **T** | idem |
| Básico | Queda do motor DICOM e recuperação; CSP sem violações; auditoria de abertura | **T** | idem; `test_viewer_serving.py` |
| Ferramentas | Ângulo, ROI, cine, lupa, sonda, navegador de tags, captura, MPR/crosshairs, linhas de referência | **O** | barra padrão do OHIF 3.13 (“Mais ferramentas”) |
| Layout | Layouts 1×1, 1×2, 2×2, 3×3 e grade configurável pelo botão Layout | **O** | `layoutSelector` do OHIF |
| Comparação | Estudos anteriores do paciente no painel de estudos; arrastar série para outro quadro | **O** | consulta QIDO por PatientID — **sem filtro por vínculo** (ver segurança) |
| Comparação | Abrir atual + anterior lado a lado (protocolo `@ohif/hpCompare`, 1×2 ou 2×2) | **N** | lançador VYONIX monta o endereço só com estudos autorizados |
| Comparação | Seleção do anterior (mesma modalidade em destaque) | **N** | lista de anteriores autorizados no lançador |
| Comparação | Navegação independente por série; sincronização de corte opcional | **O** | cada quadro é independente; “Image Slice Sync” na barra |
| Comparação | Sincronização opcional de zoom/pan e janela/nível | **A** (dependência) | o OHIF tem os grupos `zoompan`/`voi`, mas só por protocolo registrado em extensão; exige extensão VYONIX (código) |
| Comparação | Data e exame claros em cada quadro | **N** | sobreposição: data (padrão) + modalidade e descrição do exame (`vyonix.js`) |
| Comparação | Correspondência anatômica automática | **Não fazer** | sem algoritmo validado (proibido pelo pedido) |
| Protocolos | Protocolo por modalidade/procedimento da instituição | **N** | `pacs.viewer_protocols` (layout, comparar com anterior, mesma modalidade) |
| Protocolos | Preferência individual do médico, se a instituição permitir | **N** | protocolos pessoais (mesma tabela, `owner_user_id`) |
| Protocolos | Ferramentas visíveis por protocolo | **A** (dependência) | barra é personalização do OHIF por *mode*; exige extensão/mode VYONIX |
| Linha do tempo | Exame (etapas do fluxo) | **T** | `vyonix/ris/timeline.py` (`study_timeline`) |
| Linha do tempo | Anteriores do paciente com situação do laudo | **T** | `timeline.priors` |
| Linha do tempo | **Histórico do paciente** (exames, datas, modalidades, laudos, documentos, atendimentos, pedidos sem exame) | **N** | `timeline.patient_history`, sem duplicar (pedido ligado ao estudo aparece uma vez) |
| Documentos | PDF encapsulado DICOM (laudo guardado no PACS) e SR | **O** | extensões `dicom-pdf` e `cornerstone-dicom-sr` no pacote |
| Documentos | Vídeo DICOM | **O** | extensão `dicom-video` (depende do codec do navegador) |
| Documentos | Imagens/documentos não DICOM (anexos da preparação) | **P** | exibidos na preparação (cifrados, validados pelo conteúdo); **não** no Viewer — converter para DICOM exige decisão (identificação do paciente, integridade) |
| Interface | Barra, painéis recolhíveis, lista de séries, navegação de estudos | **O** | interface padrão do OHIF |
| Interface | Integração com o editor de laudos | **N** | botões “Abrir no Viewer” / “Comparar” no laudo e nas listas usam o lançador |
| Interface | Identidade visual VYONIX dentro do Viewer | **A** | logotipo/tema do OHIF por personalização — baixo valor agora |
| Segurança | Organização isolada (RLS) | **T** | testes do PACS |
| Segurança | **Imagens restritas ao vínculo do médico** (unidades) | **N (opcional)** | configuração `pacs/viewer.access = linked`: DICOMweb aplica o mesmo escopo da fila de laudos; padrão continua `organization` (comportamento homologado) |
| Segurança | Auditoria do lançamento (estudos e protocolo) | **N** | `pacs.viewer.launch` |
| Desempenho | Estudos volumosos | **A** | sem medição com estudo grande; registrar como pendência (estudo sintético grande no CI) |

## 3. Dependências e decisões

1. **Extensão VYONIX para o OHIF** (código próprio, MIT-compatível): necessária para sincronização zoom/pan/VOI,
   ferramentas por protocolo e protocolos além dos três do OHIF. Mudança estrutural moderada no pipeline do Viewer —
   propor antes de fazer.
2. **Escopo de imagens por vínculo** (`linked`): pronto como opção; ligar por padrão muda o comportamento homologado
   → decisão do proprietário.
3. **Não DICOM no Viewer:** exige definição de como identificar e assinar a integridade dos objetos convertidos.
4. **Desempenho:** gerar estudo sintético grande no CI e medir tempo de abertura.
