; Inno Setup 6 — instalador do VYONIX DICOM Print (Windows 10 1809+ e Windows 11, x64).
;
; Pré-requisitos (gerados pelo build):
;   ..\dist\Vyonix\Vyonix.exe        (PyInstaller onedir)
;   ..\build\vyonix.ico, wizard_large.bmp, wizard_small.bmp   (tools\make_icon.py)
;
; Compilação:
;   ISCC.exe /DAppVersion=1.0.0.dev1 /DFileVersion=1.0.0.1 installer\Vyonix.iss
;
; Resultado: ..\dist\installer\VYONIX_DICOM_Print_Setup_v<AppVersion>_x64.exe

#ifndef AppVersion
  #error Informe /DAppVersion=... (versão de app\__init__.py)
#endif
#ifndef FileVersion
  #error Informe /DFileVersion=a.b.c.d
#endif

#ifndef DistDir
  #define DistDir "..\dist\Vyonix"
#endif
#ifndef Suffix
  #define Suffix ""
#endif

#define AppName "VYONIX DICOM Print"
#define AppPublisher "VYONIX"
#define AppExe "Vyonix.exe"
#define DataDir "{commonappdata}\VYONIX\DICOM Print"
#define UserDataDir "{localappdata}\VYONIX\DICOM Print"
; Cofre do licenciamento (Installation ID, DEMO, Time Integrity): NUNCA removido pela desinstalação.
#define LicensingDir "{commonappdata}\VYONIX\Licensing"
#define UninstallKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\{8C4E2D6A-3F1B-4B7E-9A2C-5D1E7F9B0A11}_is1"

