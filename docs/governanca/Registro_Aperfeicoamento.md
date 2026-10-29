# Registro de aperfeiçoamento técnico (fonte única)

Classe: **D** defeito comprovado · **R** risco potencial · **P** proposta experimental.
Estado: Proposto · Aprovação necessária · Em andamento · Implementado (commit) · Validado (CI/proprietário) · Descartado.

| ID | Agente | Módulo / componente | Classe | Situação atual / problema | Evidência | Melhoria | Benefício | Risco da alteração | Dependências | Pri | Testes | Estado |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A02-001 | 02 | Desinstalador (Inno) | D | Fechamento de processos da pasta encerrava o próprio `unins000.exe` (código −1; desinstalação seguia em segundo plano) | CI `40944999029` 2.12; homologação `40945047712` passo 15 | Excluir `unins*` | Desinstalação confiável e verificável | Baixo | — | P0 | `test_uninstaller_itself_is_never_killed`; CI 2.12 | Implementado (`4bb8b0f`), CI pendente |
| A02-002 | 02 | DEPLOY — reversão do banco | D | Reversão de atualização com falha podia apagar banco existente se o banco estivesse inacessível na captura (estado desconhecido tratado como "criado agora") | `vyonix_deploy/steps/core.py` (`capture`/`rollback` antes de `f9c04e3`) | Só remover banco/cluster comprovadamente criado na execução | Integridade de dados | Baixo | — | P0 | `test_faults.py` | Implementado (`f9c04e3`, `457a6eb`), CI pendente |
| A02-003 | 02 | Desinstalador / DEPLOY — posse dos serviços | R | Serviços removidos só pelo nome; outro produto com o mesmo nome seria afetado | `installer/VyonixPlatform.iss`, `steps/update.py` | Tocar só serviço cujo programa está na pasta do Platform | Segurança operacional | Baixo | — | P0 | `Ownership`; CI 2.13 | Implementado (`457a6eb`), CI pendente |
| A02-004 | 02 | Desinstalador — resultado | R | Sem verificação final: incompleta parecia concluída | Sintoma relatado pelo proprietário (28–29/10) | Status real em `Logs\desinstalacao.json` + erro visível | Diagnóstico e confiança | Baixo | — | P0 | CI 2.12 / homologação 15 | Implementado (`457a6eb`), CI pendente |
| A02-005 | 02 | CI — resultados | D | GitHub mostra só 10 avisos por etapa: passos 10–14 da homologação ficaram invisíveis | Run `40945047712` | Resumo único em blocos | Rastreabilidade | Nenhum | — | P0 | — | Implementado (`4bb8b0f`) |
| A02-006 | 02 | PostgreSQL — queda no CI | R | Banco não voltou após queda forçada em uma execução (intermitente); causa raiz não confirmada | CI `5a51301` 2.10 | Espera maior (`-t 300`) + diagnóstico anexado (`pg_diag`) | Disponibilidade | Baixo | — | P0 | CI 2.10 | Mitigado (`8f15f75`); aprovado nas execuções seguintes; observar |
