<#
  Validação do executável e do instalador do VYONIX DICOM Print em Windows.

  Uso (PowerShell, como administrador):
    .\tools\ci_validate.ps1 -Installer dist\installer\VYONIX_DICOM_Print_Setup_v1.0.0.dev1_x64.exe `
                            -Version 1.0.0.dev1 -OutDir dist\validation

  Cada verificação registra {id, area, name, ok, detail} em <OutDir>\results.json.
  O script NÃO interrompe na primeira falha: executa tudo e retorna código 1 se algo falhar.
  ATENÇÃO: instala e desinstala o produto na máquina. Use em VM ou runner descartável.
#>
param(
    [Parameter(Mandatory = $true)] [string] $Installer,
    [Parameter(Mandatory = $true)] [string] $Version,
    [string] $DistExe = "dist\Vyonix\Vyonix.exe",
    [string] $OutDir = "dist\validation",
    [string] $LMExe = "",
    [string] $LMInstaller = "",
    [string] $LSExe = ""
)

$ErrorActionPreference = "Stop"
$AppId = "{8C4E2D6A-3F1B-4B7E-9A2C-5D1E7F9B0A11}_is1"
$UninstKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$AppId"
$InstallDir = Join-Path $env:ProgramFiles "VYONIX\DICOM Print"
$InstalledExe = Join-Path $InstallDir "Vyonix.exe"
$DataDir = Join-Path $env:ProgramData "VYONIX\DICOM Print"
$StartMenuLnk = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\VYONIX DICOM Print.lnk"
$LicensingDir = Join-Path $env:ProgramData "VYONIX\Licensing"
$LMUninstKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{5B7A1C3E-9D24-4E61-8F0B-2C7D9E1A4B66}_is1"
$LMInstallDir = Join-Path $env:ProgramFiles "VYONIX\License Manager"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path
$Installer = (Resolve-Path $Installer).Path
$DistExe = (Resolve-Path $DistExe).Path
$Work = Join-Path $OutDir "work"
# Versão de esquema esperada = número de migrações distribuídas (app\database\migrations\m0NNN_*.py).
$ExpectedSchema = @(Get-ChildItem (Join-Path $PSScriptRoot "..\app\database\migrations") -Filter "m0*.py").Count
New-Item -ItemType Directory -Force -Path $Work | Out-Null

$results = New-Object System.Collections.Generic.List[object]

# status: "aprovado" | "nao_verificavel" | "falhou". "Não verificável" = o comportamento do programa foi
# conferido, mas o ambiente não permite comprovar o requisito (ex.: sem TPM real): não conta como aprovado
# e não interrompe o pipeline.
function Add-Result([string]$Id, [string]$Area, [string]$Name, [bool]$Ok, [string]$Detail) {
    $status = if (-not $Ok) { "falhou" } elseif ($Detail -like "NÃO VERIFICÁVEL*") { "nao_verificavel" } else { "aprovado" }
    $results.Add([ordered]@{ id = $Id; area = $Area; name = $Name; ok = $Ok; status = $status; detail = $Detail })
    $mark = @{ aprovado = "PASS"; nao_verificavel = "N/V "; falhou = "FAIL" }[$status]
    Write-Host "[$mark] $Id $Name - $Detail"
}

function Invoke-Check([string]$Id, [string]$Area, [string]$Name, [scriptblock]$Body) {
    try {
        $detail = & $Body
        Add-Result $Id $Area $Name $true ([string]$detail)
    } catch {
        Add-Result $Id $Area $Name $false ($_.Exception.Message)
    }
}

function Run-Exe([string]$Exe, [string[]]$Arguments, [hashtable]$Env = @{}, [int]$TimeoutSec = 180) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = ($Arguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '
    $psi.UseShellExecute = $false
    foreach ($k in $Env.Keys) { $psi.EnvironmentVariables[$k] = $Env[$k] }
    $p = [System.Diagnostics.Process]::Start($psi)
    if (-not $p.WaitForExit($TimeoutSec * 1000)) { $p.Kill(); throw "tempo esgotado ($TimeoutSec s)" }
    return $p.ExitCode
}

function Read-Report([string]$Path) {
    if (-not (Test-Path $Path)) { throw "relatório não gerado: $Path" }
    return Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Smoke([string]$Exe, [string]$Label, [hashtable]$Env, [string[]]$Extra) {
    $report = Join-Path $OutDir "smoke-$Label.json"
    $code = Run-Exe $Exe (@("--smoke-test", "--report", $report) + $Extra) $Env
    $r = Read-Report $report
    $failed = @($r.checks | Where-Object { -not $_.ok })
    if ($code -ne 0 -or $failed.Count -gt 0) {
        $msg = ($failed | ForEach-Object { "$($_.name): $($_.error)" }) -join "; "
        throw "código $code; falhas: $msg"
    }
    return "código 0; $(@($r.checks).Count) verificações OK; plataforma Qt '$($r.qt_platform)'; frozen=$($r.frozen)"
}

function Lic([string]$Label, [string[]]$Arguments) {
    $rep = Join-Path $OutDir "license-$Label.json"
    if (Test-Path $rep) { Remove-Item $rep }
    $code = Run-Exe $InstalledExe (@("--report", $rep) + $Arguments) $clean
    $r = Read-Report $rep
    $r | Add-Member -NotePropertyName exit_code -NotePropertyValue $code -Force
    return $r
}

function Wait-Until([scriptblock]$Cond, [int]$TimeoutSec = 180) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while (-not (& $Cond)) {
        if ($sw.Elapsed.TotalSeconds -gt $TimeoutSec) { throw "tempo esgotado aguardando condição" }
        Start-Sleep -Milliseconds 500
    }
}

function Install-Silent([string]$Log) {
    $code = Run-Exe $Installer @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/TASKS=desktopicon,firewall,service,tray", "/LOG=$Log") @{} 600
    if ($code -ne 0) { throw "instalador retornou $code" }
}

function Test-FirewallRule() {
    $out = & "$env:SystemRoot\System32\netsh.exe" advfirewall firewall show rule name="VYONIX DICOM Print" verbose 2>&1
    return @{ exists = ($LASTEXITCODE -eq 0); text = ($out -join "`n") }
}

