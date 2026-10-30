# UX — Fase B: benchmarking de plataformas brasileiras, com estudo especial da RadCloud (29/10/2026)

Pesquisa só em fontes públicas; nenhuma plataforma foi testada; nenhuma área restrita acessada. Classes:
**[C]** CONFIRMADO (documentado em detalhe) · **[D]** DECLARADO PELO FORNECEDOR · **[NV]** NÃO VERIFICADO ·
**[P]** PROPOSTA VYONIX. Conformidade declarada por concorrente não prova conformidade do VYONIX. Códigos de fonte
na seção 5. Material de fornecedor é marketing: só há detalhe verificável em notas de versão públicas da Pixeon
(PX8), na documentação de OHIF/Weasis e nos textos das normas.

## 1. Comparativo (tema × plataforma) — "—" = nada público [NV]
| Tema | RadCloud | Audo | Telepacs | ASL | Pixeon | Telelaudo | MV |
|---|---|---|---|---|---|---|---|
| Arquitetura | PACS/RIS + telerradiologia num sistema [D] R1–R3 | só metadados [NV] | Agile Viewer, PACS, Cloud, Report [D] | CIS + RIS + PACS + Portal + Insights [D] | Aurora, Arya/XViewer, Korus, Smart [D] | serviço; portais Cliente/Radiologista [D] | Soul MV, VIVACE, Global Health [D] |
| Menus/navegação | [NV] (imagem pública: Dashboard · Worklist · Relatórios, ver `Referencia_RadCloud_Worklist.md`) | — | áreas restritas Laudo/Resultados [D] | módulos por produto [D] | busca com código de barras; lista colorida por status [C] PX8 | dois portais [D] | por segmento [D] |
| Perfis | médicos/equipes, gestores, pacientes [D] | — | cliente, paciente, radiologista [D] | médico, solicitante, paciente [D] | radiologista, solicitante, paciente [D] | cliente × radiologista [D] | médicos, pacientes, instituições [D] |
| Permissões | MFA [D]; papéis [NV] | — | gestão de acessos [D] | controle de acesso [D] | permissão própria p/ excluir imagem [C] | — | — |
| Agenda/atendimento | [NV] | — | — | agenda online 24 h [D] | sequência automática, WhatsApp/site/app, lembretes, anamnese, token de convênio [D] | n/a | totem QR, painel de chamadas [D] |
| Gestão de exames | "da recepção à entrega" [D] | — | ciclo de vida do laudo [D] | pedidos, não conformidades [D] | cartões com atrasos/urgências [D] | — | worklist por setor [D] |
| Recepção DICOM | equipamento → nuvem [D] | — | modalidade ou PACS do cliente [D] | multimodalidade [D] | DICOM [D] | — | — |
| PACS/Viewer | [NV] | — | "certificação ANVISA" [D] | web + workstation, MPR, 3D [D] | protocolos automáticos [D]; imagens-chave para o laudo; laudo abre sem imagens [C] | — | VIDA, linha do tempo [D] |
| Distribuição | [NV] | — | roteamento p/ especialista [D] | entre médicos [D] | automática, filas configuráveis [D] | — | — |
| Telelaudo | 24/7; urgência "em minutos" [D] | [NV] | 24/7, subespecialidade, peer review [D] | [D] | central em nuvem [D] | urgência < 1 h (contrato 2 h); rotina ≤ 16 h (24 h) [D] | central remota [D] |
| Modelos/edição | — | — | modelos, voz [D] | máscaras, voz, laudo ilustrado, assistente TAI [D] | máscaras, voz sem troca de janela [D]; laudo em vídeo [C] | — | — |
| Assinatura ICP-Brasil | ICP-Brasil [D] | — | "com certificado" [D] | [NV] | [NV] | segue CFM 2.107 [D] | biométrica à parte [D] |
| Portal do paciente | com a marca da clínica, login/senha no exame [D] | por instituição [NV] | ID do exame + código [D] | QR code, e-mail/WhatsApp [D] | portal/WhatsApp; vídeo [D] | — | Portal de Exames [D] |
| Portal do solicitante | "acesso online" [D] | — | login [D] | com controle de acesso [D] | link web para a imagem [C]; tablet/celular [D] | Portal do Cliente [D] | [D] |
| Prioridade/SLA | SLA por urgência [D]; imagem pública com prazo + barra de % consumido | — | [D] | controle de prazos [D] | SLA em BI [D] | SLA numérico publicado [D] | — |
| Indicadores | [NV] | — | relatórios [D] | produtividade, volume, custo, ociosidade [D] | KPIs/BI [D] | — | tempo real [D] |
| Interoperabilidade | [NV] | — | DICOM, prontuário [D] | [NV] | prontuário [D] | HL7 [D] | [NV] |
| Segurança/auditoria | AWS, "criptografia avançada" [D]; auditoria [NV]; política LGPD sem encarregado identificado [D] | — | anonimização, auditoria de logs [D] | [NV] | bloqueio de edição remota [C] | — | LGPD [D] |
| IA | [NV] | — | [NV] | assistente TAI [D] | HarpiAI [D] | — | tórax [D] |
| Nuvem/local | nuvem AWS, sem infraestrutura local [D] | — | nuvem + PACS [D] | web + desktop [D] | nuvem para laudo [D] | — | PACS em nuvem [D] |
| Dispositivos | [NV] | [NV] | — | qualquer navegador [D] | Arya Win11/macOS [C] | não lauda no celular [D] | acesso remoto [D] |
| Suporte | 24/7, AnyDesk, treinamento [D] | — | 24/7 WhatsApp [D] | service desk [D] | portal, LMS [D] | TeamViewer [D] | 0800 [D] |

