# Decisões do proprietário — 05/11/2026 22:05

## 1. Isolamento por unidade = P0 BLOQUEANTE da 0.3.2
1. Cada técnico vê somente exames das unidades autorizadas.
2. Quem tem várias unidades acessa exclusivamente essas.
3. Exames sem unidade ficam restritos até a vinculação correta.
4. Controle no backend, APIs, consultas, PACS e visualizadores (não só menus).
5. A instituição continua a fronteira principal; nada automático entre instituições.
6. Toda alteração (médico, prioridade, estado, dados) revalida permissões.
7. Financeiro sem dados clínicos/pessoais desnecessários.
8. Auditoria de operações e de tentativas de acesso indevido.
- Testes: duas unidades fictícias, técnicos com permissões distintas, exames em cada unidade; nada visível/alterável fora da autorização, inclusive por API direta.
- Proibido migrar definitivamente estudos antigos sem unidade antes de simulação aprovada.
- 0.3.2 só é liberada com testes de isolamento e segurança aprovados e sem regressões críticas.
- Agentes: A01, A02, A04, A07, A08.

## 2. Portal Único do Paciente — arquitetura aprovada definitivamente
1. Uma conta pessoal por paciente (login e senha próprios, ativação segura).
2. Cadastro na clínica prepara automaticamente o acesso.
3. Conta verificada existente → vínculo do novo cadastro institucional após verificação segura da identidade.
4. Exames e laudos liberados de várias instituições num só ambiente.
5. Clínicas independentes (cadastros, usuários, permissões, dados).
6. Nenhuma clínica vê exames de outra só por atender o mesmo paciente.
7. Notificações por WhatsApp/e-mail, manual ou automática, conforme a instituição.
8. Links levam ao Portal e exigem autenticação antes dos resultados.
9. Expiração do convite não elimina o acesso autorizado.
10. Auditoria de vinculações, acessos, compartilhamentos e alterações de identidade.
- Incorporar à arquitetura, modelo de dados, backlog e testes de segurança. Agentes A01, A03, A04, A05, A07, A08 (+A02, A06).
- Ordem: depois do P0 de unidade (o portal depende do isolamento correto).
