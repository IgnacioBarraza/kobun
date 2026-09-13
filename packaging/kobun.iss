; Windows installer for Kobun, made with Inno Setup.
;
; Requires the executable already built at dist\kobun.exe:
;
;     python scripts/build_app.py
;     iscc packaging\kobun.iss
;
; It compiles on Windows: Inno Setup does not run on Linux. The output lands in
; dist\installer\.
;
; What it adds over the bare .exe: a Start menu shortcut, an association with
; PDF files, an uninstall entry in Control Panel, and a choice of install
; directory.

#define MyAppName "Kobun"
#define MyAppVersion "0.4.0-alpha.1"
#define MyAppPublisher "Ignacio Barraza"
#define MyAppExeName "kobun.exe"

[Setup]
; The AppId identifies the program across versions: changing it would make an
; update install alongside the previous one instead of replacing it.
AppId={{8F3A5C7E-2B94-4D61-9E48-1A7C6B0D3F52}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\dist\installer
OutputBaseFilename=kobun-{#MyAppVersion}-windows-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; No administrator privileges: it installs for the current user, so no UAC
; prompt shows up.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\kobun\shared\icons\kobun.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=..\LICENSE

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "pdfassoc"; Description: "Abrir archivos PDF con {#MyAppName}"; GroupDescription: "Asociaciones:"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Kobun offers itself as an option for PDFs without stealing the default
; association from whatever viewer the user already has: it registers under
; OpenWithProgids and in the context menu, not as the primary handler.
Root: HKCU; Subkey: "Software\Classes\Kobun.pdf"; ValueType: string; ValueName: ""; ValueData: "Documento PDF"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\Kobun.pdf\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\Kobun.pdf\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "Kobun.pdf"; ValueData: ""; Flags: uninsdeletevalue; Tasks: pdfassoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
