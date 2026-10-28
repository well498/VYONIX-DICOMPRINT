# Central de Exames, Painel do Técnico e integração com Telelaudos — auditoria e matriz

Pedido do proprietário de 28/10/2026, 18h12 ("Evolução da Central de Exames, Painel do Técnico e Integração com
Telelaudos"). Auditoria sobre a `develop` em `c9eb30e`. A "imagem de referência do sistema Tele Radiologia"
citada no pedido **não veio anexada** (só os dois textos); a implementação segue o fluxo descrito, sem copiar
interface de terceiros.

## 1. O que existe e é aproveitado

| Recurso existente | Onde | Testes aprovados |
|---|---|---|
| Recepção DICOM (STOW/C-STORE) com validação, SHA-256, organização pela rota do AE (nuvem) ou pela instalação (local), recusas auditadas | `vyonix/pacs/service.py`, `dimse_qr.py` | `test_pacs*.py`, `test_pacs_cloud_isolation.py` |
| Qualidade do estudo: lacuna/repetição na numeração, recepção em andamento, sem pedido, sem accession (indício, nunca afirmação de completude) | `pacs.quality` | `test_pacs.py` |
| Imagens previstas pelo MPPS × recebidas | `ris.completeness` | `test_mpps_performed_images_vs_pacs` |
| Central de exames por pedido (etapas, atrasos, tempos) | `vyonix/ris/tracking.py` | `test_ris_exam_center.py` |
| Painel do técnico (exames do dia, recebidos, recusas, pendências; chegada/início/conclusão) | `vyonix/ris/technician.py`, `pages/technician.tsx` | `test_ris_technician.py`, e2e |
| Viewer OHIF na mesma origem, abertura auditada | `vyonix/api/viewer.py` | CI viewer |
| Fila de laudos: escopo por unidade, atribuição manual com prioridade/prazo, **uma atribuição aberta por exame** (índice único), reatribuição, liberação conclui | `vyonix/report/queue.py` | `test_report_queue.py` |
| Permissões efetivas, papéis opcionais, delegação limitada, login único | `vyonix/auth` | `test_access_multiinst.py` |
| Cancelamento de agendamento com motivo (recepção) | `ris.set_status` | `test_ris.py` |

## 2. Matriz

| Funcionalidade | Estado atual | Alteração necessária | Componentes | Risco | Testes |
|---|---|---|---|---|---|
| Fila de preparação por estudo recebido | Falta (só lista de recebidos) | Estado de preparação por estudo (recebido → em preparação → com pendência → pronto/encaminhado → devolvido → cancelado), criado sob demanda | `ris` (nova tabela), API, Painel | Médio | estados, isolamento |
| Recepção incompleta | Parcial (indícios de qualidade, MPPS) | Exibir na fila; bloquear encaminhamento enquanto "recepção em andamento" | prep + `pacs.quality` | Baixo | encaminhamento recusado |
| Equipamento de origem | Falta (só na auditoria) | Guardar o AE de origem do estudo na recepção DIMSE | `pacs_0005`, ingest | Baixo (aditivo) | recepção |
| Filtros (modalidade, data, equipamento, unidade, status, prioridade, paciente, accession) | Parcial | Filtros na fila de preparação | API + página | Baixo | filtros |
| Tela de preparação (cabeçalho, Viewer) | Falta | Detalhe do estudo com paciente, atendimento, unidade, médico, prioridade, prazo, estado | API + página | Baixo | detalhe |
| Anexos, foto de documento, áudio | Falta | Arquivos privados validados por conteúdo (PDF, JPEG, PNG, WEBP; áudio WebM/Ogg/MP4/MP3), limite de tamanho, cifrados no banco, download só autenticado; câmera e gravação pelo navegador; áudio é só registro (sem transcrição) | `ris` + chave do cofre | Médio | tipos, tamanho, acesso |
| Comentários com não lidos | Falta | Comentários por estudo com autor, data, instituição; marca de leitura por usuário | `ris` | Baixo | não lidos |
| Prioridade | Parcial (no pedido e na atribuição) | Alterar com permissão (auditado); técnico solicita | prep + pedido | Baixo | permissão |
| Checklist configurável | Falta | Itens por instituição/modalidade (obrigatório/opcional) + verificações de segurança fixas no servidor | configuração `ris.checklist` | Médio | obrigatórios, fixos |
| Duplicidade | Falta | Indício: mesmo paciente + modalidade + data em outro estudo, ou mesmo accession; tratamento registrado sem apagar | prep | Baixo | indício, decisão |
| Trocar médico | Parcial (reatribuição pela coordenação) | Técnico solicita (registro); reatribuição só com `report.assign` | prep + fila | Baixo | permissão |
| Compartilhar | Falta | Acesso temporário a um usuário da instituição (visualizar/laudar), com prazo, auditado; entre instituições depende da rede VYONIX (fase própria) | `ris` + escopo da fila | Médio | prazo, escopo |
| Suspeita técnica | Falta | Sinalizações tipificadas, abertas/resolvidas, sem conclusão automática | prep | Baixo | registro |
| Cancelamento | Parcial (agendamento) | Cancelar a preparação com justificativa e permissão; nada apagado | prep | Baixo | permissão |
| Encaminhar à fila de laudos | Falta | Transição validada no servidor; opção da instituição de a fila de laudos mostrar só estudos encaminhados | prep + `report.worklist` (opcional, padrão desligado) | Médio | encaminhamento |
| Devolver para correção | Falta | Médico/coordenação devolve com motivo; técnico vê "devolvidos" | prep | Baixo | devolução |
| Distribuição médica | Parcial (manual) | Regra da instituição: manual, médico fixo ou equilibrada entre médicos com vínculo; reserva pelo médico com expiração | `report.queue` | Médio | concorrência |
| Médicos da rede VYONIX | Falta | Exige acesso entre organizações por contrato — fase própria | — | Alto | — |
| Menu expandido/recolhido/oculto e menu temporário no celular | Parcial (menu vira faixa no celular) | Estados da barra lateral e gaveta no celular | `app.tsx`, CSS | Baixo | e2e celular |

## 3. Ordem

Fase 2–4 (fila, ferramentas, encaminhamento) → Fase 5 (distribuição e reserva) → Fase 6 (menus e celular) →
Fase 7 (regressão por impacto). Andamento registrado na seção 4.

## 4. Andamento

| Data | Entrega | Testes |
|---|---|---|
| 28/10 | Backend da preparação (`ris_0007`, `vyonix/ris/prep.py`, rotas `/ris/prep*`): etapas, fila com filtros e totais, checklist da instituição + verificações fixas no servidor, anexos cifrados (documento, foto, áudio) com validação por conteúdo, comentários com não lidos, suspeitas técnicas e pedidos (troca de médico/prioridade), prioridade com permissão, duplicidade com decisão registrada, cancelamento com justificativa, encaminhamento, devolução para correção, compartilhamento com prazo; equipamento de origem (`pacs_0005`, StationName ou AE); distribuição fixa/equilibrada e reserva do médico com conflito e expiração (`report_0010`, `vyonix/report/distribution.py`); opção da fila de laudos exigir preparação | `test_ris_prep.py` 4/4; platform 198 local (2 sem Orthanc local) |
