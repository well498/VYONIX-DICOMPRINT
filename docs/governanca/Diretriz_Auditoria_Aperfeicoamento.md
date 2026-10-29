# Diretriz permanente — auditoria técnica e aperfeiçoamento contínuo (29/10/2026, 18:13)

Origem: mensagem do proprietário de 29/10/2026 18:13. **O texto recebido termina em "Util" (seção 7, linha 158)**; o
restante (se houver) ainda não foi recebido e deve ser incorporado quando chegar.

## Resumo operacional
* Cada especialidade audita o que já existe (código, arquitetura, funcionalidades, integrações, interfaces, banco,
  documentação, decisões, testes) e propõe/aplica melhorias com evidência. Não concluir que algo não existe sem
  investigar o código e o histórico.
* Classificar sempre: **defeito comprovado** · **risco potencial** · **proposta experimental**.
* Pesquisa externa só para fundamentar decisões; respeitar licenças (nada de código/interfaces protegidos).
* Registro único: `docs/governanca/Registro_Aperfeicoamento.md` (consolidado pelo coordenador no backlog
  `VYONIX_NEXT_ACTION.md`). Sem relatórios duplicados.
* Implementação controlada: comportamento atual → dependências → impacto → compatibilidade → critérios de aceite →
  incremental → testes afetados → registro. Sem reescrever módulos inteiros; sem mudar o aprovado por preferência;
  mudança arquitetônica relevante vai para aprovação.
* Sem ociosidade artificial: terminado o prioritário, consultar o backlog; auditoria direcionada só com motivo; nada
  de auditorias completas repetidas.
* Continuam valendo: P0 primeiro; não modificar o DICOM Print; nada destrutivo, produção ou dados reais sem
  autorização; diretriz de continuidade (novo pedido não cancela o anterior).

## Especialidades
| Agente | Escopo da análise contínua |
|---|---|
| 01 Coordenador | Arquitetura global, integração dos módulos, dependências, planejamento, qualidade das entregas, gargalos |
| 02 Windows/DevOps | Instalador, desinstalador, serviços, recuperação, backups, PostgreSQL, atualizações, monitoramento, desempenho, pipelines (melhorias de infraestrutura depois do P0) |
| 03 PACS/Viewer | PACS, Orthanc, DICOMweb, Viewer e visualizadores, desempenho de carregamento, pesquisa, comparação, fluxos DICOM |
| 04 QA/Segurança | Cobertura de testes, isolamento institucional, autorização por estudo, autenticação, auditoria, integridade, componentes |
| 05 Telelaudos/RIS | Agendamento, cadastro, preparo, distribuição, laudo, assinatura, produção e remuneração |
