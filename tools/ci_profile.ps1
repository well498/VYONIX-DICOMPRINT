<#
  Medição de tamanho, tempo de inicialização, memória e CPU do Vyonix.exe.

    .\tools\ci_profile.ps1 -Label padrao -DistDir dist\Vyonix -Installer dist\installer\X.exe -Out dist\perf\padrao.json

  Mede (valores reais, processo real, plataforma Qt nativa do Windows):
    - tamanho da pasta onedir, por categoria, e os 25 maiores arquivos;
    - tamanho do instalador;
    - tempo de --check (5 execuções);
    - tempo até a janela principal aparecer (todos os núcleos e 1 núcleo);
    - memória (working set e bytes privados) com a interface aberta e ociosa por 30 s;
    - pico de memória durante o --smoke-test;
    - uso médio de CPU com a interface ociosa.
#>
param(
    [Parameter(Mandatory = $true)] [string] $Label,
    [Parameter(Mandatory = $true)] [string] $DistDir,
    [Parameter(Mandatory = $true)] [string] $Installer,
    [Parameter(Mandatory = $true)] [string] $Out
)
$ErrorActionPreference = "Stop"
$DistDir = (Resolve-Path $DistDir).Path
$Exe = Join-Path $DistDir "Vyonix.exe"
$Work = Join-Path ([IO.Path]::GetTempPath()) "vyonix-perf-$Label"
Remove-Item $Work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Work | Out-Null
$cores = [Environment]::ProcessorCount

function MB([double]$b) { [math]::Round($b / 1MB, 2) }

function Start-Vyonix([string[]]$Arguments, [int]$Affinity = 0) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = ($Arguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '
    $psi.UseShellExecute = $false
    $p = [System.Diagnostics.Process]::Start($psi)
    if ($Affinity -gt 0) { try { $p.ProcessorAffinity = [IntPtr]$Affinity } catch {} }
    return $p
}

# ------------------------------------------------------------------ tamanho
$files = Get-ChildItem $DistDir -Recurse -File
function Category($f) {
    $r = $f.FullName.Substring($DistDir.Length + 1).Replace('\', '/')
    switch -Regex ($r) {
        'opengl32sw' { 'Qt: OpenGL por software'; break }
        'PySide6/plugins/' { 'Qt: plugins'; break }
        'PySide6/translations/' { 'Qt: traduções'; break }
        'PySide6/Qt6[^/]*\.dll$' { 'Qt: bibliotecas'; break }
        'PySide6/|shiboken6/' { 'PySide6/shiboken (ligações Python)'; break }
        'python3\d*\.dll|base_library|\.pyd$|python3\.dll' { 'Python: runtime e extensões'; break }
        '(?i)vcruntime|msvcp|ucrtbase|api-ms-win|concrt' { 'Runtime C++ (MSVC/UCRT)'; break }
        '(?i)libcrypto|libssl|libffi|sqlite3|_sqlite' { 'Python: OpenSSL/SQLite/FFI'; break }
        '^assets/' { 'VYONIX: recursos'; break }
        '^Vyonix\.exe$' { 'VYONIX: executável (inclui código Python)'; break }
        default { 'Outros' }
    }
}
$byCat = $files | Group-Object { Category $_ } | ForEach-Object {
    [ordered]@{ category = $_.Name; files = $_.Count; mb = MB (($_.Group | Measure-Object Length -Sum).Sum) }
} | Sort-Object { -$_.mb }
$top = $files | Sort-Object Length -Descending | Select-Object -First 25 | ForEach-Object {
    [ordered]@{ file = $_.FullName.Substring($DistDir.Length + 1); mb = MB $_.Length }
}
$totalBytes = ($files | Measure-Object Length -Sum).Sum

# ------------------------------------------------------------------ --check
$checkMs = @()
for ($i = 0; $i -lt 5; $i++) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Vyonix @("--check", "--data-dir", "$Work\check", "--report", "$Work\check.json")
    $p.WaitForExit()
    $checkMs += [int]$sw.ElapsedMilliseconds
}