function Uninstall-Silent() {
    $un = (Get-ItemProperty $UninstKey).UninstallString.Trim('"')
    $code = Run-Exe $un @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") @{} 300
    if ($code -ne 0) { throw "desinstalador retornou $code" }
    # O desinstalador do Inno Setup se copia para %TEMP% e retorna antes de terminar.
    Wait-Until { -not (Test-Path $UninstKey) -and -not (Test-Path $InstalledExe) } 300
}

$offscreen = @{ QT_QPA_PLATFORM = "offscreen" }
# Ambiente "limpo": sem Python no PATH, sem variáveis do Python.
$cleanPath = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
$clean = @{ PATH = $cleanPath; PYTHONHOME = ""; PYTHONPATH = "" }

# ---------------------------------------------------------------- A. executável em dist
Invoke-Check "EXE-01" "Executável" "Vyonix.exe gerado com metadados de versão" {
    $vi = (Get-Item $DistExe).VersionInfo
    if ($vi.ProductVersion -ne $Version) { throw "ProductVersion='$($vi.ProductVersion)'" }
    $mb = [math]::Round(((Get-ChildItem (Split-Path $DistExe) -Recurse | Measure-Object Length -Sum).Sum / 1MB), 1)
    "ProductVersion=$($vi.ProductVersion); FileVersion=$($vi.FileVersion); pasta onedir=$mb MB"
}
Invoke-Check "EXE-02" "Executável" "Pacote sem ferramenta de licenças, chaves ou testes" {
    $bad = Get-ChildItem (Split-Path $DistExe) -Recurse | Where-Object {
        $_.FullName -match 'license_admin|license_manager|License_Manager|\\tests\\' -or $_.Extension -in '.pem', '.key' }
    if ($bad) { throw "itens proibidos: $($bad.FullName -join ', ')" }
    "nenhum item proibido"
}
Invoke-Check "EXE-03" "Executável" "--version sem console" {
    $rep = Join-Path $OutDir "version.json"
    $code = Run-Exe $DistExe @("--version", "--report", $rep)
    $r = Read-Report $rep
    if ($code -ne 0 -or $r.version -ne $Version) { throw "código $code, versão '$($r.version)'" }
    "versão $($r.version)"
}
Invoke-Check "EXE-04" "Executável" "--check: diretórios, banco, migração e logs" {
    $rep = Join-Path $OutDir "check-dist.json"
    $code = Run-Exe $DistExe @("--check", "--data-dir", (Join-Path $Work "dist-data"), "--report", $rep)
    $r = Read-Report $rep
    if ($code -ne 0 -or -not $r.ok -or $r.schema_version -ne $ExpectedSchema) { throw "código $code; esquema v$($r.schema_version), esperado v$ExpectedSchema" }
    if (-not (Test-Path $r.database)) { throw "banco não criado" }
    if (-not (Test-Path $r.log_file)) { throw "log não criado" }
    "esquema v$($r.schema_version); banco e log criados"
}
Invoke-Check "EXE-05" "Interface" "Smoke test da interface (Qt offscreen)" {
    Smoke $DistExe "dist-offscreen" $offscreen @("--data-dir", (Join-Path $Work "dist-smoke-off"))
}
Invoke-Check "EXE-06" "Interface" "Smoke test da interface (plataforma Windows nativa)" {
    Smoke $DistExe "dist-native" @{} @("--data-dir", (Join-Path $Work "dist-smoke-native"))
}
Invoke-Check "EXE-07" "Executável" "Banco corrompido: código 2, arquivo preservado" {
    $d = Join-Path $Work "corrupt"
    New-Item -ItemType Directory -Force -Path "$d\machine\database" | Out-Null
    $db = "$d\machine\database\vyonix.db"
    [IO.File]::WriteAllBytes($db, [Text.Encoding]::ASCII.GetBytes(("lixo" * 1000)))
    $rep = Join-Path $OutDir "check-corrupt.json"
    $code = Run-Exe $DistExe @("--check", "--data-dir", $d, "--report", $rep)
    $r = Read-Report $rep
    if ($code -ne 2 -or $r.ok) { throw "código $code" }
    if ((Get-Item $db).Length -ne 4000) { throw "arquivo alterado" }
    "código 2; mensagem: $($r.error.Substring(0, [Math]::Min(80, $r.error.Length)))..."
}

