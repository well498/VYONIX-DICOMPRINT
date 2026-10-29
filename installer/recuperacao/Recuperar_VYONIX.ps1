# VYONIX - Recuperacao de instalacao com defeito (P0).
# Padrao: SOMENTE DIAGNOSTICO (nada e alterado) e relatorio na Area de Trabalho.
# Com -Aplicar (e a confirmacao digitada "RECUPERAR"): deixa o computador pronto para reinstalar:
#   - desliga a recuperacao automatica, para e remove os servicos VyonixPacsEngine, VyonixCore, VyonixWorker e
#     VyonixPostgreSQL (nunca o VyonixDicomPrint);
#   - encerra processos que executam arquivos da pasta do programa (Program Files\VYONIX\Platform);
#   - RENOMEIA a pasta do programa que sobrou para Platform.anterior-<data> (nao apaga; pode ser removida depois);
#   - remove o registro de desinstalacao do VYONIX SOMENTE se o desinstalador nao existir mais (copia .reg salva antes).
# NUNCA altera: dados em ProgramData\VYONIX (banco, estudos DICOM, configuracoes, usuarios, auditoria, backups),
# regras de firewall de outros programas, o VYONIX DICOM Print.
param([switch]$Aplicar, [string]$Saida = "", [switch]$SemAbrir, [switch]$SemConfirmar)
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$agora = Get-Date
if (-not $Saida) { $Saida = [Environment]::GetFolderPath("Desktop") }
if (-not (Test-Path $Saida)) { $Saida = $env:TEMP }
$tag = $agora.ToString("yyyy-MM-dd_HH-mm-ss")
$arq = Join-Path $Saida ("VYONIX_Recuperacao_" + $tag + ".html")
$logf = Join-Path $Saida ("VYONIX_Recuperacao_" + $tag + ".log")
$app = Join-Path $env:ProgramFiles "VYONIX\Platform"
$dados = Join-Path $env:ProgramData "VYONIX"
$servicos = @("VyonixPacsEngine", "VyonixCore", "VyonixWorker", "VyonixPostgreSQL")
$appId = "{EE8E242D-1625-4E1B-8317-5BFD8610DD26}_is1"
$res = New-Object System.Collections.ArrayList
$acoes = New-Object System.Collections.ArrayList
function Log($m) { $l = (Get-Date).ToString("HH:mm:ss") + "  " + $m; Add-Content -Path $logf -Value $l -Encoding utf8; Write-Host $l }
function Add-Res($id, $titulo, $estado, $detalhe, $acao) {
  [void]$res.Add([pscustomobject]@{ id=$id; titulo=$titulo; estado=$estado; detalhe=$detalhe; acao=$acao }) }
function Html($s) { [System.Net.WebUtility]::HtmlEncode([string]$s) }
function Admin { ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }

