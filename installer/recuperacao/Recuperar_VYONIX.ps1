# VYONIX - Recuperacao de instalacao com defeito (P0).
#
# PADRAO: SOMENTE DIAGNOSTICO. Nao para servicos, nao encerra processos, nao altera arquivos, pastas, registro do
# Windows nem o banco de dados. Unica gravacao: o relatorio (HTML) na Area de Trabalho (ou em -Saida).
# O diagnostico identifica o que PERTENCE ao VYONIX Platform (servicos cujo programa esta em
# Program Files\VYONIX\Platform, processos que executam arquivos dessa pasta, o banco PostgreSQL do VYONIX) e mostra
# o PLANO do que a recuperacao faria, sem fazer nada.
#
# Com -Aplicar: mostra o plano e exige digitar RECUPERAR. Entao, nesta ordem:
#   1. registra o ESTADO ANTERIOR (servicos, registro de desinstalacao, regras de firewall, lista de arquivos,
#      configuracoes) em ProgramData\VYONIX\Backups\recuperacao-<data>\estado-anterior;
#   2. para os servicos que gravam no banco (Core, Worker, motor PACS) e, com o banco ainda ligado, faz um BACKUP
#      NOVO (pg_dump; a leitura completa confere as somas de verificacao das paginas) e PROVA que ele restaura
#      (restaura num banco temporario de verificacao e compara, tabela a tabela, a contagem E o resumo MD5 do
#      conteudo, as sequencias e a estrutura; confere os indices da copia com amcheck);
#      sem banco acessivel: copia a frio do cluster (servicos parados) conferida arquivo a arquivo (SHA-256);
#   3. se o backup NAO for confirmado: religa os servicos e PARA (nada removido);
#   4. remove somente os servicos que pertencem ao VYONIX Platform (nunca o VyonixDicomPrint nem servicos de outros
#      programas), encerra somente processos da pasta do programa, RENOMEIA a pasta do programa (nao apaga) e remove
#      o registro de desinstalacao somente se o desinstalador nao existir mais (copia .reg salva antes).
# NUNCA altera os dados em ProgramData\VYONIX (banco, estudos DICOM, configuracoes, usuarios, auditoria, backups).
# Reversao: Reverter_VYONIX.cmd (usa o estado anterior registrado). Pode ser executada de novo com seguranca.
param([switch]$Aplicar, [string]$Saida = "", [switch]$SemAbrir, [switch]$SemConfirmar, [string]$Confirmacao = "")
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$agora = Get-Date
if (-not $Saida) { $Saida = [Environment]::GetFolderPath("Desktop") }
if (-not (Test-Path $Saida)) { $Saida = $env:TEMP }
$tag = $agora.ToString("yyyy-MM-dd_HH-mm-ss")
$arq = Join-Path $Saida ("VYONIX_Recuperacao_" + $tag + ".html")
$logf = Join-Path $Saida ("VYONIX_Recuperacao_" + $tag + ".log")
$app = Join-Path $env:ProgramFiles "VYONIX\Platform"
$appPrefix = [IO.Path]::GetFullPath($app).TrimEnd('\') + '\'
$dados = Join-Path $env:ProgramData "VYONIX"
$pgbin = Join-Path $app "pgsql\bin"
$servicos = @("VyonixPacsEngine", "VyonixCore", "VyonixWorker", "VyonixPostgreSQL")   # ordem de parada
$gravam = @("VyonixPacsEngine", "VyonixCore", "VyonixWorker")                          # escrevem no banco
$appId = "{EE8E242D-1625-4E1B-8317-5BFD8610DD26}_is1"
$rec = Join-Path $dados ("Backups\recuperacao-" + $tag)
$res = New-Object System.Collections.ArrayList
$acoes = New-Object System.Collections.ArrayList
$script:regKey = $null; $script:backupsOk = 0; $script:pg = $null; $script:plano = $null
function Log($m) { $l = (Get-Date).ToString("HH:mm:ss") + "  " + $m; Add-Content -Path $logf -Value $l -Encoding utf8; Write-Host $l }
function Acao($m) { [void]$acoes.Add($m); Log $m }
function Add-Res($id, $titulo, $estado, $detalhe, $acao) {
  [void]$res.Add([pscustomobject]@{ id=$id; titulo=$titulo; estado=$estado; detalhe=$detalhe; acao=$acao }) }
function Html($s) { [System.Net.WebUtility]::HtmlEncode([string]$s) }
function Admin { ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
function Sob-App($p) { $p -and ([string]$p).StartsWith($appPrefix, [StringComparison]::OrdinalIgnoreCase) }
function Exe-De($pathName) {
  if ($pathName -match '^"([^"]+)"') { return $matches[1] }
  if ($pathName -match '^(.+?\.exe)') { return $matches[1] }
  return $null }

# ------------------------------------------------------------------ inventario (somente leitura)
function Servico-Info($s) {
  $w = Get-CimInstance Win32_Service -Filter "Name='$s'" -ErrorAction SilentlyContinue
  if (-not $w) { return $null }
  $k = "HKLM:\SYSTEM\CurrentControlSet\Services\$s"
  $p = Get-ItemProperty $k -ErrorAction SilentlyContinue
  $bin = Exe-De $w.PathName
  [pscustomobject]@{ Name=$s; DisplayName=$w.DisplayName; PathName=$w.PathName; Exe=$bin; ExeExiste=$(if ($bin) { Test-Path $bin } else { $false });
    Pertence=(Sob-App $bin); State=$w.State; StartMode=$w.StartMode; StartName=$w.StartName; ProcessId=$w.ProcessId;
    Delayed=$p.DelayedAutostart; DependOn=@($p.DependOnService); Description=$w.Description; DeleteFlag=($p.DeleteFlag -eq 1) } }
function Processos-App { @(Get-CimInstance Win32_Process | Where-Object { Sob-App $_.ExecutablePath }) }
function Ler-Segredo($nome) {
  # Senha local do PostgreSQL do VYONIX (DPAPI da maquina). Fica so na memoria deste processo; nunca e gravada.
  try {
    Add-Type -AssemblyName System.Security
    $j = Get-Content (Join-Path $dados "Deploy\secrets.json") -Raw -ErrorAction Stop | ConvertFrom-Json
    $v = [string]$j.$nome; if (-not $v) { return $null }
    $partes = $v.Split(":", 2); $raw = [Convert]::FromBase64String($partes[1])
    if ($partes[0] -eq "dpapi") { $raw = [Security.Cryptography.ProtectedData]::Unprotect($raw, $null, [Security.Cryptography.DataProtectionScope]::LocalMachine) }
    return [Text.Encoding]::UTF8.GetString($raw)
  } catch { return $null } }
function Banco-Info {
  $svc = Servico-Info "VyonixPostgreSQL"
  $data = Join-Path $dados "PostgreSQL\17\data"
  if ($svc -and $svc.PathName -match '-D\s+"([^"]+)"') { $data = $matches[1] }
  $porta = 5544
  foreach ($f in @("postgresql.auto.conf", "postgresql.conf")) {
    $c = Join-Path $data $f
    if (Test-Path $c) { $m = Select-String -Path $c -Pattern '^\s*port\s*=\s*(\d+)' | Select-Object -Last 1; if ($m) { $porta = [int]$m.Matches[0].Groups[1].Value; break } } }
  $tam = 0; if (Test-Path $data) { $tam = (Get-ChildItem $data -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum }
  $ctl = $null; $estado = $null; $checks = $null
  $pgc = Join-Path $pgbin "pg_controldata.exe"
  if ((Test-Path $pgc) -and (Test-Path (Join-Path $data "global\pg_control"))) {
    $ctl = & $pgc -D $data 2>$null
    $estado = (($ctl | Select-String "Database cluster state") -replace '.*:\s*', '')
    $checks = (($ctl | Select-String "Data page checksum version") -replace '.*:\s*', '') }
  $senha = Ler-Segredo "pg_superuser"
  $con = $null; $versao = $null
  $psql = Join-Path $pgbin "psql.exe"
  if ($senha -and (Test-Path $psql) -and $svc -and $svc.State -eq "Running") {
    $env:PGPASSWORD = $senha
    $o = & $psql -h 127.0.0.1 -p $porta -U vyonix_admin -d postgres -At -c "select current_setting('server_version') || '|' || (select count(*) from pg_database where datname = 'vyonix')" 2>&1
    $env:PGPASSWORD = $null
    if ($LASTEXITCODE -eq 0) { $con = $true; $versao = [string]$o } else { $con = $false; $versao = ([string]($o -join " ")).Substring(0, [Math]::Min(200, ([string]($o -join " ")).Length)) } }
  [pscustomobject]@{ Data=$data; Existe=(Test-Path (Join-Path $data "PG_VERSION")); Porta=$porta; Bytes=$tam; Estado=$estado; Checksums=$checks;
    Conecta=$con; Versao=$versao; Senha=[bool]$senha; Binarios=(Test-Path (Join-Path $pgbin "pg_dump.exe")); Servico=$svc } }

function Verificar-Backups {
  # Copias de seguranca: cada pasta com backup.json (gravado pelo DEPLOY) tem o resumo SHA-256 do arquivo .dump.
  $raiz = Join-Path $dados "Backups"
  $lista = @(Get-ChildItem $raiz -Directory -ErrorAction SilentlyContinue | Sort-Object LastWriteTime)
  $ok = 0; $ruins = @(); $ultima = $null; $ultimaDir = $null
  foreach ($b in $lista) {
    $m = Join-Path $b.FullName "backup.json"
    if (-not (Test-Path $m)) { continue }
    try { $j = Get-Content $m -Raw | ConvertFrom-Json } catch { $ruins += $b.Name; continue }
    $d = Join-Path $b.FullName $j.dump
    if ((Test-Path $d) -and ((Get-FileHash $d -Algorithm SHA256).Hash.ToLower() -eq ([string]$j.sha256).ToLower())) { $ok++; $ultima = $b.Name; $ultimaDir = $d }
    else { $ruins += $b.Name }
  }
  $leg = ""
  $pr = Join-Path $pgbin "pg_restore.exe"
  $script:ultimoBackup = $ultima; $script:ultimoLegivel = $null
  if ($ultimaDir -and (Test-Path $pr)) { & $pr --list $ultimaDir *> $null; $script:ultimoLegivel = ($LASTEXITCODE -eq 0); $leg = $(if ($script:ultimoLegivel) { "; a mais recente e legivel (pg_restore --list)" } else { "; a mais recente NAO e legivel pelo pg_restore" }) }
  $script:backupsOk = $ok
  if ($ok -gt 0) { Add-Res "R0" "Copias de seguranca do banco (verificadas)" "OK" ("$ok copia(s) integra(s) (SHA-256 confere) em $raiz; mais recente: $ultima$leg" + $(if ($ruins.Count) { "; com problema: " + ($ruins -join ", ") } else { "" })) "Ao aplicar, um backup NOVO e feito e testado antes de qualquer remocao." }
  else { Add-Res "R0" "Copias de seguranca do banco (verificadas)" "ATENCAO" $(if ($lista.Count) { "Nenhuma copia integra: " + ($ruins -join ", ") } else { "Nenhuma copia encontrada em $raiz." }) "Ao aplicar, um backup NOVO e feito e testado antes de qualquer remocao; sem backup confirmado nada e removido." }
}

function Diagnostico {
  $res.Clear()
  Verificar-Backups
  # R1 registro de desinstalacao (Inno Setup)
  $reg = $null; $script:regKey = $null
  foreach ($k in @("HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$appId", "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\$appId")) {
    if (Test-Path $k) { $reg = Get-ItemProperty $k; $script:regKey = $k } }
  $script:regOrfao = $false
  if (-not $reg) { Add-Res "R1" "Registro do VYONIX em Programas e Recursos" "AUSENTE" "Nao ha registro de instalacao do VYONIX." "" }
  else {
    $un = ($reg.UninstallString -replace '"', '').Split(" /")[0]
    $existe = Test-Path $un
    $script:regOrfao = -not $existe
    Add-Res "R1" "Registro do VYONIX em Programas e Recursos" $(if ($existe) { "OK" } else { "DEFEITO" }) ("Chave $script:regKey; versao " + $reg.DisplayVersion + "; pasta " + $reg.InstallLocation + "; desinstalador " + $un + $(if ($existe) { " (existe)" } else { " (NAO existe: registro orfao)" })) $(if (-not $existe) { "Ao aplicar: o registro orfao e removido (copia .reg salva antes)." } else { "" })
  }
  # R2 pasta do programa
  if (Test-Path $app) {
    $fs = @(Get-ChildItem $app -Recurse -File -ErrorAction SilentlyContinue)
    $exe = Test-Path (Join-Path $app "vyonix-deploy.exe")
    Add-Res "R2" "Pasta do programa (pertence ao VYONIX Platform)" $(if ($exe) { "OK" } else { "DEFEITO" }) ("$app - $($fs.Count) arquivo(s), " + [math]::Round((($fs | Measure-Object Length -Sum).Sum) / 1MB, 1) + " MB; vyonix-deploy.exe " + $(if ($exe) { "presente" } else { "AUSENTE (instalacao incompleta)" })) $(if (-not $exe) { "Ao aplicar: a pasta e renomeada (nao apagada) e o instalador grava uma nova." } else { "" })
  } else { Add-Res "R2" "Pasta do programa" "AUSENTE" "$app nao existe." "" }
  $antigas = @(Get-ChildItem (Split-Path $app) -Directory -Filter "Platform.anterior-*" -ErrorAction SilentlyContinue)
  if ($antigas.Count) { Add-Res "R2" "Pastas renomeadas por recuperacoes anteriores" "INFO" (($antigas | ForEach-Object { $_.FullName }) -join "; ") "Podem ser apagadas depois que a nova instalacao estiver validada (ou mantidas)." }
  # R3 servicos (pertence = programa do servico dentro da pasta do programa do VYONIX Platform)
  $script:svcInfo = @{}
  foreach ($s in $servicos) {
    $i = Servico-Info $s
    if (-not $i) { Add-Res "R3" "Servico $s" "AUSENTE" "Nao registrado." ""; continue }
    $script:svcInfo[$s] = $i
    $det = "$($i.State), inicio $($i.StartMode), conta $($i.StartName), programa $($i.Exe)" + $(if (-not $i.ExeExiste) { " (ARQUIVO AUSENTE)" } else { "" }) + $(if ($i.DeleteFlag) { "; MARCADO PARA EXCLUSAO (sai ao reiniciar o Windows)" } else { "" })
    if (-not $i.Pertence) { Add-Res "R3" "Servico $s" "NAO PERTENCE" ($det + "; o programa NAO esta na pasta do VYONIX Platform") "Nao sera alterado por esta ferramenta (pode ser de outro programa). Verifique com o suporte."; continue }
    $e = if ($i.DeleteFlag) { "REINICIAR" } elseif (-not $i.ExeExiste) { "DEFEITO" } else { "OK" }
    Add-Res "R3" "Servico $s (pertence ao VYONIX Platform)" $e $det $(if ($i.DeleteFlag) { "Reinicie o Windows antes de reinstalar." } elseif (-not $i.ExeExiste) { "Ao aplicar: o servico orfao e removido." } else { "" })
  }
  $dp = Get-CimInstance Win32_Service -Filter "Name='VyonixDicomPrint'" -ErrorAction SilentlyContinue
  if ($dp) { Add-Res "R3" "Servico VyonixDicomPrint (VYONIX DICOM Print)" "INFO" "$($dp.State) - NUNCA alterado por esta ferramenta." "" }
  # R4 processos da pasta do programa
  $procs = Processos-App
  $script:procs = $procs
  if ($procs.Count) { Add-Res "R4" "Processos que executam arquivos da pasta do programa" "ATENCAO" (($procs | ForEach-Object { "$($_.Name) (PID $($_.ProcessId)) $($_.ExecutablePath)" }) -join "; ") "Prendem arquivos e impedem desinstalar/atualizar. Ao aplicar, somente estes sao encerrados." }
  else { Add-Res "R4" "Processos que executam arquivos da pasta do programa" "OK" "Nenhum." "" }
  # R5 dados preservados
  $itens = @(
    @("Configuracao do sistema", (Join-Path $dados "Platform\config.json")),
    @("Segredos locais (cifrados)", (Join-Path $dados "Platform\secrets.json")),
    @("Banco PostgreSQL (cluster)", (Join-Path $dados "PostgreSQL\17\data\PG_VERSION")),
    @("Registro do DEPLOY", (Join-Path $dados "Deploy\deploy.db")))
  $txt = ($itens | ForEach-Object { $_[0] + ": " + $(if (Test-Path $_[1]) { "presente" } else { "ausente" }) }) -join "; "
  Add-Res "R5" "Dados do VYONIX em $dados - nunca alterados por esta ferramenta" "INFO" $txt "Ao reinstalar, o instalador reconhece estes dados e faz uma ATUALIZACAO (backup antes)."
  # R9 banco de dados (somente leitura)
  $b = Banco-Info; $script:pg = $b
  if (-not $b.Existe) { Add-Res "R9" "Banco de dados do VYONIX" "AUSENTE" "Cluster nao encontrado em $($b.Data)." "" }
  else {
    $d = "Cluster $($b.Data) (" + [math]::Round($b.Bytes / 1MB, 1) + " MB), porta $($b.Porta), servico VyonixPostgreSQL " + $(if ($b.Servico) { $b.Servico.State } else { "ausente" })
    if ($b.Estado) { $d += "; estado do cluster: $($b.Estado); somas de verificacao das paginas: " + $(if ($b.Checksums -and $b.Checksums -ne "0") { "ativas" } else { "desativadas" }) }
    if ($b.Conecta -eq $true) { $d += "; conexao OK (versao|banco vyonix: $($b.Versao))" } elseif ($b.Conecta -eq $false) { $d += "; conexao FALHOU: $($b.Versao)" } else { $d += "; conexao nao testada (servico parado, programas ou senha ausentes)" }
    $e = if ($b.Conecta -eq $false) { "ATENCAO" } else { "OK" }
    Add-Res "R9" "Banco de dados do VYONIX" $e $d $(if ($b.Conecta -eq $true) { "Ao aplicar: backup novo com teste de restauracao antes de remover algo." } else { "Ao aplicar: copia a frio do cluster (servicos parados), conferida arquivo a arquivo." }) }
  # R6 portas
  foreach ($porta in @(8444, 5544)) {
    $c = @(Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue)
    if ($c.Count) { $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($c[0].OwningProcess)" -ErrorAction SilentlyContinue
      Add-Res "R6" "Porta $porta" "INFO" ("Em uso por " + $(if ($p) { $p.Name + " (PID " + $p.ProcessId + ") " + $p.ExecutablePath + $(if (Sob-App $p.ExecutablePath) { " - VYONIX" } else { " - OUTRO PROGRAMA" }) } else { "PID " + $c[0].OwningProcess })) "" }
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

function Montar-Plano {
  $svc = @($servicos | Where-Object { $script:svcInfo.ContainsKey($_) -and $script:svcInfo[$_].Pertence })
  $alheios = @($servicos | Where-Object { $script:svcInfo.ContainsKey($_) -and -not $script:svcInfo[$_].Pertence })
  $b = $script:pg
  $metodo = if ($b.Conecta -eq $true -and $b.Binarios) { "backup novo do banco (pg_dump) com teste de restauracao num banco temporario" }
            elseif ($b.Existe) { "copia a frio do cluster (" + [math]::Round($b.Bytes / 1MB, 1) + " MB) com os servicos parados, conferida por SHA-256" } else { "nenhum (banco nao encontrado)" }
  $script:plano = [pscustomobject]@{
    Servicos = $svc; Alheios = $alheios; Processos = @($script:procs); Renomear = (Test-Path $app); Registro = $script:regOrfao
    Backup = $metodo; Estado = (Join-Path $rec "estado-anterior")
    Vazio = (-not $svc.Count -and -not $script:procs.Count -and -not (Test-Path $app) -and -not $script:regOrfao) }
}
function Plano-Linhas {
  $p = $script:plano; $l = @()
  if ($p.Vazio) { return @("Nada a fazer: nao ha servicos, processos, pasta do programa nem registro orfao do VYONIX Platform.") }
  $l += "1. Registrar o estado atual (para reversao) em: $($p.Estado)"
  $l += "2. Backup e verificacao antes de remover algo: $($p.Backup). Se nao for confirmado, NADA e removido."
  if ($p.Servicos.Count) { $l += "3. Parar e remover os servicos do VYONIX Platform: " + ($p.Servicos -join ", ") }
  if ($p.Alheios.Count) { $l += "   NAO serao tocados (programa fora da pasta do VYONIX): " + ($p.Alheios -join ", ") }
  $l += "   NUNCA tocados: VyonixDicomPrint e servicos de outros programas."
  if ($p.Processos.Count) { $l += "4. Encerrar somente estes processos (pasta do programa): " + (($p.Processos | ForEach-Object { "$($_.Name) PID $($_.ProcessId)" }) -join ", ") } else { $l += "4. Encerrar processos: nenhum (os dos servicos param com eles)." }
  if ($p.Renomear) { $l += "5. Renomear (nao apagar) $app para Platform.anterior-$tag" }
  if ($p.Registro) { $l += "6. Remover o registro orfao de Programas e Recursos (copia .reg salva antes)" }
  $l += "Dados preservados (nao alterados): $dados (banco, estudos DICOM, configuracoes, usuarios, auditoria, backups)."
  $l += "Impacto: o VYONIX Platform fica fora do ar ate a reinstalacao. O DICOM Print continua funcionando."
  $l += "Limitacoes: servico aberto por outro programa so sai ao reiniciar o Windows; arquivo preso por outro programa impede renomear a pasta (reinicie e execute de novo: e seguro repetir)."
  $l += "Reversao: Reverter_VYONIX.cmd (pasta renomeada volta, servicos recriados pelo reparo oficial)."
  return $l }

# ------------------------------------------------------------------ aplicar
function Impressao($db) {
  # Impressao digital do banco: por tabela, quantidade de linhas E resumo MD5 do conteudo (linhas ordenadas);
  # valores das sequencias; quantidade de indices, restricoes, funcoes, gatilhos, politicas e visoes.
  $q = "select coalesce(string_agg(x, ';' order by x), '') from (" +
    "select format('T %s.%s %s %s', n.nspname, c.relname, " +
    "(xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', n.nspname, c.relname), false, true, '')))[1]::text, " +
    "(xpath('/row/h/text()', query_to_xml(format('select md5(coalesce(string_agg(md5(t::text), %L order by md5(t::text)), %L)) as h from %I.%I t', '', '', n.nspname, c.relname), false, true, '')))[1]::text) x " +
    "from pg_class c join pg_namespace n on n.oid = c.relnamespace where c.relkind in ('r', 'p') and n.nspname not in ('pg_catalog', 'information_schema') and n.nspname not like 'pg_toast%' " +
    "union all select format('S %s.%s %s', schemaname, sequencename, coalesce(last_value::text, '-')) from pg_sequences where schemaname not in ('pg_catalog', 'information_schema') " +
    "union all select 'O indices ' || count(*) from pg_indexes where schemaname not in ('pg_catalog', 'information_schema') " +
    "union all select 'O restricoes ' || count(*) from pg_constraint k join pg_namespace n on n.oid = k.connamespace where n.nspname not in ('pg_catalog', 'information_schema') " +
    "union all select 'O funcoes ' || count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname not in ('pg_catalog', 'information_schema') " +
    "union all select 'O gatilhos ' || count(*) from pg_trigger where not tgisinternal " +
    "union all select 'O politicas ' || count(*) from pg_policy " +
    "union all select 'O visoes ' || count(*) from pg_views where schemaname not in ('pg_catalog', 'information_schema')) s"
  $o = & (Join-Path $pgbin "psql.exe") -h 127.0.0.1 -p $script:pg.Porta -U vyonix_admin -d $db -At -c $q 2>&1
  if ($LASTEXITCODE -ne 0) { throw ("impressao digital falhou em ${db}: " + ($o -join " ")) }
  return [string]($o -join "") }
function Amcheck($db) {
  # Verificacao estrutural dos indices B-tree (com conferencia contra as linhas) na COPIA restaurada.
  $q = "create extension if not exists amcheck; select count(*) from (select bt_index_check(c.oid, true) from pg_index i join pg_class c on c.oid = i.indexrelid join pg_am a on a.oid = c.relam where a.amname = 'btree' and c.relpersistence <> 't' and i.indisvalid) s"
  $o = & (Join-Path $pgbin "psql.exe") -h 127.0.0.1 -p $script:pg.Porta -U vyonix_admin -d $db -At -c $q 2>&1
  if ($LASTEXITCODE -ne 0) {
    $t = ($o -join " ")
    if ($t -match 'amcheck.*(not available|nao esta disponivel|não está disponível)|could not open extension control file') { return "amcheck indisponivel nesta versao do PostgreSQL" }
    throw ("verificacao dos indices (amcheck) encontrou problema: " + $t) }
  return ("amcheck: " + ([string]($o | Select-Object -Last 1)).Trim() + " indice(s) B-tree integros") }
function Inventario-Dados {
  # Arquivos DICOM (PACS) e configuracoes: quantidade, tamanho e resumo da lista (nome|tamanho|data). So leitura.
  $out = [ordered]@{}
  foreach ($d in @("PACS", "Platform")) {
    $p = Join-Path $dados $d
    if (-not (Test-Path $p)) { $out[$d] = "ausente"; continue }
    $fs = @(Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue | Sort-Object FullName)
    $lst = ($fs | ForEach-Object { $_.FullName.Substring($p.Length) + "|" + $_.Length + "|" + $_.LastWriteTimeUtc.Ticks }) -join "`n"
    $h = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($lst))).Replace("-", "").Substring(0, 16)
    $out[$d] = "$($fs.Count) arquivo(s), " + [math]::Round((($fs | Measure-Object Length -Sum).Sum) / 1MB, 1) + " MB, lista $h" }
  return $out }
function Backup-Logico {
  # Com Core/Worker/PACS parados (sem escritas), o banco ainda ligado: dump completo + prova de restauracao.
  $senha = Ler-Segredo "pg_superuser"
  if (-not $senha) { throw "senha local do banco ilegivel" }
  $env:PGPASSWORD = $senha
  $verif = "vyonix_verif_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
  $criado = $false
  try {
    $dump = Join-Path $rec "vyonix.dump"
    $o = & (Join-Path $pgbin "pg_dump.exe") -h 127.0.0.1 -p $script:pg.Porta -U vyonix_admin -Fc -f $dump vyonix 2>&1
    if ($LASTEXITCODE -ne 0) { throw ("pg_dump falhou (leitura completa do banco): " + ($o -join " ")) }
    & (Join-Path $pgbin "pg_dumpall.exe") -h 127.0.0.1 -p $script:pg.Porta -U vyonix_admin --globals-only -f (Join-Path $rec "papeis.sql") 2>&1 | Out-Null
    $h = (Get-FileHash $dump -Algorithm SHA256).Hash.ToLower()
    & (Join-Path $pgbin "pg_restore.exe") --list $dump *> $null
    if ($LASTEXITCODE -ne 0) { throw "pg_restore nao leu o backup" }
    $o = & (Join-Path $pgbin "createdb.exe") -h 127.0.0.1 -p $script:pg.Porta -U vyonix_admin $verif 2>&1
    if ($LASTEXITCODE -ne 0) { throw ("banco temporario de verificacao nao criado: " + ($o -join " ")) }
    $criado = $true
    $o = & (Join-Path $pgbin "pg_restore.exe") -h 127.0.0.1 -p $script:pg.Porta -U vyonix_admin -d $verif --no-owner --no-privileges --exit-on-error $dump 2>&1
    if ($LASTEXITCODE -ne 0) { throw ("restauracao de teste falhou: " + (($o | Select-Object -Last 5) -join " ")) }
    $a = Impressao "vyonix"; $r = Impressao $verif
    if ($a -ne $r) {
      $da = $a.Split(";"); $dr = $r.Split(";")
      $dif = @($da | Where-Object { $dr -notcontains $_ } | Select-Object -First 3) -join ", "
      throw "o banco restaurado difere do original (conteudo, sequencias ou estrutura): $dif" }
    $am = Amcheck $verif
    $tabs = @($a.Split(";") | Where-Object { $_ -like "T *" })
    $nt = $tabs.Count
    $nl = 0; foreach ($x in $tabs) { $pp = $x.Split(" "); if ($pp.Count -ge 3) { $nl += [int64]$pp[2] } }
    $fh = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($a))).Replace("-", "").ToLower()
    $info = [ordered]@{ at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss+00:00"); dump = "vyonix.dump"; bytes = (Get-Item $dump).Length; sha256 = $h
      origem = "Recuperar_VYONIX"; restauracao_testada = $true; tabelas = $nt; linhas = $nl
      conteudo_conferido = $true; impressao_sha256 = $fh; indices = $am }
    ($info | ConvertTo-Json) | Out-File (Join-Path $rec "backup.json") -Encoding ascii
    return "backup novo $dump (" + [math]::Round($info.bytes / 1MB, 1) + " MB, SHA-256 $($h.Substring(0,12))...): restaurado num banco temporario; conteudo identico ao original ($nt tabela(s), $nl linha(s): contagem e resumo MD5 de cada tabela, sequencias e estrutura); $am"
  } finally {
    if ($criado -and $verif.StartsWith("vyonix_verif_")) { & (Join-Path $pgbin "dropdb.exe") -h 127.0.0.1 -p $script:pg.Porta -U vyonix_admin $verif 2>&1 | Out-Null }
    $env:PGPASSWORD = $null
  } }
function Copia-Fria {
  $pg = (Get-Item $script:pg.Data -ErrorAction Stop).FullName.TrimEnd('\')
  $destino = Join-Path $rec "pgdata"
  $fs = @(Get-ChildItem $pg -Recurse -File -ErrorAction Stop)
  $tam = ($fs | Measure-Object Length -Sum).Sum
  $livre = (Get-PSDrive -Name ($dados.Substring(0, 1))).Free
  if ($livre -le ($tam * 1.2 + 1GB)) { throw ("espaco insuficiente para a copia a frio: " + [math]::Round($livre / 1GB, 1) + " GB livres, necessarios " + [math]::Round(($tam * 1.2 + 1GB) / 1GB, 1) + " GB") }
  if (Test-Path (Join-Path $pg "postmaster.pid")) {
    if (@(Get-Process -Name postgres -ErrorAction SilentlyContinue | Where-Object { Sob-App $_.Path }).Count) { throw "o PostgreSQL do VYONIX ainda esta em execucao: copia a frio seria inconsistente" } }
  New-Item -ItemType Directory -Path $destino -Force | Out-Null
  Copy-Item -Path (Join-Path $pg "*") -Destination $destino -Recurse -Force -ErrorAction Stop
  $dif = 0
  foreach ($f in $fs) {
    $rel = $f.FullName.Substring($pg.Length).TrimStart('\'); $c = Join-Path $destino $rel
    if (-not (Test-Path $c) -or (Get-FileHash $f.FullName -Algorithm SHA256).Hash -ne (Get-FileHash $c -Algorithm SHA256).Hash) { $dif++ } }
  if ($dif) { throw "$dif arquivo(s) da copia diferem do original" }
  $est = "nao verificavel (programas do PostgreSQL ausentes)"
  $pgc = Join-Path $pgbin "pg_controldata.exe"
  if (Test-Path $pgc) { $est = ((& $pgc -D $destino 2>$null | Select-String "Database cluster state") -replace '.*:\s*', '')
    if ($est -notmatch "shut down|desligado") { throw "copia nao esta em estado consistente (estado: $est)" } }
  ([ordered]@{ at = (Get-Date).ToUniversalTime().ToString("s"); origem = $pg; arquivos = $fs.Count; bytes = $tam; estado = $est; sha256_conferido = $true } | ConvertTo-Json) | Out-File (Join-Path $rec "copia-fria.json") -Encoding ascii
  return "copia a frio $destino ($($fs.Count) arquivos, " + [math]::Round($tam / 1MB, 1) + " MB): identica ao original (SHA-256 de cada arquivo); estado do cluster: $est. Para restaurar: Reverter_VYONIX (instrucoes no procedimento)" }
function Registrar-Estado {
  $e = Join-Path $rec "estado-anterior"; New-Item -ItemType Directory -Path $e -Force | Out-Null
  ($res | ConvertTo-Json -Depth 4) | Out-File (Join-Path $e "diagnostico.json") -Encoding utf8
  (ConvertTo-Json -InputObject @($script:svcInfo.Values) -Depth 4) | Out-File (Join-Path $e "servicos.json") -Encoding utf8
  foreach ($s in $script:svcInfo.Keys) {
    & reg.exe export "HKLM\SYSTEM\CurrentControlSet\Services\$s" (Join-Path $e "servico-$s.reg") /y | Out-Null
    (& sc.exe qfailure $s) | Out-File (Join-Path $e "servico-$s-recuperacao.txt") -Encoding utf8 }
  if ($script:regKey) { & reg.exe export ($script:regKey -replace '^HKLM:', 'HKLM') (Join-Path $e "registro-desinstalacao.reg") /y | Out-Null }
  @(Get-NetFirewallRule -Name "VYONIX-*" -ErrorAction SilentlyContinue | Select-Object Name, DisplayName, Enabled, Direction, Action, Profile) | ConvertTo-Json | Out-File (Join-Path $e "firewall.json") -Encoding utf8
  if (Test-Path $app) { Get-ChildItem $app -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { [pscustomobject]@{ arquivo = $_.FullName.Substring($appPrefix.Length); bytes = $_.Length; alterado = $_.LastWriteTime.ToString("s") } } | Export-Csv (Join-Path $e "arquivos-programa.csv") -NoTypeInformation -Encoding UTF8 }
  Acao "Estado anterior registrado em $e (servicos, registro, firewall, lista de arquivos)" }
function Copiar-Configuracao {
  $c = Join-Path $rec "configuracao"; New-Item -ItemType Directory -Path $c -Force | Out-Null
  foreach ($f in @("Platform\config.json", "Platform\secrets.json", "Deploy\secrets.json", "Deploy\deploy.db")) {
    $o = Join-Path $dados $f
    if (Test-Path $o) { Copy-Item $o (Join-Path $c ($f -replace '\\', '_')) -Force -ErrorAction SilentlyContinue } }
  foreach ($f in @("config.json", "secrets.json")) { $o = Join-Path $dados "Platform\$f"; if (Test-Path $o) { Copy-Item $o (Join-Path $rec $f) -Force -ErrorAction SilentlyContinue } }
  Acao "Configuracoes necessarias a restauracao copiadas para $c (segredos continuam cifrados pelo Windows)" }
function Parar($s) {
  $i = $script:svcInfo[$s]
  if (-not $i -or -not $i.Pertence -or $script:parados.Contains($s) -or -not (Get-Service -Name $s -ErrorAction SilentlyContinue)) { return }
  Start-Process -FilePath sc.exe -ArgumentList "failure $s reset= 0 actions= `"`"" -Wait -NoNewWindow | Out-Null
  & sc.exe config $s start= disabled | Out-Null
  & sc.exe stop $s | Out-Null
  for ($n = 0; $n -lt 90; $n++) { $st = (Get-Service -Name $s -ErrorAction SilentlyContinue).Status; if (-not $st -or $st -eq "Stopped") { break }; Start-Sleep 1 }
  $w = Get-CimInstance Win32_Service -Filter "Name='$s'" -ErrorAction SilentlyContinue
  if ($w -and $w.ProcessId) { Log "servico $s nao parou: encerrando PID $($w.ProcessId)"; & taskkill.exe /F /T /PID $w.ProcessId | Out-Null }
  [void]$script:parados.Add($s); Acao "Servico $s parado (sem reinicio automatico)" }
function Religar {
  # Volta ao estado anterior os servicos parados nesta execucao (quando o backup nao foi confirmado).
  foreach ($s in @("VyonixPostgreSQL", "VyonixCore", "VyonixWorker", "VyonixPacsEngine")) {
    if (-not $script:parados.Contains($s)) { continue }
    $i = $script:svcInfo[$s]
    $modo = switch ($i.StartMode) { "Auto" { if ($i.Delayed -eq 1) { "delayed-auto" } else { "auto" } } "Manual" { "demand" } "Disabled" { "disabled" } default { "auto" } }
    & sc.exe config $s start= $modo | Out-Null
    if ($i.State -eq "Running") { & sc.exe start $s | Out-Null; Start-Sleep 3 }
    Acao "Servico $s religado (inicio $modo)" }
  Acao "A recuperacao automatica dos servicos e reaplicada por: Menu Iniciar > VYONIX > Reparar instalacao" }

function Aplicar-Recuperacao {
  Log "=== recuperacao: inicio (dados em $dados NAO sao alterados)"
  $script:parados = New-Object System.Collections.ArrayList
  New-Item -ItemType Directory -Path $rec -Force | Out-Null
  $meta = [ordered]@{ tag = $tag; computador = $env:COMPUTERNAME; pasta_programa = $app; pasta_renomeada = $null; servicos_removidos = @(); backup = $null; dados_inalterados = $null; dados = $null; concluida = $false }
  Registrar-Estado
  $script:backupMsg = $null
  foreach ($s in $gravam) { Parar $s }
  $invAntes = Inventario-Dados
  if ($script:pg.Conecta -eq $true -and $script:pg.Binarios) {
    try { $script:backupMsg = Backup-Logico; Acao ("BACKUP CONFIRMADO: " + $script:backupMsg) }
    catch { Acao ("Backup novo nao confirmado: " + $_.Exception.Message + " - tentando copia a frio") } }
  Parar "VyonixPostgreSQL"
  foreach ($p in (Processos-App)) { Log "encerrando $($p.Name) PID $($p.ProcessId) ($($p.ExecutablePath))"; Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; [void]$acoes.Add("Processo $($p.Name) (PID $($p.ProcessId)) encerrado") }
  Start-Sleep 2
  if (-not $script:backupMsg -and $script:pg.Existe) {
    try { $script:backupMsg = Copia-Fria; Acao ("BACKUP CONFIRMADO: " + $script:backupMsg) }
    catch { Acao ("Copia a frio nao confirmada: " + $_.Exception.Message) } }
  if (-not $script:backupMsg -and $script:pg.Existe -and $script:ultimoBackup -and $script:ultimoLegivel -ne $false) {
    # Ultimo recurso: backup existente do DEPLOY, integro (SHA-256) e legivel. O cluster original nao e alterado.
    $script:backupMsg = "backup existente $($script:ultimoBackup) validado (SHA-256 confere" + $(if ($script:ultimoLegivel) { "; legivel pelo pg_restore" } else { "; legibilidade nao testada: programas do PostgreSQL ausentes" }) + "). O banco original em $($script:pg.Data) nao e alterado."
    Acao ("BACKUP CONFIRMADO: " + $script:backupMsg) }
  if (-not $script:pg.Existe) { $script:backupMsg = "nao se aplica: nao ha banco do VYONIX neste computador"; Acao $script:backupMsg }
  Copiar-Configuracao
  if (-not $script:backupMsg) {
    Religar
    Acao "RECUPERACAO NAO APLICADA: nao foi possivel confirmar um backup recuperavel. Nada foi removido nem renomeado."
    $meta.backup = "nao confirmado"; ($meta | ConvertTo-Json) | Out-File (Join-Path $rec "recuperacao.json") -Encoding utf8
    Log "=== recuperacao: interrompida com seguranca"; return 4 }
  $meta.backup = $script:backupMsg
  $parcial = $false
  foreach ($s in $servicos) {
    $i = $script:svcInfo[$s]
    if (-not $i) { continue }
    if (-not $i.Pertence) { Acao "Servico $s NAO alterado (programa fora da pasta do VYONIX Platform)"; continue }
    Parar $s
    $r = & sc.exe delete $s; Log ("sc delete $s : " + ($r -join " "))
    Start-Sleep 2
    $ainda = Servico-Info $s
    if (-not $ainda) { $meta.servicos_removidos += $s; Acao "Servico $s removido" }
    elseif ($ainda.DeleteFlag) { $meta.servicos_removidos += $s; $parcial = $true; Acao "Servico $s marcado para exclusao: aberto por outro programa; o Windows o remove ao reiniciar" }
    else { $parcial = $true; Acao ("Servico $s NAO removido: " + ($r -join " ")) }
  }
  if (Test-Path $app) {
    $novo = "Platform.anterior-" + $tag
    try { Rename-Item -Path $app -NewName $novo -ErrorAction Stop; $meta.pasta_renomeada = (Join-Path (Split-Path $app) $novo); Acao "Pasta do programa renomeada para $novo (nao apagada)" }
    catch { $parcial = $true; Acao ("Pasta do programa NAO renomeada (arquivo em uso por outro programa: " + $_.Exception.Message + "). Nada foi apagado. Reinicie o Windows e execute de novo.") }
  }
  if ($script:regKey -and $script:regOrfao) {
    $bak = Join-Path $rec "estado-anterior\registro-desinstalacao.reg"
    if (Test-Path $bak) { Remove-Item $script:regKey -Recurse -Force; Acao "Registro de desinstalacao orfao removido (copia em $bak)" }
    else { $parcial = $true; Acao "Registro orfao mantido: a copia .reg nao foi gravada" }
  }
  $invDepois = Inventario-Dados
  $iguais = (($invAntes | ConvertTo-Json) -eq ($invDepois | ConvertTo-Json))
  $meta.dados_inalterados = $iguais; $meta.dados = $invDepois
  if ($iguais) { Acao ("Arquivos DICOM e configuracoes inalterados: PACS " + $invDepois.PACS + "; Platform " + $invDepois.Platform) }
  else { $parcial = $true; Acao ("ATENCAO: a lista de arquivos de dados mudou durante a recuperacao (antes: " + ($invAntes | ConvertTo-Json -Compress) + "; depois: " + ($invDepois | ConvertTo-Json -Compress) + ")") }
  $meta.concluida = -not $parcial
  ($meta | ConvertTo-Json) | Out-File (Join-Path $rec "recuperacao.json") -Encoding utf8
  Log "=== recuperacao: fim ($(if ($parcial) { 'PARCIAL' } else { 'completa' }))"
  if ($parcial) { return 5 } else { return 0 }
}

# ------------------------------------------------------------------ execucao
Write-Host "VYONIX - recuperacao de instalacao. Modo: $(if ($Aplicar) { 'APLICAR (com confirmacao)' } else { 'somente diagnostico (nada e alterado)' })"
if (-not (Admin)) { Write-Host "Execute como administrador (use Recuperar_VYONIX.cmd)."; exit 2 }
Diagnostico
Montar-Plano
$antes = @($res | ForEach-Object { $_ })
$planoTxt = Plano-Linhas
$codigo = 0; $resultado = "Somente diagnostico: nada foi alterado."
if ($Aplicar) {
  Write-Host ""; Write-Host "===== O QUE A RECUPERACAO VAI FAZER ====="; $planoTxt | ForEach-Object { Write-Host $_ }; Write-Host ""
  if ($script:plano.Vazio) { $resultado = "Nada a fazer: o computador ja esta pronto para instalar." }
  else {
    $c = "RECUPERAR"
    if (-not $SemConfirmar) { $c = if ($PSBoundParameters.ContainsKey("Confirmacao")) { $Confirmacao } else { Read-Host "Digite RECUPERAR para continuar (qualquer outra resposta cancela)" } }
    if ($c -ne "RECUPERAR") { $resultado = "Cancelado antes da confirmacao: nada foi alterado."; $codigo = 3 }
    else {
      $codigo = [int](@(Aplicar-Recuperacao)[-1])
      $resultado = switch ($codigo) { 0 { "Recuperacao concluida." } 4 { "Recuperacao NAO aplicada: backup nao confirmado; servicos religados; nada removido." } 5 { "Recuperacao PARCIAL: veja 'O que foi feito'. Reinicie o Windows e execute de novo (e seguro repetir)." } }
      Diagnostico
    }
  }
}
$cor = @{ "OK"="#2e7d4f"; "AUSENTE"="#45606f"; "INFO"="#45606f"; "DEFEITO"="#b3261e"; "REINICIAR"="#a85a00"; "ATENCAO"="#a85a00"; "NAO PERTENCE"="#6a3fa0" }
function Tabela($lst) { ($lst | ForEach-Object { "<tr><td>$(Html $_.id)</td><td><span class='b' style='background:$($cor[$_.estado])'>$(Html $_.estado)</span></td><td><strong>$(Html $_.titulo)</strong><div>$(Html $_.detalhe)</div>" + $(if ($_.acao) { "<div class='a'>O que fazer: $(Html $_.acao)</div>" } else { "" }) + "</td></tr>" }) -join "`n" }
$prox = if ($codigo -eq 3) { "Nada foi alterado. Execute de novo quando quiser aplicar." }
        elseif ($codigo -eq 4) { "Envie este relatorio ao suporte: o backup nao pode ser confirmado e por isso nada foi removido." }
        elseif (@($res | Where-Object { $_.estado -eq "REINICIAR" }).Count -or $codigo -eq 5) { "Reinicie o Windows, execute Recuperar_VYONIX.cmd de novo (diagnostico) e depois instale a versao nova." }
        elseif (@($res | Where-Object { $_.estado -in @("DEFEITO", "ATENCAO") }).Count -and -not $Aplicar) { "Execute Recuperar_VYONIX.cmd e escolha APLICAR; depois instale a versao nova." }
        else { "Instale a versao nova normalmente (ela reconhece os dados e faz uma atualizacao)." }
$planoHtml = "<ol class='p'>" + (($planoTxt | ForEach-Object { "<li>$(Html $_)</li>" }) -join "") + "</ol>"
$html = @"
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>VYONIX - Recuperacao da instalacao</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;background:#f1f5f7;color:#16242f;margin:0;padding:24px}main{max-width:980px;margin:0 auto;background:#fff;border:1px solid #d7e0e6;border-radius:10px;padding:24px}
table{width:100%;border-collapse:collapse;margin-top:10px}td{border-top:1px solid #e3e9ee;padding:8px;vertical-align:top}.b{color:#fff;border-radius:99px;padding:2px 10px;font-size:.8rem;white-space:nowrap}.a{color:#45606f;margin-top:4px}.p li{margin:4px 0}</style></head>
<body><main><h1>VYONIX - Recuperacao da instalacao</h1>
<p>Computador <strong>$(Html $env:COMPUTERNAME)</strong> - $($agora.ToString("dd/MM/yyyy HH:mm")) - modo: <strong>$(if ($Aplicar) { "APLICAR" } else { "somente diagnostico (nada alterado)" })</strong></p>
<h2>Resultado</h2><p><strong>$(Html $resultado)</strong></p>
<h2>Proximo passo</h2><p><strong>$(Html $prox)</strong></p>
$(if ($Aplicar -and $codigo -ne 3 -and -not $script:plano.Vazio) { "<h2>O que foi feito</h2><ul>" + (($acoes | ForEach-Object { "<li>$(Html $_)</li>" }) -join "") + "</ul><p>Backup, estado anterior e configuracoes: <strong>$(Html $rec)</strong>. Para desfazer: Reverter_VYONIX.cmd.</p><h2>Plano que foi confirmado</h2>$planoHtml<h2>Situacao antes</h2><table>$(Tabela $antes)</table><h2>Situacao depois</h2>" } else { "<h2>O que a recuperacao faria (nada foi feito)</h2>$planoHtml<h2>Situacao</h2>" })
<table>$(Tabela $res)</table>
<p style="color:#45606f">Dados em ProgramData\VYONIX e o VYONIX DICOM Print nunca sao alterados por esta ferramenta. $(if ($Aplicar -and $codigo -ne 3) { "Registro desta execucao: " + (Html $logf) })</p></main></body></html>
"@
$html | Out-File -FilePath $arq -Encoding utf8
$res | ForEach-Object { Write-Host ("[" + $_.estado + "] " + $_.titulo + ": " + $_.detalhe) }
Write-Host ""; Write-Host ("Resultado: " + $resultado); Write-Host ("Proximo passo: " + $prox); Write-Host ("Relatorio: " + $arq)
if (-not $SemAbrir) { Start-Process $arq }
exit $codigo
