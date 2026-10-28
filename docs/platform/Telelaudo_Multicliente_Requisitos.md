# VYONIX TELELAUDO multicliente — requisitos, arquitetura e plano incremental

Situação: **requisitos registrados em 28/10/2026 (pedido do proprietário). Não iniciado.** Entra depois das
prioridades em andamento (PACS, Viewer, RIS, DEPLOY), respeitando os bloqueios BLK-06, BLK-13 e BLK-14. Constrói sobre
o VYONIX REPORT (primeira entrega já feita), sem uma versão separada do sistema por cliente.

## 1. Objetivo

Um mesmo sistema atende várias clínicas e hospitais. Cada cliente tem:

- modelos de laudo próprios;
- identidade visual: logomarca, papel timbrado, cabeçalho, rodapé, margens, fontes, cores e paginação;
- unidades com identidade própria;
- médicos vinculados.

O laudo final é gerado com a identidade, o modelo e o médico corretos, com rastreabilidade do exame ao documento.

## 2. Requisitos

| ID | Requisito | Detalhes e critérios de aceitação |
|---|---|---|
| TEL-01 | Identidade visual da organização | Upload de logomarca, papel timbrado (PDF/imagem de fundo), cabeçalho e rodapé. Margens, fontes (lista fechada, embutidas no PDF), cores e paginação. Pré-visualização A4. Versão a cada alteração. |
| TEL-02 | Identidade por unidade | Herda da organização e sobrescreve campo a campo. A pré-visualização mostra a origem de cada elemento. |
| TEL-03 | Biblioteca de modelos | Modelos padrão do sistema (somente leitura) e modelos do cliente. Associação por modalidade e procedimento (e unidade, opcional). Ativo/inativo. |
| TEL-04 | Versões de modelos | Rascunho → em conferência → publicado → arquivado. Laudo liberado guarda a versão exata do modelo e da identidade usadas. Versão publicada é imutável. |
| TEL-05 | Editor visual | Seções estruturadas (técnica, achados, conclusão) e campos dinâmicos validados (paciente, exame, data, instituição, unidade, médico, CRM/UF, RQE). Cabeçalho e rodapé. Quebras de página automáticas. Pré-visualização A4 e exportação PDF. Sem HTML livre: o conteúdo é saneado. |
| TEL-06 | Importação DOCX assistida | Converte estilos, tabelas, imagens, cabeçalho e rodapé suportados. Lista as incompatibilidades (campos de formulário, macros, fontes ausentes, objetos incorporados). O modelo importado só é publicado depois da **conferência visual confirmada** por um usuário autorizado. Macros e conteúdo ativo nunca são executados. |
| TEL-07 | Cadastro de médicos | Nome completo, CRM e UF (validação de formato), RQE e especialidades. Clínicas e unidades autorizadas (vínculo com início e fim). Identificação profissional no rodapé. Usuário do VYONIX vinculado. |
| TEL-08 | Imagem da assinatura manuscrita | Elemento **somente visual**. Enviada pelo próprio médico, guardada cifrada, com acesso só durante a geração do PDF de um laudo que ele liberou. Aplicada apenas se o médico autorizar (opção dele, revogável). **Nunca substitui a assinatura eletrônica.** Administradores não podem enviar, trocar, baixar nem aplicar a imagem de outro médico. |
| TEL-09 | Assinatura do laudo | Ato do próprio médico, com data e hora, identidade do signatário, versões e SHA-256 na auditoria. Hoje: confirmação de senha (feito no REPORT). Assinatura digital ICP-Brasil (PAdES, carimbo de tempo, certificado A1/A3 ou em nuvem) depende de BLK-14. |
| TEL-10 | Seleção automática (seção 3) | Organização, unidade, modalidade e procedimento → modelo e identidade; médico autorizado; campos administrativos do RIS/PACS; conteúdo clínico editável; pré-visualização; revisão e assinatura; documento final auditado. |
| TEL-11 | Isolamento multicliente | RLS por organização em todas as tabelas e arquivos. Permissões por organização e unidade. Teste automatizado: nenhum modelo, identidade, assinatura ou médico de outro cliente é selecionável nem acessível. |
| TEL-12 | Arquivos sensíveis | Logos e timbrados por organização. Imagens de assinatura cifradas em repouso, fora da pasta pública, sem URL direta, com acesso auditado. Limites de tipo e tamanho; varredura de conteúdo ativo (SVG com script, PDF com JavaScript). |
| TEL-13 | Integração RIS/PACS/Viewer | Laudo ligado a pedido, accession, Study Instance UID e agendamento. Link para o Viewer. Situação do laudo no RIS. |
| TEL-14 | Padrões | DICOM: laudo como Encapsulated PDF (1.2.840.10008.5.1.4.1.1.104.1) ou SR básico, enviado ao PACS do cliente **quando o equipamento suportar**. HL7 v2 ORU^R01 e FHIR R4 DiagnosticReport no CONNECT. Sempre opcionais, sem pressupor suporte. |
| TEL-15 | LGPD e documento médico eletrônico | Base legal e finalidade. Minimização no PDF. Retenção e descarte por política do cliente. Registro de acesso. Revisão das normas do CFM e da legislação de documentos e assinaturas eletrônicas por especialista (BLK-06 e BLK-14) antes da comercialização. |
| TEL-16 | Telelaudo (distribuição) | Fila de laudos por médico e cliente, atribuição, prazos (SLA) e prioridade. Médico remoto acessa só os exames das unidades autorizadas. Comunicação de achado crítico ao cliente de origem. |

