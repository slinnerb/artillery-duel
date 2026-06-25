; Inno Setup script for Artillery Duel.
;
; The game installs PER-USER (into %LocalAppData%) on purpose: the in-game
; "Check for Updates" feature swaps the .exe in place, which needs a writable
; folder. Program Files would require admin on every update. Tailscale, which
; DOES need admin, is installed by a helper script that elevates on its own.

#define MyAppName "Artillery Duel"
#define MyAppExeName "ArtilleryDuel.exe"
#define MyAppVersion "1.0.5"
#define MyAppPublisher "slinnerb"
#define MyAppURL "https://github.com/slinnerb/artillery-duel"

[Setup]
AppId={{8F2A1C7E-3B4D-4E5F-9A6B-1C2D3E4F5A6B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\ArtilleryDuel
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=ArtilleryDuel-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "installtailscale"; Description: "Install Tailscale (lets you play over the internet)"; GroupDescription: "Networking:"; Check: TailscaleMissing

[Files]
Source: "dist\ArtilleryDuel.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "install_tailscale.ps1"; DestDir: "{tmp}"; Flags: dontcopy

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function TailscaleInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf}\Tailscale\tailscale.exe')) or
            FileExists(ExpandConstant('{commonpf32}\Tailscale\tailscale.exe'));
end;

function TailscaleMissing(): Boolean;
begin
  Result := not TailscaleInstalled();
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  ScriptPath: String;
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('installtailscale') and TailscaleMissing() then
    begin
      ExtractTemporaryFile('install_tailscale.ps1');
      ScriptPath := ExpandConstant('{tmp}\install_tailscale.ps1');
      Exec('powershell.exe',
           '-NoProfile -ExecutionPolicy Bypass -File "' + ScriptPath + '"',
           '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
    end;
  end;
end;
