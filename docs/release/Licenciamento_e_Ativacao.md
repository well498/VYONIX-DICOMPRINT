# Licenciamento e Ativação

**VYONIX DICOM Print {VERSION}** · licenciamento offline, formato 2

O VYONIX DICOM Print funciona sem internet. A ativação é feita por arquivos: o computador do cliente exporta uma **solicitação**, o administrador emite a **licença assinada** no VYONIX License Manager e o cliente importa o arquivo. O VYONIX DICOM Print só **verifica** licenças: ele não contém nenhuma função de emissão nem a chave privada.

## 1. Primeira abertura: tela de ativação

Sem licença válida nem demonstração ativa, o VYONIX abre a tela **Ativação do VYONIX DICOM Print**:

| Botão | O que faz |
|---|---|
| **Iniciar demonstração de 5 dias** | Libera todas as funções por 120 horas corridas a partir de agora (uma demonstração por computador). |
| **Ativar licença comercial** | Importa o arquivo `.vylic` recebido do administrador (requer a senha de administrador do VYONIX, se definida). |
| **Exportar solicitação** | Gera o arquivo `.vyreq` (ou copia o código `VYXR2-…`) para enviar ao administrador, com o motivo (primeira ativação, reinstalação, troca de disco…). |
| **Visualizar Hardware ID** | Mostra o VYONIX Hardware ID, o VYONIX Installation ID e quais componentes foram considerados. |

Até a ativação, **recepção DICOM (C-STORE), impressão, DICOM Print SCP e regras automáticas ficam suspensos**: os equipamentos recebem recusa transitória (tentam de novo depois) e os trabalhos aguardam na fila. Cadastros, configurações, calibrações e artes BMP podem ser preparados normalmente e são preservados na ativação. A mesma tela fica disponível no menu **Licença**.

## 2. Identificadores

**VYONIX Hardware ID** (`VYXH-XXXXX-XXXXX-XXXXX-XXXXX`) — combinação normalizada de: UUID do computador (SMBIOS), placa-mãe (fabricante, modelo e número de série), identificador do Windows (`MachineGuid`), número de série do disco que contém o Windows e a chave do TPM 2.0 criada pelo VYONIX. As placas de rede físicas são um componente auxiliar e não entram no ID. Valores genéricos de fábrica são ignorados. Cada componente é transformado em um resumo SHA-256: **nenhum número de série legível aparece na solicitação, no diagnóstico ou na licença**.

**VYONIX Installation ID** (`VYXI-…`) — criado a cada **instalação nova** e mantido nas **atualizações**.

A licença vincula ao mesmo tempo Product ID, Hardware ID (com os resumos de cada componente), Installation ID, License ID, recursos, quantidade de equipamentos e de impressoras, validade e a assinatura digital Ed25519.

## 3. Políticas obrigatórias

| Situação | Resultado |
|---|---|
| **Atualização oficial** (instalar a nova versão por cima) | Installation ID, ativação, licença, DEMO em andamento, equipamentos, regras, calibrações, configurações e artes BMP preservados. Nenhuma nova licença. |
| **Desinstalar e instalar de novo** | A desinstalação encerra a ativação local. A instalação seguinte recebe **novo Installation ID**; a licença anterior não é aceita; é preciso exportar nova solicitação e o administrador emite a licença (reativação). |
| **Troca de disco, placa-mãe, computador ou reinstalação do Windows** | A licença deixa de corresponder ao computador. Exporte nova solicitação com o motivo; o administrador usa **REATIVAR / EMITIR NOVA LICENÇA** no License Manager. |
| **Componente temporariamente ilegível** (ex.: falha de leitura do disco pelo Windows) | Tolerado se os demais componentes coincidirem e uma placa de rede autorizada estiver presente. |
| **Licença copiada para outro computador ou outra instalação** | Recusada (hardware/instalação não correspondem; com TPM, também falta a prova de posse). |
| **Licença alterada** (qualquer byte) | Recusada: assinatura inválida. Arquivos com nome ou estrutura "parecidos" não são aceitos. |
| **Licença permanente** | Sem vencimento comercial; continua sujeita à assinatura, ao hardware e à instalação. |
| **Licença vencida** | Funções suspensas; o aviso aparece nos 15 dias anteriores. A renovação é um novo arquivo `.vylic`. |

Como a atualização é distinguida da reinstalação: antes de copiar os arquivos, o instalador consulta a entrada de desinstalação do produto mantida pelo Windows; depois, `Vyonix.exe --installation install --upgrade|--fresh` aplica a decisão sobre o registro selado da instalação. A desinstalação executa `--installation uninstall`. Não depende apenas da presença de um arquivo.

## 4. Demonstração (DEMO) de 5 dias

- 120 horas **corridas** a partir do início: fechar o programa ou desligar o computador não pausa a contagem.
- **Uma por computador**: o registro fica selado no banco, em `%ProgramData%\VYONIX\Licensing` e no registro do Windows — locais que a desinstalação (mesmo com "remover dados") e a limpeza de configurações não apagam. Reinstalar não concede outra demonstração; a contagem continua de onde estava.
- Alterar o relógio não concede tempo (ver seção 6).
- Tempo restante na página Licença e no Painel; aviso nas últimas 24 horas; as páginas impressas identificam "DEMONSTRAÇÃO" no rodapé (fora da área das imagens).
- Ao terminar, as funções são suspensas; a ativação comercial pode ser feita a qualquer momento, sem perder configurações.
- **DEMO assinada:** para uma nova avaliação autorizada (ou prevenção mais forte de reutilização), o administrador emite uma licença do tipo DEMO no License Manager, que registra cada computador que já recebeu DEMO.

