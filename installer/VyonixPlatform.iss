; Inno Setup 6 — VYONIX_Setup_x64.exe (plataforma VYONIX: Core, Worker, PostgreSQL e DEPLOY).
;
; O instalador só copia os arquivos (Python embutido no pacote PyInstaller e PostgreSQL 17) e abre o
; assistente do VYONIX DEPLOY. Nada é configurado sem o plano aprovado no assistente — exceto em modo
; silencioso explícito (implantação em massa), em que a aprovação vem da linha de comando:
;
;   VYONIX_Setup_x64.exe /VERYSILENT /DEPLOYCONFIG="C:\caminho\opcoes.json"      instalação nova aprovada
;   VYONIX_Setup_x64.exe /VERYSILENT /DEPLOYUPDATE=1                             atualização aprovada
;   (senha do primeiro administrador em VYONIX_ADMIN_PASSWORD)
;
; Compilação: ISCC.exe /DAppVersion=0.2.0 /DFileVersion=0.2.0.0 installer\VyonixPlatform.iss

#ifndef AppVersion
  #error Informe /DAppVersion=...
#endif
#ifndef FileVersion
  #error Informe /DFileVersion=a.b.c.d
#endif
#ifndef DistDir
  #define DistDir "..\dist\VyonixPlatform"
#endif

#ifdef Homolog
  #define AppName "VYONIX Homologacao"
#else
  #define AppName "VYONIX"
#endif
#define AppPublisher "VYONIX"
#define DeployExe "vyonix-deploy.exe"

