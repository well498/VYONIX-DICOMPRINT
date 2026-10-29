# VYONIX - Validacao da instalacao (P0): somente leitura. Nao altera servicos, configuracoes nem dados.
# Uso: duplo clique em Validar_VYONIX.cmd. Gera um relatorio HTML na Area de Trabalho e o abre.
param([int]$Porta = 8444, [string]$Saida = "", [switch]$SemAbrir)
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$agora = Get-Date
if (-not $Saida) { $Saida = [Environment]::GetFolderPath("Desktop") }
if (-not (Test-Path $Saida)) { $Saida = $env:TEMP }
$arq = Join-Path $Saida ("VYONIX_Validacao_" + $agora.ToString("yyyy-MM-dd_HH-mm") + ".html")
$app = Join-Path $env:ProgramFiles "VYONIX\Platform"
$exe = Join-Path $app "vyonix-deploy.exe"
$res = New-Object System.Collections.ArrayList
function Add-Res($id, $titulo, $estado, $detalhe, $acao) {
  [void]$res.Add([pscustomobject]@{ id=$id; titulo=$titulo; estado=$estado; detalhe=$detalhe; acao=$acao }) }
function Html($s) { [System.Net.WebUtility]::HtmlEncode([string]$s) }

Write-Host "VYONIX - validacao da instalacao (somente leitura). Aguarde..."
$boot = $null; try { $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime } catch {}
$instalado = $null; if (Test-Path $exe) { $instalado = (Get-Item $exe).CreationTime }   # quando o arquivo foi gravado neste disco

# 1. diagnostico de inicializacao do proprio VYONIX
$diag = $null
if (-not (Test-Path $exe)) {
  Add-Res "C1" "VYONIX instalado" "REPROVADO" "Nao encontrei $exe." "Instale o VYONIX e aprove o plano no assistente."
} else {
  try {
    $txt = (& $exe verificar --porta $Porta --json 2>$null) -join "`n"
    $diag = $txt | ConvertFrom-Json
  } catch { $diag = $null }
  if (-not $diag) {
    Add-Res "C1" "VYONIX instalado e configurado" "REPROVADO" "O diagnostico do VYONIX nao respondeu." "Envie este relatorio ao suporte."
  } else {
    $inst = $diag.checks | Where-Object { $_.id -eq "install" }
    if ($inst.status -eq "ok") { Add-Res "C1" "VYONIX instalado e configurado" "APROVADO" $inst.detail "" }
    else { Add-Res "C1" "VYONIX instalado e configurado" "REPROVADO" $inst.detail $inst.fix }
  }
}

# 2. servicos: em execucao, inicio automatico, conta de servico (funciona sem login)
$svcs = @(Get-CimInstance Win32_Service -Filter "Name like 'Vyonix%'" -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne "VyonixDicomPrint" })
$need = @("VyonixPostgreSQL", "VyonixCore", "VyonixWorker")
$falta = @($need | Where-Object { $n = $_; -not ($svcs | Where-Object { $_.Name -eq $n }) })
$ruins = @($svcs | Where-Object { $need -contains $_.Name -and ($_.State -ne "Running" -or $_.StartMode -ne "Auto") })
$contas = @($svcs | Where-Object { $need -contains $_.Name -and -not ($_.StartName -like "NT SERVICE\*" -or $_.StartName -eq "LocalSystem") })
$lista = ($svcs | ForEach-Object { "$($_.Name): $($_.State), $($_.StartMode), conta $($_.StartName)" }) -join "; "
if ($falta.Count -gt 0) { Add-Res "C2" "Servicos do Windows (automaticos, sem login)" "REPROVADO" ("Faltam: " + ($falta -join ", ")) "Menu Iniciar > VYONIX > Assistente de instalacao." }
elseif ($ruins.Count -gt 0 -or $contas.Count -gt 0) { Add-Res "C2" "Servicos do Windows (automaticos, sem login)" "REPROVADO" $lista "Envie este relatorio ao suporte." }
else { Add-Res "C2" "Servicos do Windows (automaticos, sem login)" "APROVADO" ($lista + ". Contas de servico do Windows: funcionam sem nenhum usuario conectado.") "" }

# 3-5. acesso local, pela rede e firewall (do diagnostico)
if ($diag) {
  $loc = $diag.checks | Where-Object { $_.id -eq "web.localhost" }
  if ($loc.status -eq "ok") { Add-Res "C3" "Acesso neste computador (https://localhost:$Porta)" "APROVADO" $loc.detail "" }
  else { Add-Res "C3" "Acesso neste computador (https://localhost:$Porta)" "REPROVADO" $loc.detail $loc.fix }
  $lan = @($diag.checks | Where-Object { $_.id -like "web.lan.*" })
  $ok = @($lan | Where-Object { $_.status -eq "ok" })
  if ($ok.Count -gt 0) { Add-Res "C4" "Acesso pelo IP da rede" "APROVADO" (($diag.urls | Where-Object { $_ -notlike "*localhost*" }) -join "  ") "Confirme de OUTRO computador da rede (passo 3 do roteiro)." }
  else { Add-Res "C4" "Acesso pelo IP da rede" "REPROVADO" (($lan | ForEach-Object { $_.detail }) -join " ") "Envie este relatorio ao suporte." }
  $fw = $diag.checks | Where-Object { $_.id -eq "firewall" }
  if ($fw) {
    $e = if ($fw.status -eq "ok" -or $fw.status -eq "info") { "APROVADO" } else { "ATENCAO" }
    Add-Res "C5" "Firewall do Windows" $e $fw.detail $fw.fix }
}

