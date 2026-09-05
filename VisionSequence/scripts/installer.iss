; VisionSequence - Inno Setup 6 script. Built by scripts\build_release.ps1:
;   ISCC.exe /DAppVersion=1.0.0 /DSourceDir=..\build\release\VisionSequence-1.0.0 /DOutDir=..\release scripts\installer.iss
;
; The installer copies the release tree to <dir>\app\<version> and runs scripts\install.ps1, which writes .env,
; migrates, creates the first administrator, configures HTTPS, the firewall and the services. Data, plugins, .env,
; certificates and DL packs live outside the version tree and survive uninstall unless the user chooses otherwise.
;
; Silent / mass rollout:
;   VisionSequence-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /DIR=C:\VisionSequence /STATIONID=ST01
;       /HOSTNAMES=vision-st01,192.168.1.10 /SUBNET=192.168.1.0/24 /HTTPS=internal /ADMINUSER=admin /ADMINPASSWORD=***
;   Other switches: /HTTPS=custom /CERT=x.pem /KEY=y.key | /HTTPS=none | /NOTCPAUTH=1 | /HTTPPORT=8000 | /HTTPSPORT=443
; Upgrades: running a newer setup on an installed station hands over to "vsctl update" (backup, migrate, switch, restart).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\build\release\VisionSequence-" + AppVersion
#endif
#ifndef OutDir
  #define OutDir "..\release"
#endif

