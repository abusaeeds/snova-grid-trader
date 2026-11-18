; Inno Setup script - builds one SNovaGridTrader_Setup.exe installer.
; 1) Run build_tools\build_exe.bat first.
; 2) Open this file in Inno Setup Compiler and press Compile (Ctrl+F9).

#define AppName "SNova Grid Trader"
#define AppVersion "1.0.0"
#define AppPublisher "YOUR NAME"
#define AppExe "SNovaGridTrader.exe"

[Setup]
AppId={{6E4C1C0B-8F3A-4E7D-9A51-5B1F0D7C2A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\Output
OutputBaseFilename=SNovaGridTrader_Setup
SetupIconFile=..\assets\logo.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\SNovaGridTrader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