Outras com justificativa técnica: **Laudos.AI** (fila com criticidade e SLA perto de estourar; achado crítico com
confirmação de recebimento; HL7v2, FHIR R4, DICOM-SR, MWL [D]); **Fleury** (portal com dois públicos, laudo
evolutivo [D]). Da 1ª rodada: Dedalus RISonWEB, Fujifilm Synapse RIS, Carestream Vue, Animati, Laudite, Morsch.

## 2. Estudo especial da RadCloud (R1–R6; áreas de login não acessadas)
| Item | Divulgado | Exigiria demonstração autorizada |
|---|---|---|
| PACS/RIS integrado | "tudo em um só sistema" [D] | módulos, telas, papéis |
| Central de exames | acompanhamento da recepção à entrega [D] | colunas, filtros, lote |
| Filas | [NV] (imagem pública mostra worklist com unidade, prioridade, status e SLA) | regras de fila |
| Prioridade e SLA | por urgência [D] | níveis, alertas, escalonamento, relatório |
| Distribuição | [NV] | automática/manual, balanceamento |
| Produtividade | [NV] | painéis, exportação |
| MFA | para médicos e equipes [D] | métodos, obrigatoriedade, recuperação |
| Assinatura ICP-Brasil | [D] | A1/A3/nuvem, lote, carimbo de tempo, validação |
| Multi-institucional | várias unidades numa plataforma; **login único para vários hospitais** [D] | isolamento. **Registrado, não recomendado: o VYONIX mantém contas independentes por instituição (decisão aprovada)** |
| Portal do paciente | marca da clínica; login/senha no exame [D] | compartilhamento, validade, acessibilidade |
| Entrega | portal para médicos e pacientes [D] | notificações, link do solicitante |
| Segurança | AWS, criptografia, LGPD/CFM/ANVISA, registro MS citado [D]; registro não confirmado na consulta [NV] | auditoria, retenção, controlador/operador |
| Escala | > 500 mil exames/mês, 3 mil usuários, 250 unidades [D] | desempenho real |
| Guarda | 20 anos [D] | arquivo frio, recuperação |
| Suporte | 24/7, AnyDesk [D] | níveis de atendimento |

Lições [P]: SLA visível por urgência; portal com a marca da instituição; MFA para equipes clínicas; guarda longa
explícita; **contraponto:** mostrar sempre em qual instituição o usuário está (contas independentes).

## 3. Padrões de mercado
Entradas por perfil · fila com urgência/prazo e distribuição automática · laudo sem troca de janela (voz, imagens-
chave) · protocolos de exibição e comparação automáticos · assinatura "ICP-Brasil" anunciada sem detalhe · entrega
digital (portal com marca/QR/protocolo, link para o solicitante, WhatsApp, vídeo) · recepção digital · painéis de
produção/SLA/ociosidade · nuvem como padrão, suporte remoto · celular para paciente/solicitante, laudo em estação ·
IA anunciada como apoio.

