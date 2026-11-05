# Estudo J4Care (coordenador, 05/11/2026) — só conteúdo público; j4care.com raiz não acessível pelo allowlist (páginas internas sim)
Fontes abertas: https://www.j4care.com/copy-of-smooth-vna (VNEdge), https://www.j4care.com/news, https://web.dcm4che.org/solutions, https://www.advantageaustria.org/ae/company/en/j4care-gmbh
- J4Care (Mödling, Áustria): principal contribuidora do dcm4che; vende SMooTH Suite = "versão Enterprise profissional do dcm4che" + visualizador; produto médico certificado; de servidor único a multi-site ativo/ativo e arquivos nacionais (Estônia, Finlândia, CUF Portugal, Pisa). Suporte a quem usa dcm4chee.
- SMooTH VNA: VNA vendor-neutral, XDS, FHIR, patologia; Connectathon patologia 2024 sem falhas (SMooTH Archive).
- SMooTH Viewer: web zero-footprint, clínicos e pacientes, certificado para diagnóstico, relatórios, reconhecimento de voz.
- SMooTH VNEdge: edge para centros remotos; "cluster compacto de 3 NUC"; "Always-On Availability – Stay operational, even during network outages"; comunicação cifrada; processamento local completo; sincroniza com VNA central (datacenter ou nuvem). Sem detalhes de mecanismo/cache/prefetch.
- SMooTH VNIN: só citado (Arab Health 2025); nenhuma descrição técnica pública encontrada.
- Projeto Dorset (2023): arquitetura baseada em mensagens em vez de "image pooling".
Conceitos incorporáveis (proposta VYONIX, sem código proprietário): edge que opera durante queda de rede; sincronização segura com VNA central; arquitetura por mensagens (eventos) em vez de consulta em massa; arquivo central multi-site com isolamento; viewer zero-footprint também para paciente; conformidade IHE comprovada em Connectathon.
Separação: aberto = dcm4che/dcm4chee-arc-light (verificar licença no repo); proprietário/comercial = SMooTH (edge cluster, viewer, certificação, suporte); proposta = o que o VYONIX implementaria por conta própria.
