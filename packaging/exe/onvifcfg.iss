; Inno Setup 6 script for onvifcfg.
;
; Compiles the PyInstaller-bundled onvifcfg.exe into a single-file
; Windows installer that:
;   - installs the binary to %ProgramFiles%\onvifcfg\
;   - optionally appends that folder to the system PATH
;   - adds Start Menu shortcuts (terminal help, web UI)
;   - registers an uninstaller visible in Add/Remove Programs
;
; Invoked by packaging\exe\build-exe.ps1.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{9A3B7F2E-4E1C-4D1B-9C8F-3E5A2B7F1D01}
AppName=onvifcfg
AppVersion={#AppVersion}
AppPublisher=ITCom Solutions
AppPublisherURL=https://itcom-solutions.com
AppSupportURL=https://github.com/andrewhack/odm/issues
DefaultDirName={autopf}\onvifcfg
DefaultGroupName=onvifcfg
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=onvifcfg-setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
PrivilegesRequired=admin
ChangesEnvironment=yes
UninstallDisplayIcon={app}\onvifcfg.exe
VersionInfoCompany=onvifcfg contributors
VersionInfoProductName=onvifcfg
VersionInfoProductVersion={#AppVersion}
VersionInfoVersion={#AppVersion}

[Tasks]
Name: "addtopath"; Description: "Add onvifcfg to the system PATH"; GroupDescription: "Options:"

[Files]
Source: "..\..\dist\onvifcfg.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\onvifcfg\onvifcfg web UI"; Filename: "{app}\onvifcfg.exe"; Parameters: "serve"; WorkingDir: "{app}"; IconFilename: "{app}\onvifcfg.exe"
Name: "{autoprograms}\onvifcfg\onvifcfg command help"; Filename: "cmd.exe"; Parameters: "/k ""{app}\onvifcfg.exe"" --help"; WorkingDir: "{app}"

[Run]
Filename: "{app}\onvifcfg.exe"; Parameters: "--help"; Description: "Show onvifcfg command help"; Flags: nowait postinstall skipifsilent runascurrentuser

[Code]
const
  EnvironmentKey = 'System\CurrentControlSet\Control\Session Manager\Environment';

procedure EnvAddPath(Path: string);
var
  Paths: string;
begin
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', Paths) then
    Paths := '';
  if Pos(';' + UpperCase(Path) + ';', ';' + UpperCase(Paths) + ';') > 0 then
    Exit;
  if Length(Paths) > 0 then
    Paths := Paths + ';' + Path
  else
    Paths := Path;
  RegWriteExpandStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', Paths);
end;

procedure EnvRemovePath(Path: string);
var
  Paths: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', Paths) then
    Exit;
  P := Pos(';' + UpperCase(Path) + ';', ';' + UpperCase(Paths) + ';');
  if P = 0 then
    Exit;
  Delete(Paths, P - 1, Length(Path) + 1);
  RegWriteExpandStringValue(HKEY_LOCAL_MACHINE, EnvironmentKey, 'Path', Paths);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and IsTaskSelected('addtopath') then
    EnvAddPath(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    EnvRemovePath(ExpandConstant('{app}'));
end;