# ------------------------------------------------------------------ janela principal
function Measure-Window([int]$Affinity, [string]$Dir, [int]$IdleSec) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Vyonix @("--data-dir", $Dir) $Affinity
    $shownMs = $null
    while ($sw.Elapsed.TotalSeconds -lt 60) {
        Start-Sleep -Milliseconds 50
        $p.Refresh()
        if ($p.HasExited) { throw "processo encerrou ao iniciar (código $($p.ExitCode))" }
        if ($p.MainWindowHandle -ne [IntPtr]::Zero) { $shownMs = [int]$sw.ElapsedMilliseconds; break }
    }
    if ($null -eq $shownMs) { $p.Kill(); throw "janela principal não apareceu em 60 s" }
    $res = [ordered]@{ window_ms = $shownMs }
    if ($IdleSec -gt 0) {
        Start-Sleep -Seconds 5      # estabilização (primeira atualização do Dashboard)
        $p.Refresh()
        $cpu0 = $p.TotalProcessorTime.TotalMilliseconds
        $t0 = [Diagnostics.Stopwatch]::StartNew()
        $ws = @(); $priv = @()
        while ($t0.Elapsed.TotalSeconds -lt $IdleSec) {
            Start-Sleep -Milliseconds 500
            $p.Refresh(); $ws += $p.WorkingSet64; $priv += $p.PrivateMemorySize64
        }
        $p.Refresh()
        $cpuMs = $p.TotalProcessorTime.TotalMilliseconds - $cpu0
        $res.idle_seconds = $IdleSec
        $res.working_set_mb_avg = MB (($ws | Measure-Object -Average).Average)
        $res.working_set_mb_max = MB (($ws | Measure-Object -Maximum).Maximum)
        $res.private_mb_avg = MB (($priv | Measure-Object -Average).Average)
        $res.peak_working_set_mb = MB $p.PeakWorkingSet64
        $res.threads = $p.Threads.Count
        $res.cpu_percent_of_one_core = [math]::Round(100 * $cpuMs / ($t0.Elapsed.TotalMilliseconds), 2)
    }
    $sw2 = [Diagnostics.Stopwatch]::StartNew()
    [void]$p.CloseMainWindow()
    if (-not $p.WaitForExit(15000)) { $p.Kill(); $res.close = "forçado"; } else { $res.close = "normal"; $res.close_ms = [int]$sw2.ElapsedMilliseconds; $res.exit_code = $p.ExitCode }
    return $res
}

$first = Measure-Window 0 "$Work\ui-first" 30
$warmAll = @(); $warmOne = @()
for ($i = 0; $i -lt 3; $i++) { $warmAll += (Measure-Window 0 "$Work\ui-first" 0).window_ms }
for ($i = 0; $i -lt 3; $i++) { $warmOne += (Measure-Window 1 "$Work\ui-first" 0).window_ms }

# ------------------------------------------------------------------ pico no smoke test
$p = Start-Vyonix @("--smoke-test", "--data-dir", "$Work\smoke", "--report", "$Work\smoke.json")
$peak = 0
while (-not $p.HasExited) {
    try { $p.Refresh(); if ($p.WorkingSet64 -gt $peak) { $peak = $p.WorkingSet64 } } catch {}
    Start-Sleep -Milliseconds 50
}
$smoke = Get-Content "$Work\smoke.json" -Raw -Encoding UTF8 | ConvertFrom-Json

function Median($xs) { $s = $xs | Sort-Object; $s[[int][math]::Floor($s.Count / 2)] }

$result = [ordered]@{
    label = $Label
    cores = $cores
    cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
    ram_gb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
    disk = [ordered]@{
        onedir_mb = MB $totalBytes; onedir_files = $files.Count
        installer_mb = MB (Get-Item $Installer).Length
        by_category = @($byCat); top_files = @($top)
    }
    check_ms = $checkMs; check_ms_median = Median $checkMs
    ui_first_start = $first
    ui_window_ms_all_cores = $warmAll; ui_window_ms_all_cores_median = Median $warmAll
    ui_window_ms_one_core = $warmOne; ui_window_ms_one_core_median = Median $warmOne
    smoke_ok = [bool]$smoke.ok; smoke_peak_working_set_mb = MB $peak
}
New-Item -ItemType Directory -Force (Split-Path $Out) | Out-Null
$result | ConvertTo-Json -Depth 6 | Out-File $Out -Encoding utf8
Write-Host ($result | ConvertTo-Json -Depth 6)
if (-not $smoke.ok) { exit 1 }
