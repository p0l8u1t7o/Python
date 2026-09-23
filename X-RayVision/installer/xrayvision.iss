; X-RayVision 安裝程式 (Inno Setup 6)
; 由 tools/release/build_release.py 呼叫，不直接編譯：
;   ISCC /DAppVersion=0.1.0 /DStageDir=<stage> /DOutputDir=<輸出> /DLangDir=<含 ChineseTraditional.isl 的目錄> [/Sxrvsign=… /DSign] xrayvision.iss
;
; 安裝內容：程式目錄 {autopf}\X-RayVision (啟動器、服務包裝、產品版本)，資料目錄 {commonappdata}\X-RayVision
; 一台電腦只允許一份安裝；已安裝時由網頁「系統管理 > 軟體更新」進版，不以安裝程式覆蓋 (避免略過升版前快照)
; 解除安裝時移除程式與服務，保留資料目錄 (檢測紀錄、影像、授權、設定)

#ifndef AppVersion
  #error AppVersion is required (/DAppVersion=…)
#endif
#ifndef StageDir
  #error StageDir is required (/DStageDir=…)
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

#define AppName "X-RayVision"
#define AppIdGuid "6F3C2A51-8D4E-4B7A-9C1F-3E2D5A7B9C10"
#define ServiceId "XRayVision"
#define ServiceExe "XRayVisionService.exe"
#define Port "8600"

#ifdef LangDir
  #if FileExists(AddBackslash(LangDir) + "ChineseTraditional.isl")
    #define HasZh
  #endif
#endif

[Setup]
AppId={{{#AppIdGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupMutex=XRayVisionSetup,Global\XRayVisionSetup
CloseApplications=no
UninstallDisplayName={#AppName}
#ifdef Sign
SignTool=xrvsign
SignedUninstaller=yes
#endif

[Languages]
#ifdef HasZh
Name: "zh_TW"; MessagesFile: "{#LangDir}\ChineseTraditional.isl"
#endif
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
en.AlreadyInstalled=%1 version %2 is already installed on this computer.%n%nTo install a newer version, sign in as an administrator and use System > Software Update. To reinstall, uninstall the existing installation first; inspection data is retained.
en.InstallingService=Registering the Windows service...
en.StartingService=Starting the service and running the self-test...
en.ServiceNotReady=The service did not respond within the expected time. It may still be starting. If the page cannot be opened later, restart the computer or export a diagnostic package from the installation log folder:%n%n%1
en.OpenApp=Open {#AppName}
en.DataKept=The data directory has been retained:%n%1%n%nIt contains inspection records, images, the license and settings. Delete it manually only when the data is no longer needed.
#ifdef HasZh
zh_TW.AlreadyInstalled=本電腦已安裝 %1 版本 %2。%n%n如需安裝新版本，請以系統管理員登入後使用「系統管理 > 軟體更新」。如需重新安裝，請先解除安裝現有版本；檢測資料會保留。
zh_TW.InstallingService=正在註冊 Windows 服務…
zh_TW.StartingService=正在啟動服務並執行自我檢查…
zh_TW.ServiceNotReady=服務未在預期時間內回應，可能仍在啟動中。若稍後仍無法開啟網頁，請重新啟動電腦，或參考以下記錄檔目錄：%n%n%1
zh_TW.OpenApp=開啟 {#AppName}
zh_TW.DataKept=資料目錄已保留：%n%1%n%n內含檢測紀錄、影像、授權與設定。確定不再需要時，請自行刪除。
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Dirs]
Name: "{commonappdata}\{#AppName}"; Flags: uninsneveruninstall

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[INI]
Filename: "{app}\{#AppName}.url"; Section: "InternetShortcut"; Key: "URL"; String: "http://127.0.0.1:{#Port}/"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.url"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.url"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.url"; Description: "{cm:OpenApp}"; Flags: postinstall shellexec nowait skipifsilent

[UninstallRun]
Filename: "{app}\service\{#ServiceExe}"; Parameters: "stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopService"
Filename: "{app}\service\{#ServiceExe}"; Parameters: "uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveService"

[UninstallDelete]
; 進版後新增的版本目錄、快取與服務包裝記錄
Type: filesandordirs; Name: "{app}\versions"
Type: filesandordirs; Name: "{app}\launcher"
Type: filesandordirs; Name: "{app}\service"
Type: files; Name: "{app}\current.json"
Type: files; Name: "{app}\{#AppName}.url"
Type: dirifempty; Name: "{app}"

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppIdGuid}_is1';

function DataDir: String;
begin
  Result := ExpandConstant('{commonappdata}\{#AppName}');
end;

{ 一台電腦只允許一份安裝 }
function InitializeSetup: Boolean;
var
  Ver: String;
begin
  Result := True;
  if RegQueryStringValue(HKLM64, UninstallKey, 'DisplayVersion', Ver) or
     RegQueryStringValue(HKLM32, UninstallKey, 'DisplayVersion', Ver) then
  begin
    SuppressibleMsgBox(FmtMessage(CustomMessage('AlreadyInstalled'), ['{#AppName}', Ver]), mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

{ 啟動器設定：資料目錄與連接埠 (已存在時保留) }
procedure WriteLauncherConfig;
var
  Path, Dir: String;
begin
  Path := ExpandConstant('{app}\launcher\launcher.json');
  if FileExists(Path) then
    Exit;
  Dir := DataDir();
  StringChangeEx(Dir, '\', '\\', True);
  SaveStringToFile(Path, '{"data_dir": "' + Dir + '", "port": {#Port}}' + #13#10, False);
end;

procedure RunService(const Args: String);
var
  Code: Integer;
begin
  Exec(ExpandConstant('{app}\service\{#ServiceExe}'), Args, ExpandConstant('{app}\service'), SW_HIDE,
       ewWaitUntilTerminated, Code);
  Log(Format('service %s -> %d', [Args, Code]));
end;

{ 等待服務啟動並通過內建標準影像自我檢查 }
function WaitHealthy(TimeoutSec: Integer): Boolean;
var
  Http: Variant;
  I, Status: Integer;
  Body: String;
begin
  Result := False;
  for I := 1 to TimeoutSec div 2 do
  begin
    try
      Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
      Http.SetTimeouts(2000, 2000, 5000, 120000);
      Http.Open('GET', 'http://127.0.0.1:{#Port}/api/health?selftest=1', False);
      Http.Send('');
      Status := Http.Status;
      Body := Http.ResponseText;
      if (Status = 200) and (Pos('"selftest":"pass"', Body) > 0) then
      begin
        Result := True;
        Exit;
      end;
    except
    end;
    Sleep(2000);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    WriteLauncherConfig;
    WizardForm.StatusLabel.Caption := CustomMessage('InstallingService');
    RunService('install');
    WizardForm.StatusLabel.Caption := CustomMessage('StartingService');
    RunService('start');
    if not WaitHealthy(180) then
      SuppressibleMsgBox(FmtMessage(CustomMessage('ServiceNotReady'), [DataDir() + '\logs']), mbInformation, MB_OK, IDOK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DirExists(DataDir()) and not UninstallSilent then
    MsgBox(FmtMessage(CustomMessage('DataKept'), [DataDir()]), mbInformation, MB_OK);
end;