## 3. Seleção automática: prioridade e fallback

A busca nunca sai da organização do exame. O RLS garante isso no banco, e o serviço também confere.

**Modelo:**
1. Combinação mais específica primeiro, entre os modelos publicados e ativos da organização do exame:
   - unidade + procedimento;
   - unidade + modalidade;
   - organização + procedimento;
   - organização + modalidade;
   - modelo genérico da organização.
2. Modelo padrão do sistema para a modalidade. É somente leitura; o cliente pode adotá-lo explicitamente.
3. Sem modelo: rascunho em branco com as seções técnica, achados e conclusão, com aviso. **Nunca** o modelo de
   outra organização.
4. Empate no mesmo nível: modelo marcado como preferencial. Se não houver preferencial, a escolha é recusada com
   pedido de decisão ao administrador do cliente. A escolha não é arbitrária.

**Identidade visual:**
1. Identidade da unidade (campo a campo);
2. identidade da organização;
3. identidade neutra do sistema, sem logomarca.

**Médico:**
- Só médicos com vínculo vigente com a organização e a unidade do exame, e com a permissão de laudar.
- O médico que libera é o usuário autenticado no ato. Não existe "liberar em nome de".

**Versões:** o laudo grava o identificador e a versão do modelo e da identidade usados. Reemitir um PDF antigo usa
as mesmas versões.

## 4. Arquitetura proposta

| Parte | Detalhe |
|---|---|
| Módulo | `report` atual ampliado. O nome comercial **VYONIX TELELAUDO** é uma oferta da licença sobre o módulo `report`; a decisão comercial é do proprietário. |
| Esquema `report` | Novas tabelas: `branding`, `branding_versions`, `templates`, `template_versions` (com o estado de conferência), `template_bindings` (modalidade/procedimento/unidade), `physicians`, `physician_links`, `signature_images` (referência ao arquivo cifrado), `assignments` (fila). Todas com RLS. |
| Arquivos | Armazenamento por organização no diretório de dados. Imagens de assinatura cifradas com chave do cofre local, nunca no banco em claro. |
| Renderização | Mesmo motor para pré-visualização e documento final, para que o PDF corresponda à pré-visualização: ReportLab, ou HTML → PDF com mecanismo sem rede. Fontes embutidas e quebra de página automática. |
| Importação DOCX | `python-docx` (leitura, sem macros) com relatório de incompatibilidades. Conversão para o formato interno estruturado. Conferência visual obrigatória antes de publicar. |
| Permissões | `report.branding.manage`, `report.templates.manage`, `report.templates.publish`, `report.physicians.manage` (cadastro, sem acesso à imagem de assinatura), `report.write`, `report.sign`, `report.assign`. |
| Auditoria | Toda alteração de identidade, modelo, vínculo, imagem de assinatura (envio, revogação, uso) e assinatura de laudo. |

## 5. Plano incremental (quando chegar a etapa)

| Etapa | Entrega | Testes principais |
|---|---|---|
| T1 | Cadastro de médicos e vínculos; permissão de laudar por organização e unidade | Isolamento; médico sem vínculo não lauda |
| T2 | Identidade visual (organização e unidade) com versões e pré-visualização A4 | Herança; arquivos maliciosos recusados |
| T3 | Modelos estruturados com campos dinâmicos, versões e publicação | Campos validados; versão publicada imutável |
| T4 | Seleção automática com prioridade e fallback | Matriz de casos; nunca seleciona de outro cliente |
| T5 | PDF final com identidade e modelo versionados; imagem de assinatura opcional autorizada pelo médico | Administrador não usa a assinatura; reemissão idêntica |
| T6 | Importação DOCX assistida com relatório e conferência | Documentos sintéticos com incompatibilidades conhecidas |
| T7 | Fila de telelaudo (atribuição, prazos) | Médico remoto só vê as unidades autorizadas |
| T8 | DICOM Encapsulated PDF / HL7 / FHIR opcionais | Simuladores; equipamento sem suporte não quebra o fluxo |
| T9 | Assinatura digital ICP-Brasil | Depende de BLK-14 |

## 6. Restrições

- Não altera a instalação do DICOM Print.
- Sem publicação, ensaios em campo ou uso clínico sem autorização.
- Dados de teste sempre sintéticos.
