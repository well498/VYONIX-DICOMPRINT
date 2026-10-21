; Inno Setup 6 — instalador OPCIONAL do VYONIX License Manager (Windows 10/11 x64).
;
; Instala o mesmo executável portátil (dist\VYONIX_License_Manager.exe) em Arquivos de Programas,
; com atalho no menu Iniciar. Instalado, os dados ficam em %APPDATA%\VYONIX\License Manager do
; administrador (marcador installed.flag). Este instalador NÃO faz parte do instalador comercial
; do VYONIX DICOM Print e não contém chaves privadas.
;
;   ISCC.exe /DAppVersion=1.0.0 /DFileVersion=1.0.0.0 installer\LicenseManager.iss
;
; Resultado: ..\dist\installer-lm\VYONIX_License_Manager_Setup.exe

#ifndef AppVersion
  #error Informe /DAppVersion=...
#endif
#ifndef FileVersion
  #error Informe /DFileVersion=a.b.c.d
#endif

#define AppName "VYONIX License Manager"
#define AppExe "VYONIX_License_Manager.exe"

[Setup]
AppId={{5B7A1C3E-9D24-4E61-8F0B-2C7D9E1A4B66}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=VYONIX
VersionInfoVersion={#FileVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription=Instalador do {#AppName}
DefaultDirName={commonpf64}\VYONIX\License Manager
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
PrivilegesRequired=admin
OutputDir=..\dist\installer-lm
OutputBaseFilename=VYONIX_License_Manager_Setup
SetupIconFile=..\build\vyonix.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
SetupLogging=yes

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "LicenseManager_installed.flag"; DestDir: "{app}"; DestName: "installed.flag"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Messages]
ptbr.FinishedLabel=O VYONIX License Manager foi instalado. Os dados (clientes, licenças e chaves cifradas) ficam em %APPDATA%\VYONIX\License Manager e NÃO são removidos na desinstalação. Faça backups protegidos regularmente.
