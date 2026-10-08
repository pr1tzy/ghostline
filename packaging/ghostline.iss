; Inno Setup script for GhostlineSetup.exe. Built by packaging/build.py (ISCC /DAppVersion=x.y.z).
; Installs for the current Windows user only (no admin prompt) into %LOCALAPPDATA%\Programs\Ghostline.
; Laps and settings live in %LOCALAPPDATA%\Ghostline, so updates and reinstalls never touch them.
; Nothing is added to Windows startup.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{880d2d88-cc66-44f6-8047-920698967a85}
AppName=Ghostline
AppVersion={#AppVersion}
AppVerName=Ghostline {#AppVersion}
AppPublisher=Ghostline
AppPublisherURL=https://github.com/pr1tzy/ghostline
AppSupportURL=https://github.com/pr1tzy/ghostline/issues
AppUpdatesURL=https://github.com/pr1tzy/ghostline/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Ghostline
VersionInfoDescription=Ghostline installer
DefaultDirName={localappdata}\Programs\Ghostline
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=GhostlineSetup
SetupIconFile=ghostline.ico
UninstallDisplayIcon={app}\Ghostline.exe
UninstallDisplayName=Ghostline
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "withgame"; Description: "Start Ghostline when I start a session in Assetto Corsa, and close it a few minutes after the game. (Nothing is added to Windows startup. You can change this later in the tray menu.)"; GroupDescription: "When should Ghostline run?"
Name: "updates"; Description: "Tell me when a new version of Ghostline is out (asks GitHub once a day; nothing else is sent)"; GroupDescription: "Updates:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\Ghostline\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; files from an older version that this one no longer ships
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Ghostline"; Filename: "{app}\Ghostline.exe"; Comment: "Sim racing telemetry for Assetto Corsa"
Name: "{autodesktop}\Ghostline"; Filename: "{app}\Ghostline.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Ghostline.exe"; Parameters: "--set launch_with_game=1"; Tasks: withgame; Flags: runhidden waituntilterminated
Filename: "{app}\Ghostline.exe"; Parameters: "--set launch_with_game=0"; Tasks: not withgame; Flags: runhidden waituntilterminated
Filename: "{app}\Ghostline.exe"; Parameters: "--set check_updates=1"; Tasks: updates; Flags: runhidden waituntilterminated
Filename: "{app}\Ghostline.exe"; Parameters: "--set check_updates=0"; Tasks: not updates; Flags: runhidden waituntilterminated
Filename: "{app}\Ghostline.exe"; Description: "Open Ghostline now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM Ghostline.exe /F"; Flags: runhidden; RunOnceId: "StopGhostline"
Filename: "{app}\Ghostline.exe"; Parameters: "--uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveGameApps"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{localappdata}\Ghostline');
    if DirExists(Data) and (MsgBox('Also delete your laps and settings?' + #13#10 + #13#10 + Data + #13#10 + #13#10 +
        'Choose No to keep them for a later reinstall.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(Data, True, True, True);
  end;
end;