[Setup]
; AppId fixo: atualizações reconhecem a instalação existente. Nunca alterar.
AppId={{EE8E242D-1625-4E1B-8317-5BFD8610DD26}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#FileVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription=Instalador da plataforma VYONIX
DefaultDirName={commonpf64}\VYONIX\Platform
DisableDirPage=yes
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
PrivilegesRequired=admin
OutputDir=..\dist\installer-platform
#ifdef Homolog
OutputBaseFilename=VYONIX_Homologacao_Setup_x64
#else
OutputBaseFilename=VYONIX_Setup_x64
#endif
UninstallDisplayName={#AppName} (plataforma)
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=no
SetupLogging=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
FinishedHeadingLabel=Arquivos do VYONIX copiados
FinishedLabel=Falta um passo: o assistente do VYONIX DEPLOY configura o banco, os serviços e o acesso pelo navegador. Deixe marcado "Abrir o assistente" e conclua. Sem aprovar o plano no assistente o sistema não funciona. Depois, use Menu Iniciar → VYONIX → "VYONIX - Verificar funcionamento".

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "common\*"; DestDir: "{app}"; Flags: ignoreversion
Source: "validacao\*"; DestDir: "{app}\validacao"; Flags: ignoreversion
#ifdef Homolog
Source: "homologacao\*"; DestDir: "{app}"; Flags: ignoreversion
#endif

[Icons]
; Disponíveis já antes da configuração: o assistente (administrador) e a verificação de funcionamento (sem
; administrador), que abre o sistema ou explica o que falhou.
Name: "{commonprograms}\VYONIX\VYONIX - Assistente de instalacao"; Filename: "{app}\Assistente_Instalacao.cmd"; WorkingDir: "{app}"
Name: "{commonprograms}\VYONIX\VYONIX - Verificar funcionamento"; Filename: "{app}\vyonix-deploy.exe"; Parameters: "abrir --porta 8444"; WorkingDir: "{app}"
Name: "{commonprograms}\VYONIX\VYONIX - Validar instalacao"; Filename: "{app}\validacao\Validar_VYONIX.cmd"; WorkingDir: "{app}\validacao"
Name: "{commonprograms}\VYONIX\VYONIX - Reparar instalacao"; Filename: "{app}\Reparar_VYONIX.cmd"; WorkingDir: "{app}"
#ifdef Homolog
Name: "{commonprograms}\VYONIX\VYONIX Homologacao - Preparar modulos"; Filename: "{app}\Preparar_Homologacao.cmd"; WorkingDir: "{app}"
Name: "{commonprograms}\VYONIX\VYONIX Homologacao - Enviar exame simulado"; Filename: "{app}\Enviar_Exame_Simulado.cmd"; WorkingDir: "{app}"
Name: "{commonprograms}\VYONIX\LEIA-ME Homologacao"; Filename: "{app}\LEIA-ME_HOMOLOGACAO.txt"
Name: "{commonprograms}\VYONIX\VYONIX - Abrir sistema"; Filename: "{app}\vyonix-deploy.exe"; Parameters: "abrir --porta 8444"; WorkingDir: "{app}"
Name: "{commonprograms}\VYONIX\VYONIX - Diagnostico"; Filename: "{app}\Diagnostico.cmd"; WorkingDir: "{app}"
#endif

[Run]
Filename: "{app}\{#DeployExe}"; Parameters: "install --config ""{param:DEPLOYCONFIG}"" --approve-all --silent"; Flags: runhidden waituntilterminated; Check: SilentInstall; StatusMsg: "Aplicando o plano aprovado (VYONIX DEPLOY)..."
Filename: "{app}\{#DeployExe}"; Parameters: "update --approve-all --silent"; Flags: runhidden waituntilterminated; Check: SilentUpdate; StatusMsg: "Atualizando (backup, migração e serviços)..."
; Atualização sobre uma instalação existente (dados em ProgramData\VYONIX): marcado por padrão, conclui a atualização
; (backup, migração e serviços) com o progresso visível — sem desinstalar nada nem passar pelo assistente.
Filename: "{app}\Atualizar_VYONIX.cmd"; Description: "Concluir a atualização agora (backup do banco, migração e reinício dos serviços; dados preservados)"; Flags: postinstall skipifsilent waituntilterminated; Check: IsUpgrade
Filename: "{app}\{#DeployExe}"; Parameters: "wizard"; Description: "Abrir o assistente do VYONIX DEPLOY"; Flags: nowait postinstall skipifsilent runhidden; Check: not IsUpgrade
Filename: "{app}\{#DeployExe}"; Parameters: "wizard"; Description: "Abrir o assistente do VYONIX DEPLOY"; Flags: nowait postinstall skipifsilent runhidden unchecked; Check: IsUpgrade

[UninstallRun]
; Remove serviços, regra de firewall e atalhos. Dados (ProgramData\VYONIX) e o DICOM Print são preservados.
Filename: "{app}\{#DeployExe}"; Parameters: "uninstall --approve-all --silent"; Flags: runhidden waituntilterminated; RunOnceId: "VyonixDeployUninstall"

[Code]
const
  NSERV = 4;

var
  Services: array of String;

function ServiceNames(): Boolean;
begin
  SetArrayLength(Services, NSERV);
  { VyonixPacsEngine (módulo PACS) também executa VyonixPlatform.exe e o Orthanc.exe da pasta do programa.
    Nunca inclui o VyonixDicomPrint. }
  Services[0] := 'VyonixPacsEngine'; Services[1] := 'VyonixCore'; Services[2] := 'VyonixWorker';
  Services[3] := 'VyonixPostgreSQL';
  Result := True;
end;

function LogFile(): String;
begin
  Result := ExpandConstant('{commonappdata}\VYONIX\Logs\instalador.log');
end;

{ Registro detalhado de instalação, atualização, reparo e desinstalação (além do log do Inno em %TEMP%). }
procedure L(const Msg: String);
begin
  ForceDirectories(ExtractFileDir(LogFile()));
  SaveStringToFile(LogFile(), GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':') + '  ' + Msg + #13#10, True);
  Log(Msg);
end;

function Sc(const Params: String): Integer;
begin
  if not Exec(ExpandConstant('{sys}\sc.exe'), Params, '', SW_HIDE, ewWaitUntilTerminated, Result) then
    Result := -1;
  L('sc ' + Params + ' -> ' + IntToStr(Result));
end;

function IsUpgrade(): Boolean;
begin
  { Instalação anterior configurada (dados preservados em ProgramData, mesmo depois de desinstalar). }
  Result := FileExists(ExpandConstant('{commonappdata}\VYONIX\Platform\config.json'));
end;

function SilentInstall(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:DEPLOYCONFIG|}') <> '');
end;

function SilentUpdate(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:DEPLOYUPDATE|}') = '1');
end;

function ServiceState(const Name: String): String;
var
  Code: Integer;
  Tmp: String;
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := '';
  Tmp := GetTempDir() + 'vyonix_svc_' + Name + '.txt';
  DeleteFile(Tmp);
  if Exec(ExpandConstant('{cmd}'), '/C ' + ExpandConstant('{sys}\sc.exe') + ' query ' + Name + ' > "' + Tmp + '"', '',
          SW_HIDE, ewWaitUntilTerminated, Code) and LoadStringsFromFile(Tmp, Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
      if Pos('STATE', Uppercase(Lines[I])) > 0 then
        Result := Trim(Lines[I]);
end;

function WaitStopped(const Name: String; Seconds: Integer): Boolean;
var
  N: Integer;
  St: String;
begin
  N := 0;
  St := ServiceState(Name);
  while (Pos('RUNNING', St) > 0) or (Pos('PENDING', St) > 0) do
  begin
    Sleep(1000);
    N := N + 1;
    if N > Seconds then Break;
    St := ServiceState(Name);
  end;
  Result := not ((Pos('RUNNING', St) > 0) or (Pos('PENDING', St) > 0));
  L(Name + ': ' + St + ' (' + IntToStr(N) + ' s)');
end;

{ Encerra processos que executam arquivos da pasta do programa (assistente esquecido aberto, Orthanc ou
  PostgreSQL órfãos). Só desta pasta: nunca o DICOM Print nem outros programas. }
procedure KillAppProcesses(const Dir: String);
var
  Code: Integer;
  Ps: String;
begin
  Ps := GetTempDir() + 'vyonix_procs.ps1';
  SaveStringToFile(Ps,
    '$d = [IO.Path]::GetFullPath(''' + Dir + ''').TrimEnd([char]92) + [char]92' + #13#10 +
    'Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($d, ' +
    '[StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { "encerrado " + $_.ProcessId + " " + $_.ExecutablePath; ' +
    'Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }' + #13#10, False);
  Exec(ExpandConstant('{cmd}'), '/C powershell -NoProfile -ExecutionPolicy Bypass -File "' + Ps + '" >> "' +
       LogFile() + '" 2>&1', '', SW_HIDE, ewWaitUntilTerminated, Code);
  L('processos da pasta do programa verificados (' + Dir + ')');
end;

{ Para o serviço sem deixar o Windows reiniciá-lo: sem recuperação automática enquanto os arquivos são trocados ou
  removidos (na atualização o DEPLOY reaplica a recuperação e o início automático). Disabled = desinstalação. }
procedure Neutralize(const Name: String; Disabled: Boolean);
begin
  if ServiceState(Name) = '' then
  begin
    L(Name + ': não registrado');
    Exit;
  end;
  Sc('failure ' + Name + ' reset= 0 actions= ""');
  if Disabled then
    Sc('config ' + Name + ' start= disabled');
  Sc('stop ' + Name);
  WaitStopped(Name, 90);
end;

{ Atualização ou reinstalação: os serviços e o assistente usam os arquivos do programa; são parados antes da cópia
  e reiniciados pelo DEPLOY depois do backup e da migração. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  I: Integer;
begin
  ServiceNames();
  L('=== instalação/atualização {#AppVersion} em ' + ExpandConstant('{app}') + '; instalação anterior: ' +
    IntToStr(Ord(IsUpgrade())));
  for I := 0 to NSERV - 1 do
    Neutralize(Services[I], False);
  KillAppProcesses(ExpandConstant('{app}'));
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if IsUpgrade() then
      L('arquivos copiados; próximo passo: concluir a atualização (DEPLOY update)')
    else
      L('arquivos copiados; próximo passo: assistente do DEPLOY');
  end;
end;

{ Desinstalação: 1) neutraliza os serviços (sem recuperação, desativados, parados) e fecha processos da pasta do
  programa; 2) o DEPLOY remove serviços, regras de firewall e atalhos ([UninstallRun]); 3) o que restar (serviço ou
  processo) é removido aqui e a pasta do programa é apagada. Dados (ProgramData\VYONIX) e DICOM Print preservados. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  I: Integer;
  Left: String;
begin
  ServiceNames();
  if CurUninstallStep = usUninstall then
  begin
    L('=== desinstalação de ' + ExpandConstant('{app}'));
    for I := 0 to NSERV - 1 do
      Neutralize(Services[I], True);
    KillAppProcesses(ExpandConstant('{app}'));
  end
  else if CurUninstallStep = usPostUninstall then
  begin
    Left := '';
    for I := 0 to NSERV - 1 do
      if ServiceState(Services[I]) <> '' then
      begin
        Neutralize(Services[I], True);
        Sc('delete ' + Services[I]);
        Sleep(2000);
        if ServiceState(Services[I]) <> '' then
          Left := Left + ' ' + Services[I];
      end;
    KillAppProcesses(ExpandConstant('{app}'));
    if DirExists(ExpandConstant('{app}')) then
    begin
      if DelTree(ExpandConstant('{app}'), True, True, True) then
        L('pasta do programa removida')
      else
        L('pasta do programa: itens não removidos (arquivo em uso?)');
    end;
    if Left <> '' then
    begin
      L('serviços marcados para exclusão até reiniciar:' + Left);
      if not UninstallSilent() then
        MsgBox('O VYONIX foi desinstalado. O Windows ainda mantém' + Left + ' marcado(s) para exclusão: ' +
               'reinicie o computador antes de instalar de novo. Os dados foram preservados.', mbInformation, MB_OK);
    end
    else
      L('desinstalação concluída; dados preservados em ' + ExpandConstant('{commonappdata}\VYONIX'));
  end;
end;
