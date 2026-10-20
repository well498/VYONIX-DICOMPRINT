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
    [string] $OutDir = "dist\validation"
)

$ErrorActionPreference = "Stop"
$AppId = "{8C4E2D6A-3F1B-4B7E-9A2C-5D1E7F9B0A11}_is1"
$UninstKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$AppId"
$InstallDir = Join-Path $env:ProgramFiles "VYONIX\DICOM Print"
$InstalledExe = Join-Path $InstallDir "Vyonix.exe"
$DataDir = Join-Path $env:ProgramData "VYONIX\DICOM Print"
$StartMenuLnk = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\VYONIX DICOM Print.lnk"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path
$Installer = (Resolve-Path $Installer).Path
$DistExe = (Resolve-Path $DistExe).Path
$Work = Join-Path $OutDir "work"
New-Item -ItemType Directory -Force -Path $Work | Out-Null

$results = New-Object System.Collections.Generic.List[object]

function Add-Result([string]$Id, [string]$Area, [string]$Name, [bool]$Ok, [string]$Detail) {
    $results.Add([ordered]@{ id = $Id; area = $Area; name = $Name; ok = $Ok; detail = $Detail })
    $mark = if ($Ok) { "PASS" } else { "FAIL" }
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

function Wait-Until([scriptblock]$Cond, [int]$TimeoutSec = 180) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while (-not (& $Cond)) {
        if ($sw.Elapsed.TotalSeconds -gt $TimeoutSec) { throw "tempo esgotado aguardando condição" }
        Start-Sleep -Milliseconds 500
    }
}

function Install-Silent([string]$Log) {
    $code = Run-Exe $Installer @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/TASKS=desktopicon", "/LOG=$Log") @{} 600
    if ($code -ne 0) { throw "instalador retornou $code" }
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
        $_.FullName -match 'license_admin|\\tests\\' -or $_.Extension -in '.pem', '.key' }
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
    if ($code -ne 0 -or -not $r.ok -or $r.schema_version -ne 1) { throw "código $code" }
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
Invoke-Check "INS-06" "Interface" "Smoke test do programa instalado (Windows nativo)" {
    Smoke $InstalledExe "installed-native" $clean @()
}
Invoke-Check "INS-07" "Instalador" "Atualização sobre instalação existente preserva dados" {
    Install-Silent (Join-Path $OutDir "setup-2-upgrade.log")
    $rep = Join-Path $OutDir "check-after-upgrade.json"
    $code = Run-Exe $InstalledExe @("--check", "--report", $rep) $clean
    $r = Read-Report $rep
    if ($code -ne 0) { throw "código $code" }
    if ($r.installation_id -ne $script:installationId) { throw "ID mudou: $($r.installation_id)" }
    "ID da instalação mantido ($($r.installation_id))"
}
Invoke-Check "INS-08" "Instalador" "Desinstalação silenciosa remove programa e preserva dados" {
    Uninstall-Silent
    if (Test-Path $StartMenuLnk) { throw "atalho permaneceu" }
    if (-not (Test-Path "$DataDir\database\vyonix.db")) { throw "banco removido" }
    "programa, atalhos e registro removidos; banco preservado"
}
Invoke-Check "INS-09" "Instalador" "Reinstalação reutiliza os dados preservados" {
    Install-Silent (Join-Path $OutDir "setup-3-reinstall.log")
    $rep = Join-Path $OutDir "check-after-reinstall.json"
    $code = Run-Exe $InstalledExe @("--check", "--report", $rep) $clean
    $r = Read-Report $rep
    if ($code -ne 0 -or $r.installation_id -ne $script:installationId) { throw "código $code; ID $($r.installation_id)" }
    "mesmo ID após reinstalar"
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
Write-Host "`n$($results.Count - $failed.Count)/$($results.Count) verificações aprovadas."
if ($failed.Count -gt 0) {
    foreach ($f in $failed) { Write-Host "::error title=$($f.id) $($f.name)::$($f.detail)" }
    exit 1
}
exit 0