function Diagnostico {
  $res.Clear()
  # R1 registro de desinstalacao (Inno Setup)
  $reg = $null
  foreach ($k in @("HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$appId", "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\$appId")) {
    if (Test-Path $k) { $reg = Get-ItemProperty $k; $script:regKey = $k } }
  if (-not $reg) { Add-Res "R1" "Registro do VYONIX em Programas e Recursos" "AUSENTE" "Nao ha registro de instalacao do VYONIX." "" }
  else {
    $un = ($reg.UninstallString -replace '"', '').Split(" /")[0]
    $existe = Test-Path $un
    $e = if ($existe) { "OK" } else { "DEFEITO" }
    Add-Res "R1" "Registro do VYONIX em Programas e Recursos" $e ("Versao " + $reg.DisplayVersion + "; pasta " + $reg.InstallLocation + "; desinstalador " + $un + $(if ($existe) { " (existe)" } else { " (NAO existe: registro orfao)" })) $(if (-not $existe) { "Use -Aplicar: o registro orfao e removido (copia .reg salva)." } else { "" })
  }
  # R2 pasta do programa
  if (Test-Path $app) {
    $n = @(Get-ChildItem $app -Recurse -File -ErrorAction SilentlyContinue).Count
    $exe = Test-Path (Join-Path $app "vyonix-deploy.exe")
    Add-Res "R2" "Pasta do programa" $(if ($exe) { "OK" } else { "DEFEITO" }) ("$app - $n arquivo(s); vyonix-deploy.exe " + $(if ($exe) { "presente" } else { "AUSENTE (instalacao incompleta)" })) $(if (-not $exe) { "Use -Aplicar: a pasta e renomeada (nao apagada) e o instalador grava uma nova." } else { "" })
  } else { Add-Res "R2" "Pasta do programa" "AUSENTE" "$app nao existe." "" }
  # R3 servicos
  foreach ($s in $servicos) {
    $w = Get-CimInstance Win32_Service -Filter "Name='$s'" -ErrorAction SilentlyContinue
    $flag = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\$s" -Name DeleteFlag -ErrorAction SilentlyContinue).DeleteFlag
    if (-not $w) { Add-Res "R3" "Servico $s" "AUSENTE" "Nao registrado." ""; continue }
    $bin = $null
    if ($w.PathName -match '^"([^"]+)"') { $bin = $matches[1] } elseif ($w.PathName -match '^(.+?\.exe)') { $bin = $matches[1] }
    $binOk = if ($bin) { Test-Path $bin } else { $false }
    $det = "$($w.State), inicio $($w.StartMode), conta $($w.StartName), programa $bin" + $(if (-not $binOk) { " (ARQUIVO AUSENTE)" } else { "" }) + $(if ($flag -eq 1) { "; MARCADO PARA EXCLUSAO (sai ao reiniciar o Windows)" } else { "" })
    $e = if ($flag -eq 1) { "REINICIAR" } elseif (-not $binOk) { "DEFEITO" } else { "OK" }
    $acao = if ($flag -eq 1) { "Reinicie o Windows antes de reinstalar." } elseif (-not $binOk) { "Use -Aplicar: o servico orfao e removido." } else { "" }
    Add-Res "R3" "Servico $s" $e $det $acao
  }
  # R4 processos da pasta do programa
  $d = [IO.Path]::GetFullPath($app).TrimEnd('\') + '\'
  $procs = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($d, [StringComparison]::OrdinalIgnoreCase) })
  if ($procs.Count) { Add-Res "R4" "Processos usando a pasta do programa" "ATENCAO" (($procs | ForEach-Object { "$($_.Name) (PID $($_.ProcessId))" }) -join ", ") "Prendem arquivos e impedem desinstalar/atualizar. -Aplicar os encerra (so os do VYONIX Platform)." }
  else { Add-Res "R4" "Processos usando a pasta do programa" "OK" "Nenhum." "" }
  # R5 dados preservados
  $itens = @(
    @("Configuracao do sistema", (Join-Path $dados "Platform\config.json")),
    @("Banco PostgreSQL (cluster)", (Join-Path $dados "PostgreSQL\17\data\PG_VERSION")),
    @("Registro do DEPLOY", (Join-Path $dados "Deploy\deploy.db")))
  $txt = ($itens | ForEach-Object { $_[0] + ": " + $(if (Test-Path $_[1]) { "presente" } else { "ausente" }) }) -join "; "
  $bk = @(Get-ChildItem (Join-Path $dados "Backups") -Directory -ErrorAction SilentlyContinue).Count
  Add-Res "R5" "Dados do VYONIX (ProgramData) - nunca alterados por esta ferramenta" "INFO" ($txt + "; backups: $bk") "Ao reinstalar, o instalador reconhece estes dados e faz uma ATUALIZACAO (backup antes)."
  # R6 portas
  foreach ($porta in @(8444, 5544)) {
    $c = @(Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue)
    if ($c.Count) { $p = Get-Process -Id $c[0].OwningProcess -ErrorAction SilentlyContinue
      Add-Res "R6" "Porta $porta" "INFO" ("Em uso por " + $(if ($p) { $p.Name + " (PID " + $p.Id + ")" } else { "PID " + $c[0].OwningProcess })) "" }
    else { Add-Res "R6" "Porta $porta" "INFO" "Livre." "" }
  }
  # R7 reinicio pendente
  $pfr = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager" -Name PendingFileRenameOperations -ErrorAction SilentlyContinue).PendingFileRenameOperations
  $vy = @($pfr | Where-Object { $_ -like "*VYONIX*" })
  Add-Res "R7" "Reinicio do Windows pendente para arquivos do VYONIX" $(if ($vy.Count) { "REINICIAR" } else { "OK" }) $(if ($vy.Count) { "$($vy.Count) arquivo(s) aguardando o reinicio." } else { "Nenhum." }) $(if ($vy.Count) { "Reinicie o Windows antes de reinstalar." } else { "" })
  # R8 registros
  $logs = @()
  $il = Join-Path $dados "Logs\instalador.log"
  if (Test-Path $il) { $logs += "instalador.log (ultimas linhas): " + ((Get-Content $il -Tail 15 -ErrorAction SilentlyContinue) -join " | ") }
  $inno = @(Get-ChildItem $env:TEMP -Filter "Setup Log*.txt" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 2)
  foreach ($f in $inno) { $logs += $f.Name + ": " + ((Get-Content $f.FullName -Tail 8 -ErrorAction SilentlyContinue) -join " | ") }
  Add-Res "R8" "Registros de instalacao/desinstalacao" "INFO" $(if ($logs.Count) { $logs -join "  ||  " } else { "Nenhum registro encontrado." }) "Envie este relatorio: ele traz a causa da falha."
}