**Limite:** uma demonstração exclusivamente offline, sem estado externo confiável, não é imune à restauração completa de uma imagem do disco nem a um administrador local que apague todos os locais do cofre ao mesmo tempo.

## 5. Proteção contra clonagem — camadas

1. **Hardware:** componentes atuais × autorizados (nenhum componente forte pode ter mudado).
2. **Instalação:** o Installation ID precisa ser o da licença.
3. **Assinatura:** Ed25519, chave pública embutida, identificação da chave emissora (`key_id`).
4. **TPM 2.0 (quando disponível):** chave ECDSA P-256 (ou RSA 2048) **não exportável** no Microsoft Platform Crypto Provider, criada pelo instalador. Se a licença inclui essa chave, o TPM precisa assinar um desafio aleatório a cada verificação periódica; uma cópia do disco em outro computador não consegue assinar.
5. **Integridade de estado:** registros selados (HMAC-SHA256, chave aleatória protegida pelo DPAPI do Windows no escopo da máquina) em três locais; um registro presente com selo inválido é tratado como adulteração (funções suspensas, diagnóstico e revalidação administrativa).

**Limites documentados:** sem TPM, a clonagem integral do disco ou de uma máquina virtual reproduz os identificadores e o selo; restaurar snapshots devolve o estado anterior; manipulação avançada do sistema por um administrador local pode contornar camadas locais. Nenhuma proteção exclusivamente offline é absoluta.

## 6. VYONIX Time Integrity

Registra de forma protegida a data da ativação, o último horário confiável, a última execução, as inicializações do Windows e as inconsistências (histórico na página Licença e no diagnóstico).

- **Horário confiável:** só avança. Com o VYONIX em execução, avança pelo relógio monotônico do Windows (`GetTickCount64`, que não muda quando alguém altera a data); entre execuções, pela data do Windows — exceto quando, na mesma inicialização do Windows, a hora de inicialização calculada mudou (prova de alteração do relógio).
- **Retrocesso:** data do Windows mais de **26 horas** antes do horário confiável, ou mais de 48 horas antes da emissão assinada da licença → funções suspensas, motivo exibido, evento registrado. Corrigir a data libera as funções; se o horário confiável estiver errado (ex.: relógio adiantado por engano e o computador reiniciado assim), use a revalidação administrativa.
- **Avanço:** detectado com evidência (durante a execução ou na mesma inicialização) e não incorporado ao horário confiável; ao voltar a data, nada é bloqueado e nenhum tempo foi ganho.
- **Correções legítimas:** todos os horários são UTC — fuso horário e horário de verão não alteram a contagem; ajustes de NTP e pequenas correções (até 26 h) não bloqueiam e não devolvem tempo (o horário usado para validade e DEMO é o maior entre o relógio e o horário confiável).
- **Fontes confiáveis:** relógio monotônico e datas assinadas pelo License Manager (emissão e revalidações). NTP não é usado (protocolo sem autenticação; o produto funciona offline).
- O histórico temporal tem proteção de integridade, mas não é uma fonte absoluta de tempo em ambientes offline.

## 7. Recuperação administrativa

1. Licença → **Exportar diagnóstico…** (JSON sem dados de pacientes: situação, componentes considerados, histórico temporal, integridade, um código de uso único).
2. O administrador abre o diagnóstico no License Manager → **Revalidação** e emite o arquivo `.vyreval` assinado (redefine o horário confiável e/ou aceita o estado atual dos registros).
3. Licença → **Importar revalidação…**. Cada revalidação só vale para o diagnóstico daquela instalação e uma única vez. A revalidação **não devolve** tempo de licença nem de DEMO.

Nenhuma licença legítima fica bloqueada sem esse procedimento.

## 8. Revogação

A revogação é administrativa. Em ambiente offline ela só tem efeito no computador quando a **lista de revogação** assinada (`.vyrevoke`) é importada em Licença → **Importar lista de revogação…** (listas mais antigas que a instalada são recusadas). Sem a lista, a licença revogada continua valendo até o vencimento.

## 9. Impressoras autorizadas

Quando a licença limita impressoras, a primeira impressão em cada impressora ocupa uma vaga (a impressora virtual VYONIX PDF não conta). Esgotadas as vagas, o trabalho falha com o motivo; o administrador do VYONIX pode liberar uma vaga na página Licença (registrado no Histórico) ou solicitar a ampliação.

## 10. Linha de comando (suporte)

`Vyonix.exe --license status|request|demo|install|diagnostic|revalidation|revocation [--file ARQUIVO] --report saida.json`

## 11. Privacidade (LGPD)

Solicitações, diagnósticos e licenças contêm apenas resumos criptográficos de identificadores de hardware, os IDs VYONIX, a versão, o nome da unidade e o nome do cliente na licença. Nenhum dado de paciente.
