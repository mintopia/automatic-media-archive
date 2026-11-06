; AMA's Windows installer (ADR 0017). Build it with tools/installer/build.py, which
; stages the files and passes AppVersion, PythonVersion, Wheel, StageDir and OutputDir.
;
; Per-user, no admin rights. It carries uv.exe and AMA's wheel; at install time
; install-env.cmd has uv install the pinned Python and AMA's locked dependencies into
; the app folder, so no GPL or LGPL code is redistributed (ADR 0012).
; Settings, database and logs live in %LOCALAPPDATA%\AMA, outside the app folder:
; an upgrade replaces the app folder only, and uninstall keeps that folder unless
; "also remove settings and history" is ticked (or /REMOVEDATA is passed).

#ifndef AppVersion
  #error Build with tools/installer/build.py
#endif

#define AppGuid "9BB3DCCE-2AEE-4B22-9FCC-A9216D85B372"
#define AppName "Automatic Media Archive"
; The value name ama.start_at_login uses, so the tray's "Start at login" agrees.
#define RunValueName "Automatic Media Archive"

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Jessica Smith
AppPublisherURL=https://github.com/mintopia/automatic-media-archive
AppSupportURL=https://git.mintopia.net/mintopia/automatic-media-archive/issues
PrivilegesRequired=lowest
DefaultDirName={autopf}\AMA
; A chosen folder could be %LOCALAPPDATA%\AMA, which uninstall must keep.
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; AMA is stopped in code: Restart Manager wouldn't see the Python in venv\ or python\.
CloseApplications=no
OutputDir={#OutputDir}
OutputBaseFilename=AMA-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\venv\Scripts\pythonw.exe
SetupLogging=yes
; With PrivilegesRequired=lowest the mitigation is inherited by everything Setup starts,
; which then can't follow the junctions uv makes (python\cpython-3.13-*, which venv\
; points through): install-env.cmd and the AMA started at the end would both fail.
; It guards elevated installers; this one runs, and starts AMA, as the user anyway.
RedirectionGuard=no

[Tasks]
Name: startatsignin; Description: "Start AMA when I sign in"

[InstallDelete]
; Rebuilt by install-env.cmd on every install, so an upgrade carries nothing stale.
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\python"
Type: files; Name: "{app}\ama-*.whl"

[Files]
Source: "{#StageDir}\uv.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\{#Wheel}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\install-env.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "{#StageDir}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: "{code:RunParameters}"; WorkingDir: "{app}"; Comment: "Rip, identify, encode and file your Discs"

[Run]
Filename: "{app}\venv\Scripts\pythonw.exe"; Parameters: "{code:RunParameters}"; WorkingDir: "{app}"; Description: "Start AMA now"; Flags: postinstall nowait skipifsilent; Check: EnvironmentReady

[UninstallDelete]
; venv\, python\ and install.log are made at install time, not copied.
Type: filesandordirs; Name: "{app}"

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

var
  EnvReady: Boolean;
  TasksPageSeen: Boolean;
  RemoveData: Boolean;

function AppDir(): String;
begin
  Result := ExpandConstant('{app}');
end;

{ The settings file AMA uses with no --config: $AMA_CONFIG, else %LOCALAPPDATA%\AMA\ama.toml
  (ama.config.default_config_path). }
function ConfigPath(Param: String): String;
begin
  Result := GetEnv('AMA_CONFIG');
  if Result = '' then
  begin
    Result := GetEnv('LOCALAPPDATA');
    if Result = '' then
      Result := ExpandConstant('{localappdata}');
    Result := AddBackslash(Result) + 'AMA\ama.toml';
  end;
end;

function RunParameters(Param: String): String;
begin
  Result := '-m ama run --config "' + ConfigPath('') + '"';
end;

{ Exactly what ama.start_at_login.command_line writes for this install. }
function RunCommand(): String;
begin
  Result := '"' + AppDir + '\venv\Scripts\pythonw.exe" -m ama run --config "' + ConfigPath('') + '"';
end;

function EnvironmentReady(): Boolean;
begin
  Result := EnvReady;
end;

{ The Run value starts this install (not another one, such as a development copy). }
function RunValueIsOurs(): Boolean;
var
  Value: String;
begin
  Result := RegQueryStringValue(HKCU, RunKey, '{#RunValueName}', Value)
    and (Pos(Lowercase(AddBackslash(AppDir)), Lowercase(Value)) > 0);
end;

function HasParam(Name: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Name) = 0 then
      Result := True;
end;

{ A command-line parameter starting with Prefix, such as /TASKS=. }
function HasParamPrefix(Prefix: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(Copy(ParamStr(I), 1, Length(Prefix)), Prefix) = 0 then
      Result := True;
end;

{ Ends every process running from the app folder: the tray, the server, the Python
  under it. Their files can't be replaced or removed while they run. }
procedure StopAMA();
var
  Folder, Script: String;
  ResultCode: Integer;
begin
  Folder := AddBackslash(AppDir);
  if not DirExists(Folder) then
    Exit;
  StringChangeEx(Folder, '''', '''''', True);
  Script := '$app = ''' + Folder + '''; Get-Process | Where-Object { $_.Path -and ' +
    '$_.Path.StartsWith($app, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { ' +
    'try { $_.Kill(); $_.WaitForExit(10000) | Out-Null } catch {} }';
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' + Script + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopAMA();
  Result := '';
end;

{ On an upgrade, offer what is in place now: the tray may have turned it off since.
  Tasks given on the command line win. }
procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpSelectTasks) and not TasksPageSeen
     and not HasParamPrefix('/TASKS=') and not HasParamPrefix('/MERGETASKS=') then
  begin
    TasksPageSeen := True;
    if RegKeyExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{' + '{#AppGuid}' + '}_is1') then
    begin
      if RunValueIsOurs() then
        WizardSelectTasks('startatsignin')
      else
        WizardSelectTasks('!startatsignin');
    end;
  end;
end;

procedure InstallEnvironment();
var
  App, LogFile, Params: String;
  ResultCode: Integer;
begin
  App := AppDir;
  LogFile := App + '\install.log';
  WizardForm.StatusLabel.Caption := 'Installing Python and AMA''s dependencies. This needs the internet and can take a few minutes...';
  WizardForm.ProgressGauge.Style := npbstMarquee;
  Params := '/S /C ""' + App + '\install-env.cmd" "{#PythonVersion}" "{#Wheel}" "' +
    ExpandConstant('{tmp}') + '\uv-cache" > "' + LogFile + '" 2>&1"';
  try
    EnvReady := Exec(ExpandConstant('{cmd}'), Params, App, SW_HIDE, ewWaitUntilTerminated, ResultCode)
      and (ResultCode = 0);
  finally
    WizardForm.ProgressGauge.Style := npbstNormal;
  end;
  if not EnvReady then
  begin
    Log('install-env.cmd failed with exit code ' + IntToStr(ResultCode) + '; see ' + App + '\install.log');
    SuppressibleMsgBox('AMA''s Python and dependencies couldn''t be installed. ' +
      'Check your internet connection and run this installer again.' + #13#10#13#10 +
      'Details are in ' + LogFile + '.', mbError, MB_OK, IDOK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then
    Exit;
  InstallEnvironment();
  if EnvReady and WizardIsTaskSelected('startatsignin') then
  begin
    if RegWriteStringValue(HKCU, RunKey, '{#RunValueName}', RunCommand()) then
      Log('Start at sign-in: ' + RunCommand())
    else
      Log('Start at sign-in: couldn''t write the Run value');
  end
  else if RunValueIsOurs() then
  begin
    RegDeleteValue(HKCU, RunKey, '{#RunValueName}');
    Log('Start at sign-in: off');
  end;
end;

{ A failed environment fails the install for scripts and CI (silent installs). }
function GetCustomSetupExitCode(): Integer;
begin
  if EnvReady then
    Result := 0
  else
    Result := 1;
end;

{ Uninstall: ask whether to remove settings and history too. Off by default. }
function AskRemoveData(): Boolean;
var
  Form: TSetupForm;
  Text: TNewStaticText;
  Box: TNewCheckBox;
  Button: TNewButton;
begin
  Form := CreateCustomForm(ScaleX(420), ScaleY(150), False, True);
  try
    Form.Caption := 'Uninstall {#AppName}';
    Text := TNewStaticText.Create(Form);
    Text.Parent := Form;
    Text.Left := ScaleX(12);
    Text.Top := ScaleY(12);
    Text.Width := Form.ClientWidth - ScaleX(24);
    Text.AutoSize := False;
    Text.WordWrap := True;
    Text.Height := ScaleY(48);
    Text.Caption := 'Your settings, history and logs stay in ' +
      ExtractFileDir(ConfigPath('')) + ', so a later install picks up where you left off. ' +
      'Your Libraries are never touched.';
    Box := TNewCheckBox.Create(Form);
    Box.Parent := Form;
    Box.Left := ScaleX(12);
    Box.Top := ScaleY(68);
    Box.Width := Form.ClientWidth - ScaleX(24);
    Box.Height := ScaleY(20);
    Box.Caption := 'Also remove settings and history';
    Box.Checked := False;
    Button := TNewButton.Create(Form);
    Button.Parent := Form;
    Button.Caption := 'Continue';
    Button.Width := Form.CalculateButtonWidth([Button.Caption]);
    Button.Height := ScaleY(23);
    Button.Left := Form.ClientWidth - Button.Width - ScaleX(12);
    Button.Top := Form.ClientHeight - ScaleY(23 + 12);
    Button.ModalResult := mrOk;
    Button.Default := True;
    Form.ActiveControl := Button;
    Form.ShowModal();
    Result := Box.Checked;
  finally
    Form.Free();
  end;
end;

{ `ama remove-data` deletes %LOCALAPPDATA%\AMA but keeps any Library inside it. }
procedure RemoveSettingsAndHistory();
var
  Python, Output: String;
  Text: AnsiString;
  ResultCode: Integer;
begin
  Python := AppDir + '\venv\Scripts\python.exe';
  Output := ExpandConstant('{tmp}') + '\remove-data.log';
  if FileExists(Python) and
     Exec(ExpandConstant('{cmd}'), '/S /C ""' + Python + '" -m ama remove-data --config "' +
       ConfigPath('') + '" > "' + Output + '" 2>&1"', AppDir, SW_HIDE, ewWaitUntilTerminated, ResultCode)
     and (ResultCode = 0) then
    Exit;
  Text := '';
  LoadStringFromFile(Output, Text);
  SuppressibleMsgBox('Your settings and history weren''t removed. ' + String(Text) + #13#10 +
    'You can delete ' + ExtractFileDir(ConfigPath('')) + ' yourself; check first that no Library is in it.',
    mbError, MB_OK, IDOK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  RemoveData := HasParam('/REMOVEDATA');
  if not UninstallSilent then
    RemoveData := AskRemoveData();
  StopAMA();
  if RemoveData then
    RemoveSettingsAndHistory();
  if RunValueIsOurs() then
    RegDeleteValue(HKCU, RunKey, '{#RunValueName}');
end;