[Setup]
AppId={{6F1C0C2A-7C7B-4E7E-9E1B-5D3C7A2B9F10}
AppName=VisionSequence
AppVersion={#AppVersion}
AppVerName=VisionSequence {#AppVersion}
AppPublisher=VisionSequence
DefaultDirName=C:\VisionSequence
DisableProgramGroupPage=yes
DirExistsWarning=no
OutputDir={#OutDir}
OutputBaseFilename=VisionSequence-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
SetupLogging=yes
UninstallDisplayName=VisionSequence
CloseApplications=no
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}\app\{#AppVersion}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\app\{#AppVersion}\scripts\install.ps1"" {code:InstallArgs}"; StatusMsg: "Configuring the station (database, accounts, HTTPS, services)..."; Flags: runhidden waituntilterminated
Filename: "{code:WebUrl}"; Description: "Open the web interface"; Flags: shellexec postinstall nowait skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\current\scripts\vsctl.ps1"" proxy uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "proxy"
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\current\scripts\vsctl.ps1"" service uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "service"
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\current\scripts\vsctl.ps1"" firewall -Remove"; Flags: runhidden waituntilterminated; RunOnceId: "firewall"

[UninstallDelete]
Type: files; Name: "{app}\vsctl.cmd"
Type: files; Name: "{app}\run-service.ps1"
Type: filesandordirs; Name: "{app}\app"

[Code]
var
  StationPage: TInputQueryWizardPage;
  HttpsPage: TInputOptionWizardPage;
  CertPage: TInputFileWizardPage;
  AdminPage: TInputQueryWizardPage;

function ParamOr(const Name, Default: String): String;
begin
  Result := ExpandConstant('{param:' + Name + '|' + Default + '}');
end;

function IsUpgrade: Boolean;
begin
  Result := FileExists(AddBackslash(WizardDirValue) + '.env');
end;

procedure InitializeWizard;
begin
  StationPage := CreateInputQueryPage(wpSelectDir, 'Station', 'How client PCs reach this station',
    'The host names and IP addresses go into the allowed-hosts list and the HTTPS certificate; the subnet limits who may connect through the firewall (leave empty for any).');
  StationPage.Add('Station id (shown in reports and the API):', False);
  StationPage.Add('Host names / IP addresses, comma separated:', False);
  StationPage.Add('Allowed subnet for the firewall (e.g. 192.168.1.0/24):', False);
  StationPage.Values[0] := ParamOr('STATIONID', GetComputerNameString);
  StationPage.Values[1] := ParamOr('HOSTNAMES', Lowercase(GetComputerNameString));
  StationPage.Values[2] := ParamOr('SUBNET', '');

  HttpsPage := CreateInputOptionPage(StationPage.ID, 'HTTPS', 'How browsers connect',
    'Recommended: the built-in certificate authority. Its root certificate (certs\root.crt) is imported once on every client PC.', True, False);
  HttpsPage.Add('Built-in certificate authority (self-signed, port 443)');
  HttpsPage.Add('Certificate provided by your IT department (next page asks for the files)');
  HttpsPage.Add('No HTTPS - plain HTTP on port 8000 (trusted LAN only)');
  if ParamOr('HTTPS', 'internal') = 'custom' then HttpsPage.SelectedValueIndex := 1
  else if ParamOr('HTTPS', 'internal') = 'none' then HttpsPage.SelectedValueIndex := 2
  else HttpsPage.SelectedValueIndex := 0;

  CertPage := CreateInputFilePage(HttpsPage.ID, 'Certificate', 'Certificate files',
    'PEM files issued for the host names entered before.');
  CertPage.Add('Certificate (full chain, .pem/.crt):', 'Certificate files|*.pem;*.crt;*.cer|All files|*.*', '.pem');
  CertPage.Add('Private key (.key/.pem):', 'Key files|*.key;*.pem|All files|*.*', '.key');
  CertPage.Values[0] := ParamOr('CERT', '');
  CertPage.Values[1] := ParamOr('KEY', '');

  AdminPage := CreateInputQueryPage(CertPage.ID, 'Administrator', 'First administrator account',
    'Created before any port is opened. Engineers and operators are added later on the Users page.');
  AdminPage.Add('User name:', False);
  AdminPage.Add('Password:', True);
  AdminPage.Add('Password (again):', True);
  AdminPage.Values[0] := ParamOr('ADMINUSER', 'admin');
  AdminPage.Values[1] := ParamOr('ADMINPASSWORD', '');
  AdminPage.Values[2] := ParamOr('ADMINPASSWORD', '');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if IsUpgrade and ((PageID = StationPage.ID) or (PageID = HttpsPage.ID) or (PageID = CertPage.ID) or (PageID = AdminPage.ID)) then
    Result := True
  else if (PageID = CertPage.ID) and (HttpsPage.SelectedValueIndex <> 1) then
    Result := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = StationPage.ID then begin
    if Trim(StationPage.Values[0]) = '' then begin MsgBox('Please enter a station id.', mbError, MB_OK); Result := False; end
    else if Trim(StationPage.Values[1]) = '' then begin MsgBox('Please enter at least one host name or IP address.', mbError, MB_OK); Result := False; end;
  end else if CurPageID = CertPage.ID then begin
    if (not FileExists(CertPage.Values[0])) or (not FileExists(CertPage.Values[1])) then begin
      MsgBox('Please select both the certificate and the private key file.', mbError, MB_OK); Result := False;
    end;
  end else if CurPageID = AdminPage.ID then begin
    if Trim(AdminPage.Values[0]) = '' then begin MsgBox('Please enter a user name.', mbError, MB_OK); Result := False; end
    else if Length(AdminPage.Values[1]) < 8 then begin MsgBox('The password needs at least 8 characters.', mbError, MB_OK); Result := False; end
    else if AdminPage.Values[1] <> AdminPage.Values[2] then begin MsgBox('The passwords do not match.', mbError, MB_OK); Result := False; end;
  end;
end;

function HttpsMode: String;
begin
  case HttpsPage.SelectedValueIndex of
    1: Result := 'custom';
    2: Result := 'none';
  else
    Result := 'internal';
  end;
end;

function Quote(const S: String): String;
begin
  Result := '"' + S + '"';
end;

function InstallArgs(Param: String): String;
var
  PwFile: String;
begin
  Result := '-Root ' + Quote(ExpandConstant('{app}')) + ' -Unattended';
  if IsUpgrade then exit;
  Result := Result + ' -StationId ' + Quote(Trim(StationPage.Values[0]))
    + ' -HostNames ' + Quote(Trim(StationPage.Values[1]))
    + ' -Https ' + HttpsMode
    + ' -HttpPort ' + ParamOr('HTTPPORT', '8000')
    + ' -HttpsPort ' + ParamOr('HTTPSPORT', '443')
    + ' -AdminUser ' + Quote(Trim(AdminPage.Values[0]));
  if Trim(StationPage.Values[2]) <> '' then Result := Result + ' -Subnet ' + Quote(Trim(StationPage.Values[2]));
  if HttpsMode = 'custom' then Result := Result + ' -Cert ' + Quote(CertPage.Values[0]) + ' -Key ' + Quote(CertPage.Values[1]);
  if ParamOr('NOTCPAUTH', '') <> '' then Result := Result + ' -NoTcpAuth';
  if AdminPage.Values[1] <> '' then begin
    { the password never appears on a command line: it goes through a temp file install.ps1 deletes }
    PwFile := ExpandConstant('{tmp}\vs-admin.txt');
    SaveStringToFile(PwFile, AdminPage.Values[1], False);
    Result := Result + ' -AdminPasswordFile ' + Quote(PwFile);
  end;
end;

function WebUrl(Param: String): String;
var
  Hosts, First: String;
  P: Integer;
begin
  Hosts := Trim(StationPage.Values[1]);
  P := Pos(',', Hosts);
  if P > 0 then First := Trim(Copy(Hosts, 1, P - 1)) else First := Hosts;
  if First = '' then First := Lowercase(GetComputerNameString);
  if HttpsMode = 'none' then Result := 'http://' + First + ':' + ParamOr('HTTPPORT', '8000') + '/'
  else if ParamOr('HTTPSPORT', '443') = '443' then Result := 'https://' + First + '/'
  else Result := 'https://' + First + ':' + ParamOr('HTTPSPORT', '443') + '/';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  App: String;
begin
  App := ExpandConstant('{app}');
  if CurUninstallStep = usUninstall then begin
    { the junction must go before the version trees; RemoveDir deletes the link, never the target }
    RemoveDir(AddBackslash(App) + 'current');
  end else if CurUninstallStep = usPostUninstall then begin
    if (not UninstallSilent) and (MsgBox('Also delete the station data (database, images, backups), plugins, certificates and .env under ' + App + '?' + #13#10 + 'Choose No to keep them for a later reinstall.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then begin
      DelTree(AddBackslash(App) + 'data', True, True, True);
      DelTree(AddBackslash(App) + 'plugins', True, True, True);
      DelTree(AddBackslash(App) + 'packs', True, True, True);
      DelTree(AddBackslash(App) + 'certs', True, True, True);
      DeleteFile(AddBackslash(App) + '.env');
      DeleteFile(AddBackslash(App) + 'Caddyfile');
      DeleteFile(AddBackslash(App) + 'updates.log');
      RemoveDir(App);
    end;
  end;
end;
