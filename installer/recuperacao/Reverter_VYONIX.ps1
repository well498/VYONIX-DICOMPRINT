# VYONIX - Reverter uma recuperacao (P0).
# Usa o estado anterior registrado por Recuperar_VYONIX em ProgramData\VYONIX\Backups\recuperacao-<data>:
#   1. a pasta do programa renomeada (Platform.anterior-<data>) volta a ser Program Files\VYONIX\Platform;
#   2. o registro de Programas e Recursos volta (arquivo .reg salvo), se estiver ausente;
#   3. os servicos sao recriados pelo REPARO oficial do VYONIX DEPLOY (configuracao, contas, recuperacao automatica,
#      firewall) e, para o que faltar, a partir da configuracao registrada (servicos.json);
#   4. confere o funcionamento (backend, frontend e banco).
# NUNCA altera o banco de dados nem os dados em ProgramData\VYONIX. Nada e apagado. Restaurar o banco a partir do
# backup e uma operacao separada, que exige confirmacao propria (veja o procedimento de reversao).
param([string]$Pasta = "", [switch]$SemConfirmar, [string]$Confirmacao = "", [string]$Saida = "", [switch]$SemAbrir)
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$agora = Get-Date; $tag = $agora.ToString("yyyy-MM-dd_HH-mm-ss")
if (-not $Saida) { $Saida = [Environment]::GetFolderPath("Desktop") }
if (-not (Test-Path $Saida)) { $Saida = $env:TEMP }
$arq = Join-Path $Saida ("VYONIX_Reversao_" + $tag + ".html")
$logf = Join-Path $Saida ("VYONIX_Reversao_" + $tag + ".log")
$app = Join-Path $env:ProgramFiles "VYONIX\Platform"
$dados = Join-Path $env:ProgramData "VYONIX"
$ordem = @("VyonixPostgreSQL", "VyonixCore", "VyonixWorker", "VyonixPacsEngine")
$acoes = New-Object System.Collections.ArrayList
function Log($m) { $l = (Get-Date).ToString("HH:mm:ss") + "  " + $m; Add-Content -Path $logf -Value $l -Encoding utf8; Write-Host $l }
function Acao($m) { [void]$acoes.Add($m); Log $m }
function Html($s) { [System.Net.WebUtility]::HtmlEncode([string]$s) }
function Admin { ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
if (-not (Admin)) { Write-Host "Execute como administrador (use Reverter_VYONIX.cmd)."; exit 2 }

if (-not $Pasta) {
  $cands = @(Get-ChildItem (Join-Path $dados "Backups") -Directory -Filter "recuperacao-*" -ErrorAction SilentlyContinue | Sort-Object Name -Descending)
  $Pasta = ($cands | Where-Object { $m = Join-Path $_.FullName "recuperacao.json"; (Test-Path $m) -and ((Get-Content $m -Raw | ConvertFrom-Json).pasta_renomeada) } | Select-Object -First 1).FullName
  if (-not $Pasta -and $cands.Count) { $Pasta = $cands[0].FullName } }
if (-not $Pasta -or -not (Test-Path (Join-Path $Pasta "recuperacao.json"))) { Write-Host "Nenhuma recuperacao registrada para reverter em $dados\Backups."; exit 6 }
$meta = Get-Content (Join-Path $Pasta "recuperacao.json") -Raw | ConvertFrom-Json
$est = Join-Path $Pasta "estado-anterior"
$svcs = @()
# servicos.json desta recuperacao e das anteriores (uma reexecucao pode nao ter encontrado mais os servicos)
foreach ($f in @(Get-ChildItem (Join-Path $dados "Backups") -Filter "servicos.json" -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.FullName -like "*\recuperacao-*\estado-anterior\*" } | Sort-Object FullName -Descending)) {
  $t = Get-Content $f.FullName -Raw -ErrorAction SilentlyContinue
  if ($t -and $t.Trim()) { foreach ($x in @($t | ConvertFrom-Json)) { if ($x -and $x.Name -and -not ($svcs | Where-Object { $_.Name -eq $x.Name })) { $svcs += $x } } } }
$appId = "{EE8E242D-1625-4E1B-8317-5BFD8610DD26}_is1"
$regKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$appId"
$regBak = Join-Path $est "registro-desinstalacao.reg"
$antiga = $meta.pasta_renomeada
$nova = (Test-Path $app) -and (Test-Path (Join-Path $app "vyonix-deploy.exe"))

$plano = @("Recuperacao a reverter: $Pasta ($($meta.tag))")
$impede = $null
if ($antiga -and (Test-Path $antiga)) {
  if ($nova) { $impede = "Ja existe uma instalacao em $app. A reversao nao a substitui: para voltar a anterior, desinstale a atual (dados preservados) e execute de novo." }
  else { if (Test-Path $app) { $plano += "Renomear a pasta incompleta $app para Platform.descartada-$tag (nao apagar)" }; $plano += "Renomear $antiga de volta para $app" } }
