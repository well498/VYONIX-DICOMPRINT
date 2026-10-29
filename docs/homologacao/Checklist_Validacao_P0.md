# VYONIX — Checklist de validação do P0 (no seu computador)

Marque cada item. Para cada um, guarde a evidência indicada (foto da tela ou arquivo). O P0 só é considerado
resolvido com este checklist preenchido no seu Windows; a aprovação do CI do GitHub não o substitui.

**Antes:** siga o *Procedimento de recuperação* até o Passo 4 (versão de teste instalada por cima).

| # | Validar | Como (sem comandos) | Resultado esperado | Evidência | OK? |
|---|---|---|---|---|---|
| 1 | **Atualização direto sobre a versão instalada**, sem desinstalar | Execute `VYONIX_Homologacao_Setup_x64.exe` e deixe marcado "Concluir a atualização agora" | A janela de atualização termina com "Atualização concluída". Pacientes, estudos e usuários continuam lá | Foto da lista de pacientes/estudos e `C:\ProgramData\VYONIX\Logs\atualizacao.log` | ☐ |
| 2 | **Backend, frontend e banco funcionando** | Menu Iniciar → VYONIX → **VYONIX - Verificar funcionamento** (abre o sistema; se algo falhar, abre um relatório dizendo o que está parado: serviço, banco ou página web). Depois **VYONIX - Validar instalacao** | O sistema abre no navegador e você entra com o seu usuário. Na validação, C1–C4 aparecem como APROVADO | Relatório `VYONIX_Validacao_*.html` (Área de Trabalho) | ☐ |
| 3 | **Inicialização automática após reiniciar**, sem login e sem terminal | Reinicie o Windows e **não entre** com o seu usuário. Espere 5 minutos e abra o VYONIX **de outro computador ou do celular**. Depois entre no Windows e rode **VYONIX - Validar instalacao** | O VYONIX abre antes do login. A validação mostra C6/C7 como APROVADO (serviços iniciados pelo Windows, sem falhas registradas) | Foto da tela do outro aparelho com o relógio visível + relatório | ☐ |
| 4 | **Acesso pelo navegador**: localhost e IP | Neste computador: `https://localhost:8444`. De outro aparelho na mesma rede: `https://IP-DESTE-COMPUTADOR:8444` (o IP aparece no relatório de validação) | Tela de login nos dois. O aviso de certificado é esperado (certificado próprio); não desligue nenhuma proteção | Foto das duas telas | ☐ |
| 5a | **Reparar** | Menu Iniciar → VYONIX → **VYONIX - Reparar instalacao**; leia o diagnóstico e digite SIM se houver o que reparar | "Nada a reparar" ou "reparo concluído"; o sistema continua abrindo | Foto da janela | ☐ |
| 5b | **Desinstalar** preservando os dados | Configurações → Aplicativos → VYONIX → Desinstalar | Termina sem erro. `C:\Program Files\VYONIX\Platform` fica vazia ou some. `C:\ProgramData\VYONIX` continua lá. O DICOM Print continua funcionando | Foto das duas pastas + `C:\ProgramData\VYONIX\Logs\instalador.log` | ☐ |
| 5c | **Reinstalar** preservando os dados | Execute de novo `VYONIX_Homologacao_Setup_x64.exe` (deixe marcado "Concluir a atualização agora") | Os mesmos pacientes, estudos DICOM, usuários e configurações de antes | Foto da lista de pacientes/estudos | ☐ |

**Se algum item falhar:** não apague nada. Rode **VYONIX - Verificar funcionamento** e envie o relatório e os
arquivos da seção "Coletar os registros" do procedimento. Para voltar à instalação anterior, use
`Reverter_VYONIX.cmd` (seção "Se a atualização falhar — reversão").

**Também a validar depois (registrado como pendente):** Windows 10 e Windows 11 (se houver os dois), e a abertura
real no Weasis numa estação de teste.