[Setup]
; AppId fixo: atualizações reconhecem a instalação existente. Nunca alterar.
AppId={{8C4E2D6A-3F1B-4B7E-9A2C-5D1E7F9B0A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppComments=Precisão em cada imagem.
VersionInfoVersion={#FileVersion}
VersionInfoProductVersion={#FileVersion}
VersionInfoProductName={#AppName}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=Instalador do {#AppName}
DefaultDirName={commonpf64}\VYONIX\DICOM Print
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Requisito mínimo do produto: Windows 10 64 bits, versão 1809 (Qt 6 + Python 3.12).
MinVersion=10.0.17763
; Program Files e ProgramData exigem privilégios administrativos.
PrivilegesRequired=admin
OutputDir=..\dist\installer
OutputBaseFilename=VYONIX_DICOM_Print_Setup_v{#AppVersion}_x64{#Suffix}
SetupIconFile=..\build\vyonix.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=..\build\wizard_large.bmp
WizardSmallImageFile=..\build\wizard_small.bmp
InfoBeforeFile=AVISO.txt
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "service"; Description: "Instalar o serviço Windows (recepção e impressão continuam com o VYONIX fechado e após reiniciar o computador)"; GroupDescription: "Serviço:"
Name: "tray"; Description: "Mostrar o ícone do VYONIX na bandeja ao entrar no Windows"; GroupDescription: "Serviço:"
Name: "firewall"; Description: "Permitir que equipamentos DICOM se conectem ao VYONIX (Firewall do Windows, redes privadas e de domínio)"; GroupDescription: "Rede:"

[Dirs]
; Dados da máquina: preservados em atualizações e, por padrão, na desinstalação.
; O serviço (conta Sistema Local) e a interface (usuário comum) compartilham o banco em ProgramData;
; por isso Usuários têm permissão de modificação (limitação documentada no Manual de Instalação).
Name: "{#DataDir}"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{#LicensingDir}"; Permissions: users-modify; Flags: uninsneveruninstall

[InstallDelete]
; Atualização: remove bibliotecas da versão anterior para não misturar DLLs.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "AVISO.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "VYONIX DICOM Print"; ValueData: """{app}\{#AppExe}"" --tray"; Flags: uninsdeletevalue; Tasks: tray

[Run]
; Licenciamento: instalação nova (novo Installation ID) × atualização (ID, ativação e licença preservados).
; A distinção vem da entrada de desinstalação do Windows (lida antes da cópia dos arquivos) e do
; registro selado da instalação — não da simples presença de um arquivo.
Filename: "{app}\{#AppExe}"; Parameters: "--installation install --upgrade --report ""{#LicensingDir}\instalador.json"""; Flags: runhidden waituntilterminated; Check: IsUpgrade; StatusMsg: "Preservando a ativação da instalação existente..."
Filename: "{app}\{#AppExe}"; Parameters: "--installation install --fresh --report ""{#LicensingDir}\instalador.json"""; Flags: runhidden waituntilterminated; Check: not IsUpgrade; StatusMsg: "Registrando a nova instalação..."
; Serviço Windows: instala (ou atualiza) com início automático atrasado, reinício automático em falhas.
Filename: "{app}\VyonixService.exe"; Parameters: "--startup delayed install"; Flags: runhidden waituntilterminated; Tasks: service; StatusMsg: "Instalando o serviço Windows..."
Filename: "{app}\VyonixService.exe"; Parameters: "--startup delayed update"; Flags: runhidden waituntilterminated; Tasks: service
Filename: "{sys}\sc.exe"; Parameters: "failure VyonixDicomPrint reset= 86400 actions= restart/5000/restart/15000/restart/60000"; Flags: runhidden waituntilterminated; Tasks: service
Filename: "{app}\VyonixService.exe"; Parameters: "--wait 60 start"; Flags: runhidden waituntilterminated; Tasks: service; StatusMsg: "Iniciando o serviço Windows..."
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""VYONIX DICOM Print (serviço)"""; Flags: runhidden; Tasks: firewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""VYONIX DICOM Print (serviço)"" dir=in action=allow program=""{app}\VyonixService.exe"" enable=yes profile=private,domain"; Flags: runhidden; Tasks: firewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""VYONIX DICOM Print"""; Flags: runhidden; Tasks: firewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""VYONIX DICOM Print"" dir=in action=allow program=""{app}\{#AppExe}"" enable=yes profile=private,domain"; Flags: runhidden; Tasks: firewall; StatusMsg: "Configurando o Firewall do Windows..."
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{app}\VyonixService.exe"; Parameters: "--wait 60 stop"; Flags: runhidden waituntilterminated; RunOnceId: "VyonixServiceStop"
Filename: "{app}\{#AppExe}"; Parameters: "--installation uninstall --report ""{#LicensingDir}\desinstalador.json"""; Flags: runhidden waituntilterminated; RunOnceId: "VyonixEndActivation"
Filename: "{app}\VyonixService.exe"; Parameters: "remove"; Flags: runhidden waituntilterminated; RunOnceId: "VyonixServiceRemove"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""VYONIX DICOM Print (serviço)"""; Flags: runhidden; RunOnceId: "VyonixFirewallService"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""VYONIX DICOM Print"""; Flags: runhidden; RunOnceId: "VyonixFirewall"

[Code]
var
  RemoveData: Boolean;
  Upgrading: Boolean;

{ Atualização × instalação nova: consulta feita ANTES de copiar os arquivos. }
function InitializeSetup(): Boolean;
begin
  Upgrading := RegKeyExists(HKLM64, '{#UninstallKey}') or RegKeyExists(HKLM32, '{#UninstallKey}');
  Result := True;
end;

function IsUpgrade(): Boolean;
begin
  Result := Upgrading;
end;

{ Atualização: para o serviço da versão anterior antes de substituir os arquivos. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
  Exe: String;
begin
  Result := '';
  Exe := ExpandConstant('{app}\VyonixService.exe');
  if FileExists(Exe) then
    Exec(Exe, '--wait 60 stop', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function InitializeUninstall(): Boolean;
begin
  RemoveData := False;
  if not UninstallSilent() then
    RemoveData := MsgBox(
      'Deseja remover também os dados do VYONIX (banco de dados, configurações, imagens e logs)?' + #13#10 + #13#10 +
      'Escolha "Não" para manter os dados e reutilizá-los em uma reinstalação.' + #13#10 + #13#10 +
      'Em qualquer caso, a ativação desta instalação é encerrada: uma nova instalação exigirá nova licença.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and RemoveData then
  begin
    DelTree(ExpandConstant('{#DataDir}'), True, True, True);
    DelTree(ExpandConstant('{#UserDataDir}'), True, True, True);
  end;
end;
