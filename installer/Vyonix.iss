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
Name: "firewall"; Description: "Permitir que equipamentos DICOM se conectem ao VYONIX (Firewall do Windows, redes privadas e de domínio)"; GroupDescription: "Rede:"

[Dirs]
; Dados da máquina: preservados em atualizações e, por padrão, na desinstalação.
; Usuários comuns precisam gravar o banco enquanto não existe o serviço Windows (Fase 7);
; nessa fase a permissão será restringida à conta do serviço.
Name: "{#DataDir}"; Permissions: users-modify; Flags: uninsneveruninstall

[InstallDelete]
; Atualização: remove bibliotecas da versão anterior para não misturar DLLs.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "AVISO.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""VYONIX DICOM Print"""; Flags: runhidden; Tasks: firewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""VYONIX DICOM Print"" dir=in action=allow program=""{app}\{#AppExe}"" enable=yes profile=private,domain"; Flags: runhidden; Tasks: firewall; StatusMsg: "Configurando o Firewall do Windows..."
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""VYONIX DICOM Print"""; Flags: runhidden; RunOnceId: "VyonixFirewall"

[Code]
var
  RemoveData: Boolean;

function InitializeUninstall(): Boolean;
begin
  RemoveData := False;
  if not UninstallSilent() then
    RemoveData := MsgBox(
      'Deseja remover também os dados do VYONIX (banco de dados, configurações, imagens e logs)?' + #13#10 + #13#10 +
      'Escolha "Não" para manter os dados e reutilizá-los em uma reinstalação.',
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
