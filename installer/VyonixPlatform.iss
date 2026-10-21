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

#define AppName "VYONIX"
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
OutputBaseFilename=VYONIX_Setup_x64
UninstallDisplayName={#AppName} (plataforma)
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=no
SetupLogging=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Run]
Filename: "{app}\{#DeployExe}"; Parameters: "install --config ""{param:DEPLOYCONFIG}"" --approve-all --silent"; Flags: runhidden waituntilterminated; Check: SilentInstall; StatusMsg: "Aplicando o plano aprovado (VYONIX DEPLOY)..."
Filename: "{app}\{#DeployExe}"; Parameters: "update --approve-all --silent"; Flags: runhidden waituntilterminated; Check: SilentUpdate; StatusMsg: "Atualizando (backup, migração e serviços)..."
Filename: "{app}\{#DeployExe}"; Parameters: "wizard"; Description: "Abrir o assistente do VYONIX DEPLOY"; Flags: nowait postinstall skipifsilent runhidden

[UninstallRun]
; Remove serviços, regra de firewall e atalhos. Dados (ProgramData\VYONIX) e o DICOM Print são preservados.
Filename: "{app}\{#DeployExe}"; Parameters: "uninstall --approve-all --silent"; Flags: runhidden waituntilterminated; RunOnceId: "VyonixDeployUninstall"

[Code]
function SilentInstall(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:DEPLOYCONFIG|}') <> '');
end;

function SilentUpdate(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:DEPLOYUPDATE|}') = '1');
end;

procedure StopService(const Name: String);
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\sc.exe'), 'stop ' + Name, '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function ServiceState(const Name: String): String;
var
  Code: Integer;
  Tmp: String;
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := '';
  Tmp := ExpandConstant('{tmp}\svc_' + Name + '.txt');
  if Exec(ExpandConstant('{cmd}'), '/C ' + ExpandConstant('{sys}\sc.exe') + ' query ' + Name + ' > "' + Tmp + '"', '',
          SW_HIDE, ewWaitUntilTerminated, Code) and LoadStringsFromFile(Tmp, Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
      if Pos('STATE', Uppercase(Lines[I])) > 0 then
        Result := Lines[I];
end;

{ Atualização: os serviços usam os arquivos do programa; são parados antes da cópia e reiniciados
  pelo DEPLOY depois do backup e da migração. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  N: Integer;
  Names: array of String;
  I: Integer;
begin
  SetArrayLength(Names, 3);
  Names[0] := 'VyonixCore'; Names[1] := 'VyonixWorker'; Names[2] := 'VyonixPostgreSQL';
  for I := 0 to 2 do
  begin
    StopService(Names[I]);
    N := 0;
    while (Pos('RUNNING', ServiceState(Names[I])) > 0) or (Pos('STOP_PENDING', ServiceState(Names[I])) > 0) do
    begin
      Sleep(1000);
      N := N + 1;
      if N > 90 then Break;
    end;
  end;
  Result := '';
end;
