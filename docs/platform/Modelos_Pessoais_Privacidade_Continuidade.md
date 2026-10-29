# Modelos pessoais e frases pessoais — privacidade, exportação, recuperação e continuidade

* **Data:** 29/10/2026 · implementado em `vyonix/report/templates.py`, `vyonix/report/phrases.py`
* **Princípio:** o conteúdo pessoal do médico é dele. A instituição garante a continuidade do serviço, mas **nenhum
  perfil administrativo lê, altera ou exporta** modelos e frases pessoais de outro usuário pela aplicação.

## Mecanismos avaliados

| Mecanismo | Decisão | Motivo |
|---|---|---|
| Administrador vê/edita modelos pessoais | **Não** | Acesso irrestrito ao conteúdo pessoal (vedado pelo proprietário) |
| **Exportação pelo próprio médico** (arquivo JSON com SHA-256) | **Implementado** | Cópia de segurança sob controle do médico; a integridade é conferida na recuperação |
| **Recuperação** a partir da exportação | **Implementado** | Volta como **rascunhos pessoais** do usuário que importa (publicar exige conferência); arquivo alterado é recusado |
| **Oferecer cópia à instituição** (iniciativa do médico) | **Implementado** | Continuidade quando o médico quer: cria modelo da instituição **inativo e em rascunho**; quem gerencia confere, ativa e publica; o original segue privado |
| **Resumo para gestores** | **Implementado** | Só quantidade de modelos pessoais por usuário e data da última mudança — sem nomes nem texto — para planejar continuidade (ex.: pedir ao médico que exporte antes de sair) |
| Transferência automática ao desativar o usuário | **Não** | Seria acesso sem consentimento; os modelos ficam guardados e inacessíveis |
| Cópia pelo banco de dados | Fora da aplicação | O backup do servidor contém os dados (como todo o banco); restauração é procedimento técnico auditado, não acesso de rotina |

## Garantias testadas (`tests_platform/test_report_editor.py`)

* Modelo pessoal invisível e inutilizável por outro médico e pelo administrador (404); fora da seleção automática.
* Exportação só dos próprios modelos; arquivo adulterado recusado (SHA-256); recuperação preserva a formatação.
* Proposta à instituição: inativa, em rascunho, não pessoal; o original continua pessoal.
* Resumo do gestor sem nomes de modelos.
* Frases pessoais: outro médico e o administrador recebem 404; favoritas e atalhos próprios valem só para o usuário;
  outra organização não vê nenhuma frase (row level security).

## Limitações

* O arquivo exportado não é cifrado: o médico deve guardá-lo como guarda seus documentos (não contém dados de
  pacientes, só o texto dos modelos).
* Recuperar numa conta nova depende de o médico ter exportado antes (ou de ter oferecido cópia à instituição).
