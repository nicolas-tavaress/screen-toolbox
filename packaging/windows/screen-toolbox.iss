; Instalador do Screen Toolbox para Windows (Inno Setup 6).
; Compilar depois do build.sh:  iscc /DAppVersion=0.1.0 packaging\windows\screen-toolbox.iss

#define AppName "Screen Toolbox"
#define AppExe "screen-toolbox.exe"
#define AppId "io.github.nicolas.ScreenToolbox"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define Build "..\..\build\windows"

[Setup]
AppId={{7C0F5B2E-3A47-4E36-9C1D-5E2B8F4A6D19}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Nicolas Tavares
AppPublisherURL=https://github.com/nicolas-tavaress/screen-toolbox
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; instalação por usuário, sem pedir permissão de administrador
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#Build}
OutputBaseFilename=ScreenToolbox-{#AppVersion}-setup
SetupIconFile={#Build}\icons\{#AppId}.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "autostart"; Description: "Iniciar com o Windows (fica na bandeja, com os atalhos Ctrl+Alt+S e Ctrl+Alt+R ativos)"
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; Flags: unchecked

[Files]
Source: "{#Build}\dist\screen-toolbox\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; atualizações: remove a versão anterior (bibliotecas e plugins mudam de nome entre versões)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName} - Capturar área"; Filename: "{app}\{#AppExe}"; Parameters: "--screenshot"; IconFilename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName} - Gravar tela"; Filename: "{app}\{#AppExe}"; Parameters: "--record"; IconFilename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --background"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir o {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Get-Process screen-toolbox,gdbus -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -like '{app}\*' } | Stop-Process -Force"""; Flags: runhidden waituntilterminated; RunOnceId: "StopApp"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
// o app roda em segundo plano (e o gdbus.exe que ele sobe também): encerra antes de
// copiar os arquivos, senão a atualização falha com arquivos em uso
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec('powershell.exe',
       '-NoProfile -ExecutionPolicy Bypass -Command "Get-Process screen-toolbox,gdbus -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ''' + ExpandConstant('{app}') + '\*'' } | Stop-Process -Force"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