# ---------------------------------------------------------------- B. instalador
Invoke-Check "INS-01" "Instalador" "Instalação silenciosa" {
    if (Test-Path $UninstKey) { throw "produto já instalado antes do teste" }
    Install-Silent (Join-Path $OutDir "setup-1.log")
    if (-not (Test-Path $InstalledExe)) { throw "Vyonix.exe ausente em $InstallDir" }
    "instalado em $InstallDir"
}
Invoke-Check "INS-02" "Instalador" "Registro em Programas Instalados" {
    $k = Get-ItemProperty $UninstKey
    if ($k.DisplayVersion -ne $Version) { throw "DisplayVersion='$($k.DisplayVersion)'" }
    "DisplayName='$($k.DisplayName)'; DisplayVersion=$($k.DisplayVersion); Publisher=$($k.Publisher)"
}
Invoke-Check "INS-03" "Instalador" "Atalhos (menu Iniciar e área de trabalho)" {
    if (-not (Test-Path $StartMenuLnk)) { throw "atalho do menu Iniciar ausente" }
    $desk = Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "VYONIX DICOM Print.lnk"
    if (-not (Test-Path $desk)) { throw "atalho da área de trabalho ausente" }
    $target = (New-Object -ComObject WScript.Shell).CreateShortcut($StartMenuLnk).TargetPath
    if ($target -ne $InstalledExe) { throw "atalho aponta para '$target'" }
    "menu Iniciar -> $target; área de trabalho criada"
}
Invoke-Check "INS-03B" "Instalador" "Regra do Firewall do Windows para o VYONIX" {
    $r = Test-FirewallRule
    if (-not $r.exists) { throw "regra não criada" }
    if ($r.text -notmatch [regex]::Escape($InstalledExe)) { throw "regra não aponta para o programa instalado" }
    "regra de entrada criada para Vyonix.exe (redes privadas e de domínio)"
}
Invoke-Check "INS-04" "Instalador" "Pasta de dados com permissão de gravação para Usuários" {
    if (-not (Test-Path $DataDir)) { throw "$DataDir ausente" }
    $sid = New-Object Security.Principal.SecurityIdentifier("S-1-5-32-545")
    $acl = (Get-Acl $DataDir).Access | Where-Object {
        try { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]) -eq $sid } catch { $false } }
    if (-not ($acl | Where-Object { $_.FileSystemRights -match 'Modify|FullControl' })) { throw "Usuários sem Modify" }
    "BUILTIN\Usuários: $(($acl.FileSystemRights | Select-Object -Unique) -join ', ')"
}
$script:installationId = $null
Invoke-Check "INS-05" "Instalador" "Programa instalado sem Python no PATH (--check em ProgramData)" {
    $rep = Join-Path $OutDir "check-installed.json"
    $code = Run-Exe $InstalledExe @("--check", "--report", $rep) $clean
    $r = Read-Report $rep
    if ($code -ne 0 -or -not $r.ok) { throw "código $code" }
    if (-not $r.database.StartsWith($env:ProgramData)) { throw "banco fora de ProgramData: $($r.database)" }
    if ($r.database.StartsWith($InstallDir)) { throw "banco na pasta do programa" }
    $script:installationId = $r.installation_id
    "banco em $($r.database); ID $($r.installation_id)"
}
$script:lic = @{}
Invoke-Check "LIC-01" "Licenciamento" "Instalação nova: Installation ID novo, Hardware ID, funções suspensas sem licença" {
    $inst = Read-Report (Join-Path $LicensingDir "instalador.json")
    if ($inst.mode -ne "fresh" -or -not $inst.ok) { throw "instalador.json: modo $($inst.mode)" }
    $r = Lic "inicial" @("--license", "status")
    if (-not $r.status.enforced) { throw "política comercial não ativa na versão $Version" }
    if ($r.status.state -ne "not_activated" -or $r.status.active) { throw "estado $($r.status.state)" }
    if ($r.installation_id -ne $inst.installation_id -or $r.installation_id -ne $script:installationId) { throw "IDs divergentes" }
    if ($r.hardware_id -notmatch '^VYXH-[0-9A-Z]{5}(-[0-9A-Z]{5}){3}$') { throw "Hardware ID '$($r.hardware_id)'" }
    $comps = ($r.components.PSObject.Properties | Where-Object { $_.Value } | ForEach-Object { $_.Name }) -join ", "
    if (@($r.components.PSObject.Properties | Where-Object { $_.Value -and $_.Name -ne 'mac' }).Count -lt 2) { throw "menos de 2 componentes fortes: $comps" }
    $script:lic.hw = $r.hardware_id; $script:lic.inst = $r.installation_id
    $tpm = if ($r.tpm.available) { "TPM: chave $($r.tpm.alg) disponível" } else { "TPM: $($r.tpm.reason)" }
    "$($r.installation_id); $($r.hardware_id); componentes: $comps; $tpm; estado $($r.status.state)"
}
Invoke-Check "LIC-02" "Licenciamento" "TPM 2.0: chave não exportável e prova de posse (quando disponível)" {
    $tpm = Get-Tpm -ErrorAction SilentlyContinue
    $r = Lic "tpm" @("--license", "status")
    if ($tpm -and $tpm.TpmPresent -and $tpm.TpmReady) {
        if (-not $r.tpm.available) { throw "TPM presente e pronto, mas a chave do VYONIX não está disponível: $($r.tpm.reason) $($r.tpm.detail)" }
        if (-not $r.components.tpm) { throw "chave do TPM fora do Hardware ID" }
        "TPM presente; chave $($r.tpm.alg) no Microsoft Platform Crypto Provider; componente no Hardware ID"
    } else {
        $why = if ($tpm) { "TpmPresent=$($tpm.TpmPresent) TpmReady=$($tpm.TpmReady)" } else { "Get-Tpm indisponível" }
        if ($r.tpm.available) { throw "chave de TPM relatada sem TPM" }
        "NÃO VERIFICÁVEL nesta máquina (sem TPM utilizável: $why); camada informada como indisponível: $($r.tpm.reason)"
    }
}
Invoke-Check "LIC-03" "Licenciamento" "Solicitação de ativação exportada (VYXR2, sem identificadores legíveis)" {
    $req = Join-Path $Work "solicitacao.vyreq"
    $r = Lic "solicitacao" @("--license", "request", "--file", $req)
    if (-not $r.ok -or -not (Test-Path $req)) { throw "solicitação não gerada" }
    $doc = Get-Content $req -Raw | ConvertFrom-Json
    if (-not $doc.code.StartsWith("VYXR2-")) { throw "código inválido" }
    $serial = (Get-CimInstance Win32_BaseBoard).SerialNumber
    $guid = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Cryptography").MachineGuid
    $raw = Get-Content $req -Raw
    foreach ($v in @($serial, $guid)) { if ($v -and $v.Length -gt 4 -and $raw.Contains($v)) { throw "identificador original exposto" } }
    $script:lic.req = $req
    "arquivo $([IO.Path]::GetFileName($req)); Hardware ID $($doc.summary.hardware_id)"
}
Invoke-Check "LIC-04" "Licenciamento" "DEMO de 5 dias (120 h) iniciada; funções liberadas; segunda DEMO recusada" {
    $r = Lic "demo" @("--license", "demo")
    if (-not $r.ok -or $r.status.state -ne "demo") { throw "estado $($r.status.state): $($r.error)" }
    $h = [math]::Round($r.status.remaining_s / 3600, 2)
    if ($h -lt 119.9 -or $h -gt 120.01) { throw "restam $h h" }
    $r2 = Lic "demo-2" @("--license", "demo")
    if ($r2.ok) { throw "segunda demonstração aceita" }
    "restam $h h; segunda tentativa: $($r2.error)"
}
Invoke-Check "SRV-01" "Serviço" "Serviço Windows instalado, automático e em execução" {
    Wait-Until { (Get-Service VyonixDicomPrint -ErrorAction SilentlyContinue).Status -eq "Running" } 90
    $svc = Get-CimInstance Win32_Service -Filter "Name='VyonixDicomPrint'"
    if (-not $svc) { throw "serviço não registrado" }
    if ($svc.State -ne "Running") { throw "estado $($svc.State)" }
    if ($svc.StartMode -ne "Auto") { throw "início $($svc.StartMode)" }
    if ($svc.PathName -notmatch [regex]::Escape("$InstallDir\VyonixService.exe")) { throw "caminho $($svc.PathName)" }
    if (-not $svc.PathName.StartsWith('"')) { throw "caminho do serviço sem aspas: $($svc.PathName)" }
    "conta $($svc.StartName); início $($svc.StartMode); $($svc.PathName)"
}
Invoke-Check "SRV-02" "Serviço" "Serviço responde ao canal de controle e aos C-ECHO (Storage e Print SCP)" {
    $rep = Join-Path $OutDir "service-check.json"
    $code = 1
    for ($i = 0; $i -lt 20 -and $code -ne 0; $i++) {
        $code = Run-Exe $InstalledExe @("--service-check", "--report", $rep) $clean
        if ($code -ne 0) { Start-Sleep 3 }
    }
    $r = Read-Report $rep
    if ($code -ne 0 -or -not $r.ok) { throw "código $code; $($r.error)" }
    $svcs = ($r.status.services | ForEach-Object { "$($_.name)=$($_.state)" }) -join ", "
    "serviço $($r.status.version); $svcs; C-ECHO storage $($r.echo.storage_bound.ms) ms, print $($r.echo.print_bound.ms) ms"
}
Invoke-Check "RCP-01" "Reception" "VYONIX Reception pelo serviço: HTTPS na rede local, API exige login" {
    $ok = $false; $last = ""
    for ($i = 0; $i -lt 20 -and -not $ok; $i++) {
        try {
            $r = Invoke-WebRequest "https://127.0.0.1:8443/" -SkipCertificateCheck -UseBasicParsing -TimeoutSec 10
            $ok = $r.StatusCode -eq 200 -and $r.Content -match "VYONIX Reception"
        } catch { $last = $_.Exception.Message; Start-Sleep 3 }
    }
    if (-not $ok) { throw "painel não respondeu: $last" }
    $code = 0
    try { Invoke-WebRequest "https://127.0.0.1:8443/api/exams" -SkipCertificateCheck -UseBasicParsing -TimeoutSec 10 | Out-Null; $code = 200 }
    catch { $code = [int]$_.Exception.Response.StatusCode }
    if ($code -ne 401) { throw "API sem login respondeu $code" }
    $cert = Join-Path $DataDir "reception\tls\cert.pem"
    if (-not (Test-Path $cert)) { throw "certificado não gerado" }
    "https://127.0.0.1:8443/ (TLS); API sem sessão: 401; certificado em $cert"
}
Invoke-Check "SRV-03" "Serviço" "Registro de inicialização da bandeja" {
    $v = (Get-ItemProperty "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run")."VYONIX DICOM Print"
    if ($v -notmatch "--tray") { throw "valor '$v'" }
    $v
}
Invoke-Check "INS-06" "Interface" "Smoke test do programa instalado (Windows nativo, conectado ao serviço)" {
    Smoke $InstalledExe "installed-native" $clean @()
}
Invoke-Check "LM-01" "License Manager" "Portátil: duplo clique sem Python/VYONIX, emite licença para a solicitação real" {
    if (-not $LMExe) { throw "executável do License Manager não informado" }
    $dir = Join-Path $Work "lm-portatil"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Copy-Item $LMExe $dir
    $exe = Join-Path $dir "VYONIX_License_Manager.exe"
    $rep = Join-Path $OutDir "lm-portable-selftest.json"
    $code = Run-Exe $exe @("--self-test", "--request", $script:lic.req, "--report", $rep) $clean 300
    $r = Read-Report $rep
    $bad = @($r.checks | Where-Object { -not $_.ok } | ForEach-Object { "$($_.name): $($_.error)" })
    if ($code -ne 0 -or -not $r.ok -or -not $r.frozen) { throw "código $code; frozen=$($r.frozen); $($bad -join '; ')" }
    if (-not (Test-Path (Join-Path $dir "VYONIX_License_Manager_Dados"))) { throw "pasta de dados portátil não criada" }
    $script:lic.lmfile = $r.license_file
    $mode = ($r.checks | Where-Object { $_.name -like "modo*" }).detail
    "$(@($r.checks).Count) verificações; $mode; $([math]::Round((Get-Item $exe).Length / 1MB, 1)) MB"
}
Invoke-Check "LIC-05" "Licenciamento" "Licença assinada por chave não oficial é recusada pelo VYONIX instalado" {
    if (-not $script:lic.lmfile -or -not (Test-Path $script:lic.lmfile)) { throw "licença do autoteste ausente" }
    $r = Lic "chave-nao-oficial" @("--license", "install", "--file", $script:lic.lmfile)
    if ($r.ok -or $r.status.state -ne "demo") { throw "licença aceita ou estado alterado ($($r.status.state))" }
    if ($r.error -notmatch "chave desconhecida") { throw "motivo inesperado: $($r.error)" }
    "recusada: $($r.error.Substring(0, [Math]::Min(110, $r.error.Length)))…"
}
Invoke-Check "LM-02" "License Manager" "Instalação opcional (VYONIX_License_Manager_Setup.exe), autoteste e desinstalação" {
    if (-not $LMInstaller) { throw "instalador do License Manager não informado" }
    $code = Run-Exe (Resolve-Path $LMInstaller).Path @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=$(Join-Path $OutDir 'setup-lm.log')") @{} 300
    if ($code -ne 0) { throw "instalador retornou $code" }
    $exe = Join-Path $LMInstallDir "VYONIX_License_Manager.exe"
    if (-not (Test-Path $exe) -or -not (Test-Path (Join-Path $LMInstallDir "installed.flag"))) { throw "arquivos ausentes" }
    $rep = Join-Path $OutDir "lm-installed-selftest.json"
    $code = Run-Exe $exe @("--self-test", "--report", $rep) $clean 300
    $r = Read-Report $rep
    $mode = ($r.checks | Where-Object { $_.name -like "modo*" }).detail
    if ($code -ne 0 -or -not $r.ok -or $mode -notmatch "modo installed") { throw "código $code; $mode" }
    if (Test-Path (Join-Path $InstallDir "VYONIX_License_Manager.exe")) { throw "License Manager dentro do produto comercial" }
    $un = (Get-ItemProperty $LMUninstKey).UninstallString.Trim('"')
    $code = Run-Exe $un @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") @{} 300
    Wait-Until { -not (Test-Path $LMUninstKey) } 120
    "instalado em $LMInstallDir; $mode; desinstalado"
}
Invoke-Check "LM-03" "License Manager" "Produto comercial instalado não contém o License Manager nem chaves privadas" {
    $bad = Get-ChildItem $InstallDir -Recurse | Where-Object {
        $_.Name -match 'license_manager|License_Manager|license_admin|license_server|License_Server' -or $_.Extension -in '.pem', '.key', '.vykey' }
    if ($bad) { throw "itens proibidos: $($bad.FullName -join ', ')" }
    $hits = Get-ChildItem $InstallDir -Recurse -File | Where-Object { $_.Length -lt 20MB } | Select-String -Pattern '-----BEGIN [A-Z ]*PRIVATE KEY-----' -SimpleMatch:$false -List -ErrorAction SilentlyContinue
    $real = @($hits | Where-Object { (Get-Content $_.Path -Raw -ErrorAction SilentlyContinue) -match '-----BEGIN [A-Z ]*PRIVATE KEY-----\r?\n[A-Za-z0-9+/=]{40,}' })
    if ($real.Count -gt 0) { throw "bloco de chave privada em: $($real.Path -join ', ')" }
    "$(@(Get-ChildItem $InstallDir -Recurse -File).Count) arquivos verificados"
}
Invoke-Check "LS-01" "License Server" "Autoteste: HTTPS real, autorização assinada com número de uso único; repetição e certificado divergente recusados" {
    if (-not $LSExe) { throw "executável do License Server não informado" }
    $rep = Join-Path $OutDir "ls-selftest.json"
    $code = Run-Exe (Resolve-Path $LSExe).Path @("selftest", "--report", $rep) $clean 300
    $r = Read-Report $rep
    if ($code -ne 0 -or -not $r.ok -or -not $r.frozen) { throw "código $code; frozen=$($r.frozen); $($r.error)" }
    "$(@($r.steps).Count) etapas: $($r.steps -join '; ')"
}
Invoke-Check "LS-02" "License Server" "Chave cifrada, configuração, servidor HTTPS em execução, /v1/health e API administrativa autenticada" {
    if (-not $LSExe) { throw "executável do License Server não informado" }
    $exe = (Resolve-Path $LSExe).Path
    $dir = Join-Path $Work "license-server"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $pp = Join-Path $dir "frase.txt"; $pw = Join-Path $dir "senha.txt"; $key = Join-Path $dir "ci-teste.pem"
    Set-Content $pp "Frase-Chave-CI-123" -NoNewline -Encoding ascii
    Set-Content $pw "Admin-Servidor-CI-1" -NoNewline -Encoding ascii
    $code = Run-Exe $exe @("genkey", "--out", $key, "--key-id", "ci-teste", "--password-file", $pp) $clean 120
    if ($code -ne 0 -or -not (Test-Path $key)) { throw "genkey retornou $code" }
    if ((Get-Content $key -Raw) -notmatch "BEGIN ENCRYPTED PRIVATE KEY") { throw "chave gravada sem cifra" }
    $envs = $clean.Clone(); $envs["VYONIX_LS_KEY_PASSPHRASE"] = "Frase-Chave-CI-123"
    $data = Join-Path $dir "dados"
    $code = Run-Exe $exe @("init", "--data", $data, "--admin", "admin", "--hostname", "127.0.0.1", "--port", "18743",
                           "--key-file", $key, "--key-id", "ci-teste", "--password-file", $pw) $envs 120
    if ($code -ne 0) { throw "init retornou $code" }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe; $psi.Arguments = "serve --data `"$data`""; $psi.UseShellExecute = $false
    foreach ($k in $envs.Keys) { $psi.EnvironmentVariables[$k] = $envs[$k] }
    $proc = [System.Diagnostics.Process]::Start($psi)
    try {
        $health = $null
        for ($i = 0; $i -lt 30 -and -not $health; $i++) {
            try { $health = Invoke-RestMethod "https://127.0.0.1:18743/v1/health" -SkipCertificateCheck -TimeoutSec 5 }
            catch { Start-Sleep 1 }
        }
        if (-not $health -or -not $health.ok) { throw "servidor não respondeu" }
        $code = 0
        try { Invoke-WebRequest "https://127.0.0.1:18743/v1/admin/subscriptions" -SkipCertificateCheck -UseBasicParsing -TimeoutSec 10 | Out-Null; $code = 200 }
        catch { $code = [int]$_.Exception.Response.StatusCode }
        if ($code -ne 401) { throw "API administrativa sem token respondeu $code" }
        $login = Invoke-RestMethod "https://127.0.0.1:18743/v1/admin/login" -Method Post -SkipCertificateCheck -ContentType "application/json" `
            -Body (@{ username = "admin"; password = "Admin-Servidor-CI-1" } | ConvertTo-Json)
        $subs = Invoke-RestMethod "https://127.0.0.1:18743/v1/admin/subscriptions" -SkipCertificateCheck -Headers @{ Authorization = "Bearer $($login.token)" }
        $plain = $false
        try { Invoke-WebRequest "http://127.0.0.1:18743/v1/health" -UseBasicParsing -TimeoutSec 5 | Out-Null; $plain = $true } catch { }
        if ($plain) { throw "respondeu sem TLS" }
        "health $($health.app) $($health.version) (chave $($health.signing_key)); sem token: 401; login $($login.user.role); $(@($subs.items).Count) assinatura(s); HTTP sem TLS recusado"
    } finally {
        if (-not $proc.HasExited) { $proc.Kill() }
    }
}
Invoke-Check "INS-07" "Instalador" "Atualização sobre instalação existente preserva dados e artes BMP" {
    Add-Type -AssemblyName System.Drawing
    $hdr = Join-Path $DataDir "print_templates\header.bmp"
    $bmp = New-Object System.Drawing.Bitmap 3000, 206, ([System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.Clear([System.Drawing.Color]::White)
    $g.FillRectangle([System.Drawing.Brushes]::DarkBlue, 0, 0, 900, 206)
    $g.Dispose()
    $bmp.Save($hdr, [System.Drawing.Imaging.ImageFormat]::Bmp)
    $bmp.Dispose()
    $hashBefore = (Get-FileHash $hdr -Algorithm SHA256).Hash
    Install-Silent (Join-Path $OutDir "setup-2-upgrade.log")
    $rep = Join-Path $OutDir "check-after-upgrade.json"
    $code = Run-Exe $InstalledExe @("--check", "--report", $rep) $clean
    $r = Read-Report $rep
    if ($code -ne 0) { throw "código $code" }
    if ($r.installation_id -ne $script:installationId) { throw "ID mudou: $($r.installation_id)" }
    Wait-Until { (Get-Service VyonixDicomPrint -ErrorAction SilentlyContinue).Status -eq "Running" } 90
    if ((Get-Service VyonixDicomPrint).Status -ne "Running") { throw "serviço não voltou após a atualização" }
    if ((Get-FileHash $hdr -Algorithm SHA256).Hash -ne $hashBefore) { throw "header.bmp personalizado foi substituído" }
    "ID da instalação mantido ($($r.installation_id)); header.bmp personalizado preservado; serviço em execução após atualizar"
}
Invoke-Check "LIC-06" "Licenciamento" "Atualização oficial preserva Installation ID, ativação e DEMO" {
    $inst = Read-Report (Join-Path $LicensingDir "instalador.json")
    if ($inst.mode -ne "upgrade") { throw "instalador tratou como '$($inst.mode)'" }
    $r = Lic "apos-atualizacao" @("--license", "status")
    if ($r.installation_id -ne $script:lic.inst) { throw "Installation ID mudou" }
    if ($r.status.state -ne "demo") { throw "estado $($r.status.state)" }
    $script:lic.remaining = $r.status.remaining_s
    "modo upgrade ($($inst.result)); ID $($r.installation_id); $($r.status.message)"
}
Invoke-Check "INS-08" "Instalador" "Desinstalação silenciosa remove programa e preserva dados" {
    Uninstall-Silent
    $u = Read-Report (Join-Path $LicensingDir "desinstalador.json")
    if (-not $u.ok -or $u.retired -ne $script:lic.inst) { throw "ativação não encerrada: $($u | ConvertTo-Json -Compress)" }
    if (Test-Path $StartMenuLnk) { throw "atalho permaneceu" }
    if ((Test-FirewallRule).exists) { throw "regra de firewall permaneceu" }
    if (Get-Service VyonixDicomPrint -ErrorAction SilentlyContinue) { throw "serviço permaneceu registrado" }
    if (-not (Test-Path "$DataDir\database\vyonix.db")) { throw "banco removido" }
    "programa, atalhos e registro removidos; banco preservado"
}
Invoke-Check "INS-09" "Instalador" "Reinstalação reutiliza os dados preservados (cadastros e configurações)" {
    Install-Silent (Join-Path $OutDir "setup-3-reinstall.log")
    $rep = Join-Path $OutDir "check-after-reinstall.json"
    $code = Run-Exe $InstalledExe @("--check", "--report", $rep) $clean
    $r = Read-Report $rep
    if ($code -ne 0 -or $r.database -notlike "$env:ProgramData*") { throw "código $code" }
    "banco preservado reaberto ($($r.database))"
}
Invoke-Check "LIC-07" "Licenciamento" "Desinstalar e reinstalar: novo Installation ID, nova ativação exigida, DEMO não renovada" {
    $inst = Read-Report (Join-Path $LicensingDir "instalador.json")
    if ($inst.mode -ne "fresh") { throw "reinstalação tratada como '$($inst.mode)'" }
    $r = Lic "apos-reinstalar" @("--license", "status")
    if ($r.installation_id -eq $script:lic.inst) { throw "Installation ID reaproveitado" }
    if ($r.hardware_id -ne $script:lic.hw) { throw "Hardware ID mudou ($($r.hardware_id))" }
    $r2 = Lic "demo-apos-reinstalar" @("--license", "demo")
    if ($r2.ok) { throw "nova demonstração concedida após reinstalar" }
    if ($r.status.state -ne "demo" -or $r.status.remaining_s -gt $script:lic.remaining) { throw "contagem da DEMO reiniciada ($($r.status.remaining_s) s)" }
    "novo ID $($r.installation_id) (anterior $($script:lic.inst)); mesmo Hardware ID; DEMO continua a contagem anterior; nova DEMO recusada"
}
Invoke-Check "INS-10" "Instalador" "Desinstalação final" {
    Uninstall-Silent
    "removido"
}

# ---------------------------------------------------------------- saída
$payload = [ordered]@{
    version   = $Version
    machine   = [ordered]@{
        os        = (Get-CimInstance Win32_OperatingSystem).Caption
        build     = [Environment]::OSVersion.Version.ToString()
        arch      = $env:PROCESSOR_ARCHITECTURE
        is_admin  = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        runner    = if ($env:GITHUB_ACTIONS) { "GitHub Actions ($env:RUNNER_NAME, $env:ImageOS $env:ImageVersion)" } else { $env:COMPUTERNAME }
    }
    timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    results   = $results
}
$payload | ConvertTo-Json -Depth 6 | Out-File (Join-Path $OutDir "results.json") -Encoding utf8

$failed = @($results | Where-Object { -not $_.ok })
$nv = @($results | Where-Object { $_.status -eq "nao_verificavel" })
$passed = $results.Count - $failed.Count - $nv.Count
Write-Host "`n$passed aprovadas, $($nv.Count) não verificáveis neste ambiente, $($failed.Count) falhas (de $($results.Count))."
foreach ($n in $nv) { Write-Host "::warning title=$($n.id) não verificável::$($n.detail)" }
if ($failed.Count -gt 0) {
    foreach ($f in $failed) { Write-Host "::error title=$($f.id) $($f.name)::$($f.detail)" }
    exit 1
}
exit 0
