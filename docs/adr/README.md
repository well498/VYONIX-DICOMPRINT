# Registro de decisões de arquitetura (ADR)

Formato: contexto, decisão, consequências, alternativas e condição para rever. As decisões D1–D9 do documento de
arquitetura da plataforma correspondem às ADR-0001 a ADR-0009. Uma ADR “Proposta” só vale depois de aprovada
(Prompt Mestre §59).

| ADR | Decisão | Situação |
|---|---|---|
| [0001](ADR-0001.md) | Monorepo a partir do repositório do DICOM Print | Aceita |
| [0002](ADR-0002.md) | PostgreSQL 17 no servidor da clínica (EDGE) | Aceita |
| [0003](ADR-0003.md) | Windows primeiro no EDGE; Linux a partir da Fase 3 | Aceita |
| [0004](ADR-0004.md) | Fila de eventos no PostgreSQL (outbox) em vez de RabbitMQ/Redis | Aceita |
| [0005](ADR-0005.md) | Interface web única (React + TypeScript); Qt do Print mantido na transição | Aceita |
| [0006](ADR-0006.md) | Orthanc como motor do PACS, sem modificações | Aceita (confirmada em ADR-0012, com revisão jurídica pendente) |
| [0007](ADR-0007.md) | Nuvem multiclínica com tenant_id e FORCE ROW LEVEL SECURITY | Aceita |
| [0008](ADR-0008.md) | Empacotamento com PyInstaller (onedir) | Aceita |
| [0009](ADR-0009.md) | SQLAlchemy 2 + Alembic com um ramo de migração por módulo | Aceita |
| [0010](ADR-0010.md) | Windows 7: sem suporte na plataforma; edição legada do Print só sob demanda comprovada | Aceita |
| [0011](ADR-0011.md) | Nomes dos executáveis e instaladores | Aceita |
| [0012](ADR-0012.md) | PACS e Viewer da Entrega 3: Orthanc 1.13 + OHIF 3.13 (Cornerstone3D 5) | Proposta — exige aprovação (revisão jurídica da AGPL) |
| [0013](ADR-0013.md) | Temas da interface com tokens e contraste WCAG 2.2 AA verificado | Aceita |