## 4. Candidatas para o VYONIX [P] (situação no VYONIX: preenchida na matriz de oportunidades)
1 Faixa fixa de identificação do paciente (NIST 7804-1) · 2 Banner da instituição ativa · 3 Worklist com prazo
restante e alerta (R1, LA1, PX6, TL1) · 4 Filtros salvos, filtro mínimo, código de barras (PX8) · 5 Status do laudo
por selo, não só cor · 6 Distribuição automática com pegar/devolver e trilha · 7 Bloqueio por habilitação
(CFM 2.107 arts. 4º/6º; 2.314 art. 8) · 8 Ambiente único de laudo · 9 Protocolos de exibição editáveis ·
10 Modelos/frases com busca e "mais usados" · 11 Voz com checagem de lateralidade/negação/medidas (LGPD do áudio) ·
12 Imagens-chave/anotações no laudo (DICOM KO/SR) · 13 IA rotulada aceitar/editar/rejeitar (CFM 2.454) ·
14 Assinatura ICP-Brasil explícita com resumo pré-assinatura (CFM 2.314 art. 13; 2.107 art. 10) · 15 Retificação
com versões e aviso ao solicitante · 16 Achado crítico com confirmação de recebimento · 17 MFA clínicos e
administrativos · 18 Trilha de auditoria visível ao gestor · 19 Portal do paciente com marca, QR + senha (LGPD,
menores art. 14) · 20 Compartilhamento com validade, revogação e lista de acessos (LGPD art. 18) · 21 Portal do
solicitante (histórico, laudo evolutivo, link de imagens; consentimento CFM 2.107 art. 3º) · 22 Portal mobile-first e
acessível; laudo em estação (mamografia: monitor específico) · 23 Termo de consentimento eletrônico (CFM 2.314
art. 15) · 24 Check-in por QR, anamnese prévia, painel de chamadas · 25 Agenda com sequência e lembretes ·
26 Painel do coordenador (TAT, produção, SLA, não conformidades, ociosidade) · 27 Peer review e não conformidades ·
28 Integração por padrões (MWL, HL7v2/FHIR, IHE IID, distribuição de resultados; RNDS) · 29 Separação visual
produção × treinamento (NIST 7804) · 30 Laudo em vídeo opcional (anonimização, consentimento).

## 5. Fontes
RadCloud: R1 radcloud.com.br · R2 /pacs-ris · R3 /telerradiologia · R4 /central-de-ajuda · R5 /politica-lgpd ·
R6 /politica-de-privacidade. Audo: audo.com.br, portal.audo.com.br (sem conteúdo). Telepacs: telepacs.com.br e 3
páginas. ASL: asl.com.br, /asl-ris, /asl-pacs, post de interoperabilidade. Pixeon: pixeon.com, /sistema/radiologia,
blogs (hanging protocols, central de laudos, entrega, assinatura, cloud, worklist), Laudite, laudo multimídia,
**PX8 notas de versão públicas do Arya (portalcliente.pixeon.com/doc)**. Telelaudo: home e blog mobile. MV:
mv.com.br, /produto/pacs, VIVACE, One Touch, blog. Laudos.AI, Fleury. OHIF, Weasis, IHE RAD, NIST IR 7804/7804-1,
eMAG. Normas: CFM 2.107/2014, 2.314/2022, 2.454/2026 (via resumo Demarest), parecer CBR 2026, Lei 14.063/2020,
LGPD (cópia SES-DF). URLs completas no resultado da pesquisa (sessão de 29/10).
Não acessadas de propósito: logins da RadCloud, áreas de cliente da MV/ASL, área do médico do Fleury. Sem conteúdo
ou com erro: Audo; ajuda da RadCloud (só perguntas); registro ANVISA citado não confirmado; páginas do Planalto
(LGPD acessada por cópia; Lei 13.787 não lida); CFM 2.299/2021 não verificada. Não analisadas: Tasy, Soul MV em
detalhe, Medicware, Agfa, Philips (sem material público de interface).