function Aplicar-Recuperacao {
  Log "=== recuperacao: inicio (dados em $dados NAO sao alterados)"
  foreach ($s in $servicos) {
    if (-not (Get-Service -Name $s -ErrorAction SilentlyContinue)) { continue }
    Log "servico $s : sem recuperacao automatica, desativado, parado"
    Start-Process -FilePath sc.exe -ArgumentList "failure $s reset= 0 actions= `"`"" -Wait -NoNewWindow | Out-Null
    & sc.exe config $s start= disabled | Out-Null
    & sc.exe stop $s | Out-Null
    for ($i = 0; $i -lt 60; $i++) { $st = (Get-Service -Name $s -ErrorAction SilentlyContinue).Status; if (-not $st -or $st -eq "Stopped") { break }; Start-Sleep 1 }
    $w = Get-CimInstance Win32_Service -Filter "Name='$s'" -ErrorAction SilentlyContinue
    if ($w -and $w.ProcessId) { Log "servico $s nao parou: encerrando PID $($w.ProcessId)"; & taskkill.exe /F /T /PID $w.ProcessId | Out-Null }
    $r = & sc.exe delete $s; Log ("sc delete $s : " + ($r -join " ")); [void]$acoes.Add("Servico $s removido (ou marcado para exclusao)")
  }
  $d = [IO.Path]::GetFullPath($app).TrimEnd('\') + '\'
  Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($d, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object {
    Log "encerrando $($_.Name) PID $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    [void]$acoes.Add("Processo $($_.Name) encerrado") }
  Start-Sleep 2
  if (Test-Path $app) {
    $novo = "Platform.anterior-" + $tag
    try { Rename-Item -Path $app -NewName $novo -ErrorAction Stop; Log "pasta do programa renomeada para $novo"; [void]$acoes.Add("Pasta do programa renomeada para $novo (nao apagada)") }
    catch { Log ("nao foi possivel renomear a pasta do programa: " + $_.Exception.Message); [void]$acoes.Add("Pasta do programa NAO renomeada (arquivo em uso): reinicie o Windows e rode de novo") }
  }
  if ($script:regKey) {
    $reg = Get-ItemProperty $script:regKey
    $un = ($reg.UninstallString -replace '"', '').Split(" /")[0]
    if (-not (Test-Path $un)) {
      $bak = Join-Path $Saida ("VYONIX_registro_desinstalacao_" + $tag + ".reg")
      & reg.exe export ($script:regKey -replace '^HKLM:', 'HKLM') $bak /y | Out-Null
      Remove-Item $script:regKey -Recurse -Force; Log "registro orfao removido (copia: $bak)"
      [void]$acoes.Add("Registro de desinstalacao orfao removido (copia em $bak)")
    }
  }
  Log "=== recuperacao: fim"
}

Write-Host "VYONIX - recuperacao de instalacao. Modo: $(if ($Aplicar) { 'APLICAR' } else { 'somente diagnostico' })"
if ($Aplicar -and -not (Admin)) { Write-Host "E preciso executar como administrador (use Recuperar_VYONIX.cmd)."; exit 2 }
$script:regKey = $null
Diagnostico
$antes = @($res | ForEach-Object { $_ })
if ($Aplicar) {
  if (-not $SemConfirmar) {
    Write-Host ""
    Write-Host "Isto vai parar e remover os servicos do VYONIX Platform e renomear a pasta do programa."
    Write-Host "Os DADOS (banco, estudos, configuracoes, usuarios, auditoria, backups) NAO serao alterados."
    $c = Read-Host "Digite RECUPERAR para continuar"
    if ($c -ne "RECUPERAR") { Write-Host "Cancelado. Nada foi alterado."; exit 3 }
  }
  Aplicar-Recuperacao
  Diagnostico
}
$cor = @{ "OK"="#2e7d4f"; "AUSENTE"="#45606f"; "INFO"="#45606f"; "DEFEITO"="#b3261e"; "REINICIAR"="#a85a00"; "ATENCAO"="#a85a00" }
function Tabela($lst) { ($lst | ForEach-Object { "<tr><td>$(Html $_.id)</td><td><span class='b' style='background:$($cor[$_.estado])'>$(Html $_.estado)</span></td><td><strong>$(Html $_.titulo)</strong><div>$(Html $_.detalhe)</div>" + $(if ($_.acao) { "<div class='a'>O que fazer: $(Html $_.acao)</div>" } else { "" }) + "</td></tr>" }) -join "`n" }
$prox = if (@($res | Where-Object { $_.estado -eq "REINICIAR" }).Count) { "Reinicie o Windows e depois instale a versao nova normalmente." }
        elseif (@($res | Where-Object { $_.estado -in @("DEFEITO", "ATENCAO") }).Count) { "Execute Recuperar_VYONIX.cmd e escolha APLICAR; depois instale a versao nova." }
        else { "O computador esta pronto: instale a versao nova normalmente (ela reconhece os dados e faz uma atualizacao)." }
$html = @"
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>VYONIX - Recuperacao da instalacao</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;background:#f1f5f7;color:#16242f;margin:0;padding:24px}main{max-width:980px;margin:0 auto;background:#fff;border:1px solid #d7e0e6;border-radius:10px;padding:24px}
table{width:100%;border-collapse:collapse;margin-top:10px}td{border-top:1px solid #e3e9ee;padding:8px;vertical-align:top}.b{color:#fff;border-radius:99px;padding:2px 10px;font-size:.8rem;white-space:nowrap}.a{color:#45606f;margin-top:4px}</style></head>
<body><main><h1>VYONIX - Recuperacao da instalacao</h1>
<p>Computador <strong>$(Html $env:COMPUTERNAME)</strong> - $($agora.ToString("dd/MM/yyyy HH:mm")) - modo: <strong>$(if ($Aplicar) { "APLICAR" } else { "somente diagnostico (nada alterado)" })</strong></p>
<h2>Proximo passo</h2><p><strong>$(Html $prox)</strong></p>
$(if ($Aplicar) { "<h2>O que foi feito</h2><ul>" + (($acoes | ForEach-Object { "<li>$(Html $_)</li>" }) -join "") + "</ul><h2>Situacao antes</h2><table>$(Tabela $antes)</table><h2>Situacao depois</h2>" } else { "<h2>Situacao</h2>" })
<table>$(Tabela $res)</table>
<p style="color:#45606f">Dados em ProgramData\VYONIX e o VYONIX DICOM Print nunca sao alterados por esta ferramenta. Registro desta execucao: $(Html $logf)</p></main></body></html>
"@
$html | Out-File -FilePath $arq -Encoding utf8
$res | ForEach-Object { Write-Host ("[" + $_.estado + "] " + $_.titulo + ": " + $_.detalhe) }
Write-Host ""; Write-Host ("Proximo passo: " + $prox); Write-Host ("Relatorio: " + $arq)
if (-not $SemAbrir) { Start-Process $arq }
