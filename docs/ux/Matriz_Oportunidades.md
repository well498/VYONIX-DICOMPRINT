# Matriz de oportunidades e lacunas — VYONIX × referências brasileiras (v1, 29/10/2026)

Consolidação do Coordenador (01) a partir de: Fase A (`Fase_A_Diagnostico.md`), Fase B
(`Fase_B_Benchmarking_Brasil.md`, fontes R1–R7, PX, AS, TP, TL, MV, LA, FL), registro de aperfeiçoamento e leitura do
código. **Nada aqui é implementado automaticamente**: a seleção é por valor, segurança, necessidade real e
compatibilidade com a arquitetura; itens estruturais ou regulatórios vão para aprovação. Revisão pendente dos
Agentes 03, 04 e 05 (situação no VYONIX pode ser refinada por eles).

Situação no VYONIX: **OK** implementada e adequada · **MEL** implementada, precisa melhoria · **PAR** parcial ·
**NÃO** não implementada · **NR** não recomendada · **DEC** depende de decisão ou conformidade.
Complexidade: B baixa · M média · A alta. Prioridade: P1 essencial/usabilidade operacional · P2 · P3.

| # | Funcionalidade (referência · fonte) | Situação no VYONIX (evidência) | Problema que resolve | Benefício | Cx | Riscos / dependências | Pri | Agente | Critério de aceitação |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Faixa fixa de identificação do paciente (NIST 7804-1) | NÃO — cada tela mostra o paciente a seu modo | Paciente errado | Segurança do paciente | B | Nenhuma | P1 | UX+05 | Nome, idade/nascimento, sexo, ID e acesso visíveis e fixos em laudo, ficha e imagens; teste e2e |
| 2 | Instituição ativa sempre visível (contraponto R1) | PAR — nome da organização no topo; contas independentes já garantem isolamento | Usuário com contas em várias instituições agir na errada | Isolamento perceptível | B | Modelo de contas aprovado (não muda) | P2 | UX | Nome da instituição e unidade no cabeçalho de todas as telas |
| 3 | Worklist com prazo restante e progresso (R1, **R7**, LA1, PX6, TL1) | MEL — `report/queue.py`: prazo por prioridade (`SLA_HOURS` fixo: imediato 1 h, urgente 4 h, rotina 48 h) e marca "Atrasado"; a fila mostra só a data-limite (`reports.tsx:158`) | Atraso em urgência percebido tarde | Cumprir prazos | M | Prazo configurável por instituição/modalidade (hoje fixo no código); regra de parada (liberação) | **P1** | 05+UX | Coluna "Prazo": tempo restante em linguagem natural, faixa no prazo/atenção/atrasado com texto além da cor, contagem após vencer; ordenação padrão prioridade+prazo; teste |
| 4 | Filtros salvos, filtro "Minha fila", busca por código de barras (PX8 [C]) | NÃO — filtro padrão "Sem laudo" (UX-A-008) | Rascunhos/revisões escondidos; busca manual | Rapidez | B | Leitores de código de barras (opcional) | P1 | UX+05 | "Minha fila" padrão do médico; filtros lembrados por usuário |
| 5 | Status do laudo em selo, separado da prioridade (PX8 [C], R7) | PAR — etiquetas existem; misturadas na mesma coluna | Confundir rascunho com final | Clareza | B | Acessibilidade (texto além da cor; contraste UX-A-018) | P1 | UX | Prioridade e etapa em campos distintos; nenhum estado só por cor |
| 6 | Distribuição automática com pegar/devolver e trilha (PX2, TP3, AS2) | MEL — `report/distribution.py` (fixa/equilibrada) só no encaminhamento (A05-012); atribuição sem trava (A05-003) | Fila parada; dois médicos no mesmo exame | Equilíbrio e responsabilidade | M | Decisão do proprietário sobre "assumir laudo" (A05-003) | P1 | 05 | Distribui também sem preparo exigido; pegar/devolver auditado; outro médico não edita laudo atribuído |
| 7 | Bloqueio de laudo por habilitação (CFM 2.107 arts. 4º/6º; 2.314 art. 8) | PAR — CRM/UF e RQE cadastrados e no PDF (`report/physicians.py`); sem regra por modalidade | Ato fora de escopo | Risco ético menor | M | **DEC** — regra clínica/regulatória do proprietário | P2 | 05+04 | Configuração por instituição; bloqueio auditado |
| 8 | Ambiente único de laudo (PX4, LA1, MV3, Carestream) | PAR — "Abrir imagens" com comparação e histórico; editor sem material do técnico, sem devolver (UX-A-001), editor no topo (UX-A-006) | Troca de janela, contexto perdido | Produtividade, menos erro | A | Viewer em outra aba (OHIF); preservar decisões do Viewer | **P1** | UX+05+03 | Tela de laudo com lista, contexto do estudo (comentários, anexos, checklist), anteriores e ações; viewer ao lado |
| 9 | Protocolos de exibição editáveis por médico (PX3, OHIF/Weasis [C]) | OK — protocolos pessoal → instituição → padrão (`pacs/viewing.py`, `ViewerProtocol`) | — | — | — | Mover configuração para fora da lista operacional (UX-A Imagens) | P3 | 03 | — |
| 10 | Modelos/frases com busca e "mais usados" (AS2, PX6, Laudite) | OK — frases com categorias, busca, favoritos, variáveis; modelos pessoais e institucionais | — | — | — | Separar configuração da fila (UX-A-010) | P3 | 05 | — |
| 11 | Ditado por voz com checagem clínica (PX4, LA3) | NÃO | Digitação lenta | Velocidade | A | Motor de voz, LGPD do áudio, custo; **DEC** | P3 | 05+04 | Proposta técnica antes |
| 12 | Imagens-chave e anotações no laudo (PX8 [C]) | NÃO | Laudo sem a imagem relevante | Comunicação | M | DICOM KO/SR; Viewer | P2 | 03 | — |
| 13 | IA rotulada (aceitar/editar/rejeitar) (AS2, LA2, CFM 2.454) | NÃO | — | — | A | **DEC** — CFM 2.454/2026, ANVISA (SaMD), consentimento | P3 | 04+05 | Só após avaliação regulatória |
| 14 | Assinatura ICP-Brasil explícita com resumo pré-assinatura (R1, CFM 2.314 art. 13) | PAR — liberação por senha + imagem da assinatura; PAdES/ICP-Brasil preparado (`report/pades.py`) e bloqueado em **BLK-14** | Validade jurídica | Responsabilidade médica | A | **DEC** — BLK-14 (certificados A1/A3/nuvem, carimbo de tempo) | P1 (após BLK-14) | 05+04 | Resumo antes de assinar; laudo bloqueado depois |
| 15 | Retificação com versões e aviso ao solicitante (LA2) | PAR — versões imutáveis com hash e adendos; sem aviso ao solicitante | Correção sem rastro para quem recebeu | Rastreabilidade | M | Portal/canal do solicitante (#21) | P2 | 05 | — |
| 16 | Achado crítico com confirmação de recebimento (LA1) | OK/MEL — comunicação registrada (a quem, meio, quem, quando); escopo corrigido em `c725108` (A05-001) | — | — | B | — | P2 | 05 | Indicador de críticos pendentes na fila do médico e da coordenação |
| 17 | MFA para perfis clínicos e administrativos (R1) | MEL — MFA existe; obrigatório para administradores desligado por padrão e sem QR code (A04-009, UX-A-023); troca de senha antes do 2º fator corrigida (`c725108`) | Senha vazada | Segurança | B | **DEC** padrão (A04-009) | P1 | 04 | QR gerado localmente; política por perfil |
| 18 | Trilha de auditoria legível ao gestor (TP3, LA1) | MEL — trilha encadeada SHA-256 e tela de Auditoria com JSON cru (UX-A-014); WADO por série sem registro (A03-012) | Investigação difícil | Responsabilização | M | — | P2 | 04+UX | Detalhes em linguagem natural; filtros por paciente/estudo/usuário |
| 19 | Portal do paciente com marca, QR + senha (R1, AS2, TP1, FL1) | NÃO — requisito P2 registrado | Fila no balcão, telefone | Autonomia do paciente | A | **DEC** — BLK-06 (LGPD, CFM), menores (LGPD art. 14) | P2 | 05+04+UX | Só após aprovação dos requisitos |
| 20 | Compartilhamento com validade, revogação e lista de acessos (AS2, LGPD art. 18) | PAR — compartilhamento interno entre profissionais com prazo e revogação (`ris/prep.py`, escopo corrigido em `c725108`); nada para o paciente | Link eterno | Controle pelo titular | M | Depende de #19 | P2 | 04 | — |
| 21 | Portal/perfil do médico solicitante (PX8 [C], FL2, MV3) | NÃO — "solicitante" é texto livre (UX-A Perfis) | Solicitante sem laudo/imagens | Decisão clínica | A | **DEC** — consentimento (CFM 2.107 art. 3º), cadastro de solicitantes | P2 | 05+04+UX | — |
| 22 | Portal mobile-first; estação de laudo no desktop (TL2, AS3) | PAR — web responsiva com falhas (Agenda a 375 px, UX-A-019) | Uso no celular | Alcance | M | — | P2 | UX | Telas de recepção, solicitante e paciente utilizáveis a 375 px |
| 23 | Termo de consentimento eletrônico (CFM 2.107 art. 3º; 2.314 art. 15) | NÃO (existe só o consentimento de uso da imagem da assinatura do médico) | Transmissão sem registro | Registro | B | **DEC** — texto jurídico | P2 | 05+04 | — |
| 24 | Check-in por QR, anamnese prévia, painel de chamadas (MV4, PX2) | PAR — check-in/"Chegou" existe, com regras divergentes (UX-A-009); sem QR, anamnese ou painel | Fila e redigitação | Fluxo mais rápido | M | LGPD da anamnese | P3 | 05+UX | — |
| 25 | Agenda com sequência e lembretes (PX2, AS1) | PAR — agenda e salas; sem grade de disponibilidade, sem lembretes; pedido sem procedimento (UX-A-002) | Faltas, conflitos, pedido vazio | Ocupação | M | Canais de mensagem e opt-in | P1 (pedido com procedimento) / P3 (lembretes) | 05+UX | Formulário de pedido com procedimento, solicitante e prioridade |
| 26 | Painel do coordenador (TAT, produção, SLA, ociosidade) (AS2, PX2, MV3, R7) | PAR — Central de exames (atrasos e tempos) e Produção | Gestão às cegas | Decisão por dados | M | Dados de eventos confiáveis | P2 | 05+UX | "Visão operacional" do coordenador com exames em risco |
| 27 | Peer review e não conformidades (TP2, AS2) | PAR — revisão (segunda leitura) existe; sem não conformidades | Qualidade sem medição | Melhoria contínua | M | Sigilo entre pares | P3 | 05 | — |
| 28 | Integração por padrões (MWL, HL7/FHIR, IHE IID) (LA1, IHE) | PAR — MWL/MPPS, HL7 ORU e FHIR de saída, Q/R DICOM; ADT/ORM de entrada pendente | Redigitação | Interoperabilidade | A | Sistemas dos clientes; RNDS | P2 | 03+05 | — |
| 29 | Separação visual produção × treinamento (NIST 7804) | OK — faixa "HOMOLOGAÇÃO INTERNA" no sabor de homologação (`app.tsx:60`) | — | — | — | — | — | — | — |
| 30 | Laudo em vídeo (PX7, PX8) | NR por ora | — | — | A | Anonimização, consentimento, armazenamento | — | — | — |

## Próximos passos
1. Agentes 03/04/05 revisam a coluna "Situação" (mudanças só com evidência).
2. **Arquitetura de navegação por perfil** e **design system** usando os itens P1 desta matriz (1, 3, 4, 5, 6, 8,
   17, 25) e os problemas UX-A-001…025 — com mapas de navegação e comparação com a experiência atual.
3. **Protótipos** das telas principais (fila do médico com prazo, ambiente de laudo, painel do técnico, recepção,
   visão do coordenador) para aprovação. Nada é substituído antes.
4. Itens **DEC** são levados ao proprietário em lote, com recomendação.