elseif ($antiga) { $plano += "A pasta $antiga nao existe mais: a pasta do programa nao e restaurada" }
else { $plano += "A recuperacao nao renomeou a pasta do programa: nada a renomear" }
if (-not (Test-Path $regKey) -and (Test-Path $regBak)) { $plano += "Restaurar o registro de Programas e Recursos ($regBak)" }
$plano += "Recriar os servicos ausentes (" + (($svcs | ForEach-Object { $_.Name }) -join ", ") + ") pelo reparo oficial do VYONIX DEPLOY e conferir o funcionamento"
$plano += "Banco de dados e dados em ${dados}: NAO alterados."
Write-Host "===== O QUE A REVERSAO VAI FAZER ====="; $plano | ForEach-Object { Write-Host $_ }
$codigo = 0; $resultado = ""
if ($impede) { $resultado = "Reversao nao executada: " + $impede; $codigo = 7 }
else {
  $c = "REVERTER"
  if (-not $SemConfirmar) { $c = if ($PSBoundParameters.ContainsKey("Confirmacao")) { $Confirmacao } else { Read-Host "Digite REVERTER para continuar (qualquer outra resposta cancela)" } }
  if ($c -ne "REVERTER") { $resultado = "Cancelado: nada foi alterado."; $codigo = 3 }
  else {
    if ($antiga -and (Test-Path $antiga)) {
      try {
        if (Test-Path $app) { Rename-Item $app ("Platform.descartada-" + $tag) -ErrorAction Stop; Acao "Pasta incompleta renomeada para Platform.descartada-$tag" }
        Rename-Item $antiga (Split-Path $app -Leaf) -ErrorAction Stop; Acao "Pasta do programa restaurada: $app"
      } catch { Acao ("Pasta do programa NAO restaurada: " + $_.Exception.Message); $codigo = 5 } }
    if (-not (Test-Path $regKey) -and (Test-Path $regBak)) { & reg.exe import $regBak 2>&1 | Out-Null; Acao "Registro de Programas e Recursos restaurado" }
    $dep = Join-Path $app "vyonix-deploy.exe"
    if (Test-Path $dep) {
      $o = & $dep repair --approve-all --silent 2>&1; Log ("reparo: codigo $LASTEXITCODE; " + (($o | Select-Object -Last 6) -join " | "))
      Acao ("Reparo oficial executado (codigo $LASTEXITCODE)") }
    foreach ($n in $ordem) {
      $s = $svcs | Where-Object { $_.Name -eq $n } | Select-Object -First 1
      if (-not $s -or (Get-Service -Name $n -ErrorAction SilentlyContinue)) { continue }
      if (-not $s.Exe -or -not (Test-Path $s.Exe)) { Acao "Servico $n nao recriado: programa $($s.Exe) ausente"; $codigo = 5; continue }
      $modo = switch ($s.StartMode) { "Manual" { "Manual" } "Disabled" { "Manual" } default { "Automatic" } }
      New-Service -Name $n -BinaryPathName $s.PathName -DisplayName $s.DisplayName -StartupType $modo -DependsOn @($s.DependOn | Where-Object { $_ }) -ErrorAction SilentlyContinue | Out-Null
      if ($s.Description) { & sc.exe description $n $s.Description | Out-Null }
      if ($s.StartName -and $s.StartName -ne "LocalSystem") { & sc.exe config $n obj= $s.StartName | Out-Null }
      if ($s.Delayed -eq 1) { & sc.exe config $n start= delayed-auto | Out-Null }
      & sc.exe failure $n reset= 86400 actions= restart/60000/restart/60000/restart/60000 | Out-Null
      Acao "Servico $n recriado a partir do estado anterior" }
    foreach ($n in $ordem) { if ((Get-Service -Name $n -ErrorAction SilentlyContinue) -and (Get-Service $n).Status -ne "Running" -and (Get-Service $n).StartType -ne "Disabled") { & sc.exe start $n | Out-Null; Start-Sleep 3 } }
    if (Test-Path $dep) {
      $o = & $dep verificar --esperar 180 2>&1; $vc = $LASTEXITCODE
      Acao ("Verificacao de funcionamento: " + $(if ($vc -eq 0) { "APROVADA (backend, frontend e banco)" } else { "com problemas (codigo $vc): " + (($o | Select-Object -Last 8) -join " | ") }))
      if ($vc -ne 0 -and $codigo -eq 0) { $codigo = 5 } }
    $resultado = if ($codigo -eq 0) { "Reversao concluida: instalacao anterior restaurada e funcionando." } else { "Reversao parcial: veja o que foi feito e envie este relatorio." }
  } }
$html = @"
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>VYONIX - Reversao da recuperacao</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;background:#f1f5f7;color:#16242f;margin:0;padding:24px}main{max-width:980px;margin:0 auto;background:#fff;border:1px solid #d7e0e6;border-radius:10px;padding:24px}li{margin:4px 0}</style></head>
<body><main><h1>VYONIX - Reversao da recuperacao</h1><p>Computador <strong>$(Html $env:COMPUTERNAME)</strong> - $($agora.ToString("dd/MM/yyyy HH:mm"))</p>
<h2>Resultado</h2><p><strong>$(Html $resultado)</strong></p><h2>Plano</h2><ul>$(($plano | ForEach-Object { "<li>$(Html $_)</li>" }) -join "")</ul>
<h2>O que foi feito</h2><ul>$(($acoes | ForEach-Object { "<li>$(Html $_)</li>" }) -join "")</ul>
<p style="color:#45606f">O banco de dados e os dados em ProgramData\VYONIX nao sao alterados pela reversao.</p></main></body></html>
"@
$html | Out-File -FilePath $arq -Encoding utf8
Write-Host ""; Write-Host ("Resultado: " + $resultado); Write-Host ("Relatorio: " + $arq)
if (-not $SemAbrir) { Start-Process $arq }
exit $codigo
