# Notas da Versão

**VYONIX DICOM Print {VERSION}** · compilação {BUILD_DATE} · commit `{COMMIT}`

## Natureza desta versão

Versão de **desenvolvimento para homologação**, correspondente à **Fase 1 — Fundação** do plano de 8 fases. Não é a versão comercial 1.0.0: o número `{VERSION}` indica uma pré-versão de 1.0.0.

**Não validada para uso clínico. Sem declaração de conformidade DICOM.**

## Implementado

- Instalador Windows x64 com atalhos, registro em Programas Instalados, desinstalador e preservação de dados em atualizações.
- Executável `Vyonix.exe` sem dependência de Python instalado.
- Dados em `ProgramData` e `LocalAppData`; nada gravado na pasta do programa.
- Banco SQLite com modelo completo (equipamentos, impressoras, perfis, regras, instâncias, sessões de impressão, trabalhos, eventos, licenças, histórico), migrações atômicas com verificação de integridade e backup automático.
- Logs JSON rotativos, com mascaramento de dados de pacientes.
- Configurações validadas, auditadas, exportáveis e importáveis.
- Histórico de eventos com filtros e exportação CSV; histórico de alterações administrativas.
- Interface com os 12 itens de menu; Dashboard, Configurações, Histórico, Licença (ID da instalação) e Sobre; temas claro e escuro.
- Máquina de estados dos trabalhos de impressão (base da fila da Fase 4).
- Modos de verificação automatizada: `--check` e `--smoke-test`.

## Não implementado nesta versão

| Recurso | Fase prevista |
|---|---|
| Cadastro de equipamentos, Storage SCP (C-ECHO, C-STORE), controle de acesso administrativo | 2 |
| Decodificação e processamento de imagens, pré-visualização, calibração | 3 |
| Impressoras Windows, layouts, papel, fila persistente de impressão | 4 |
| DICOM Print SCP e declaração de conformidade | 5 |
| Motor de regras, editor e simulação, perfis | 6 |
| Serviço Windows, operação em segundo plano, bandeja do sistema | 7 |
| Licenciamento offline assinado, ferramenta de emissão | 8 |

## Limitações conhecidas

- O executável e o instalador não possuem assinatura digital de código; o Windows SmartScreen pode exibir aviso.
- Enquanto o serviço Windows não existir, todos os usuários do computador têm permissão de gravação na pasta de dados em `ProgramData`.
- Os testes automatizados foram executados em máquina virtual Windows do GitHub Actions; o teste em Windows limpo, sem Python, e em Windows 10 deve ser feito na homologação (ver Relatório de Validação).
- A disponibilidade jurídica do nome VYONIX ainda deve ser verificada antes da distribuição comercial.