# 6. reinicializacao real depois da instalacao
$reboot = $false
if ($boot -and $instalado) {
  if ($boot -gt $instalado) { $reboot = $true
    Add-Res "C6" "Reinicializacao real do Windows" "APROVADO" ("Windows ligado em " + $boot.ToString("dd/MM/yyyy HH:mm") + ", depois da instalacao (" + $instalado.ToString("dd/MM/yyyy HH:mm") + "), e o VYONIX esta funcionando.") "" }
  else { Add-Res "C6" "Reinicializacao real do Windows" "PENDENTE" ("O Windows nao foi reiniciado desde a instalacao (" + $instalado.ToString("dd/MM/yyyy HH:mm") + ").") "Reinicie o computador e siga os passos 4 e 5 do roteiro." }
}

# 7. iniciou sem login: o servico do sistema web comecou antes do login do usuario
$core = $svcs | Where-Object { $_.Name -eq "VyonixCore" }
$inicioCore = $null
if ($core -and $core.ProcessId) { try { $inicioCore = (Get-CimInstance Win32_Process -Filter ("ProcessId=" + $core.ProcessId)).CreationDate } catch {} }
$login = $null
try { $login = (@(Get-CimInstance Win32_Process -Filter "Name='explorer.exe'") | Sort-Object CreationDate | Select-Object -First 1).CreationDate } catch {}
if (-not $reboot) { Add-Res "C7" "Funciona sem login de usuario" "PENDENTE" "Depende da reinicializacao (C6)." "Passos 4 e 5 do roteiro." }
elseif ($inicioCore -and $login -and $inicioCore -lt $login) {
  Add-Res "C7" "Funciona sem login de usuario" "APROVADO" ("O sistema web iniciou as " + $inicioCore.ToString("HH:mm:ss") + ", antes do login (" + $login.ToString("HH:mm:ss") + ").") "" }
elseif ($inicioCore -and $login) {
  Add-Res "C7" "Funciona sem login de usuario" "INCONCLUSIVO" ("O sistema web iniciou as " + $inicioCore.ToString("HH:mm:ss") + ", depois do login (" + $login.ToString("HH:mm:ss") + "). O VYONIX inicia alguns minutos apos ligar, com ou sem login.") "Repita: reinicie, NAO entre no Windows por 5 minutos, abra o VYONIX de outro computador (passo 4) e so depois entre e rode esta validacao." }
else { Add-Res "C7" "Funciona sem login de usuario" "INCONCLUSIVO" "Nao foi possivel ler os horarios de inicio." "Use o passo 4 do roteiro (acesso de outro computador antes de entrar no Windows)." }

# relatorio
$cor = @{ "APROVADO"="#2e7d4f"; "REPROVADO"="#b3261e"; "PENDENTE"="#45606f"; "ATENCAO"="#a85a00"; "INCONCLUSIVO"="#a85a00" }
$geral = if (@($res | Where-Object { $_.estado -eq "REPROVADO" }).Count) { "REPROVADO" } elseif (@($res | Where-Object { $_.estado -ne "APROVADO" }).Count) { "INCOMPLETO" } else { "APROVADO" }
$linhas = ($res | ForEach-Object { "<tr><td>$(Html $_.id)</td><td><span class='b' style='background:$($cor[$_.estado])'>$(Html $_.estado)</span></td><td><strong>$(Html $_.titulo)</strong><div>$(Html $_.detalhe)</div>" + $(if ($_.acao) { "<div class='a'>O que fazer: $(Html $_.acao)</div>" } else { "" }) + "</td></tr>" }) -join "`n"
$diagRows = ""
if ($diag) { $diagRows = ($diag.checks | ForEach-Object { "<tr><td>$(Html $_.status)</td><td>$(Html $_.title)</td><td>$(Html $_.detail)</td></tr>" }) -join "`n" }
$html = @"
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>VYONIX - Validacao da instalacao</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;background:#f1f5f7;color:#16242f;margin:0;padding:24px}main{max-width:960px;margin:0 auto;background:#fff;border:1px solid #d7e0e6;border-radius:10px;padding:24px}
table{width:100%;border-collapse:collapse;margin-top:10px}td{border-top:1px solid #e3e9ee;padding:8px;vertical-align:top}.b{color:#fff;border-radius:99px;padding:2px 10px;font-size:.8rem;white-space:nowrap}.a{color:#45606f;margin-top:4px}</style></head>
<body><main><h1>VYONIX - Validacao da instalacao</h1>
<p>Computador: <strong>$(Html $env:COMPUTERNAME)</strong> - usuario $(Html $env:USERNAME) - $($agora.ToString("dd/MM/yyyy HH:mm")) - Windows ligado em $(if ($boot) { $boot.ToString("dd/MM/yyyy HH:mm") } else { "?" }) - porta $Porta</p>
<h2>Resultado geral: $geral</h2><table>$linhas</table>
<h2>Diagnostico detalhado</h2><table>$diagRows</table>
<p style="color:#45606f">Somente leitura: nada foi alterado. Envie este arquivo junto com as fotos do passo 3 e 4.</p></main></body></html>
"@
$html | Out-File -FilePath $arq -Encoding utf8
$res | ForEach-Object { Write-Host ("[" + $_.estado + "] " + $_.titulo + ": " + $_.detalhe) }
Write-Host ""
Write-Host ("Resultado geral: " + $geral)
Write-Host ("Relatorio: " + $arq)
if (-not $SemAbrir) { Start-Process $arq }
