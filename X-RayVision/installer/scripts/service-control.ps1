# 安裝版：啟動、停止、重新啟動或查詢 X-RayVision Windows 服務。
# 由同目錄的 start-service.cmd／stop-service.cmd／restart-service.cmd／service-status.cmd 呼叫；
# 啟動、停止需要系統管理員權限，未提升時自動要求提升。
param(
    [ValidateSet("start", "stop", "restart", "status")][string]$Action = "status",
    [switch]$NoPause
)
$ServiceId = "XRayVision"
$Here = $PSScriptRoot
$Wrapper = Join-Path $Here "XRayVisionService.exe"
$Home_ = Split-Path -Parent $Here

# 顯示文字：依 Windows 顯示語言選擇繁體中文或英文
$zh = (Get-UICulture).Name -like "zh-*"
$M = if ($zh) { @{
    NeedAdmin   = "需要系統管理員權限，正在要求提升權限…"
    NotInstalled = "服務尚未註冊，請重新執行安裝程式。"
    Running     = "服務執行中。"
    Stopped     = "服務已停止。"
    Starting    = "正在啟動服務…"
    Stopping    = "正在停止服務（最長約 90 秒）…"
    Ready       = "服務已就緒："
    NotReady    = "服務已啟動，但網頁尚未回應；首次啟動或進版後可能需要 1～2 分鐘。"
    Failed      = "操作失敗，結束代碼："
    Logs        = "記錄檔目錄："
    Pause       = "按任意鍵關閉視窗…"
} } else { @{
    NeedAdmin   = "Administrator privileges are required. Requesting elevation..."
    NotInstalled = "The service is not registered. Run the setup program again."
    Running     = "The service is running."
    Stopped     = "The service is stopped."
    Starting    = "Starting the service..."
    Stopping    = "Stopping the service (up to about 90 seconds)..."
    Ready       = "The service is ready: "
    NotReady    = "The service has started, but the web page is not responding yet. The first start or a start after an update can take 1 to 2 minutes."
    Failed      = "The operation failed. Exit code: "
    Logs        = "Log directory: "
    Pause       = "Press any key to close this window..."
} }

function Finish([int]$code) {
    if (-not $NoPause) { Write-Host ""; Write-Host $M.Pause; [void][Console]::ReadKey($true) }
    exit $code
}

function Get-Port {
    $cfg = Join-Path $Home_ "launcher\launcher.json"
    try { $p = (Get-Content $cfg -Raw | ConvertFrom-Json).port; if ($p) { return $p } } catch {}
    return 8600
}

function Wait-Ready([int]$timeoutSec) {
    $url = "http://127.0.0.1:$(Get-Port)/"
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri ($url + "api/health") -UseBasicParsing -TimeoutSec 3 | Out-Null
            Write-Host ($M.Ready + $url); return $true
        } catch { Start-Sleep -Seconds 2 }
    }
    Write-Host $M.NotReady
    Write-Host ($M.Logs + (Join-Path $env:ProgramData "X-RayVision\logs"))
    return $false
}

$svc = Get-Service -Name $ServiceId -ErrorAction SilentlyContinue
if (-not $svc) { Write-Host $M.NotInstalled; Finish 3 }

if ($Action -eq "status") {
    if ($svc.Status -eq "Running") { Write-Host $M.Running; [void](Wait-Ready 5) } else { Write-Host $M.Stopped }
    Finish 0
}

# 啟動、停止需要系統管理員權限
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host $M.NeedAdmin
    $args_ = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Action $Action"
    try { Start-Process -FilePath "powershell.exe" -ArgumentList $args_ -Verb RunAs } catch { Write-Host ($M.Failed + "UAC") ; Finish 5 }
    exit 0
}

if ($Action -in @("stop", "restart") -and $svc.Status -ne "Stopped") {
    Write-Host $M.Stopping
    & $Wrapper stop | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host ($M.Failed + $LASTEXITCODE); Finish $LASTEXITCODE }
    try { $svc.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(120)) } catch { Write-Host ($M.Failed + "timeout"); Finish 6 }
}
if ($Action -eq "stop") { Write-Host $M.Stopped; Finish 0 }

$svc.Refresh()
if ($svc.Status -ne "Running") {
    Write-Host $M.Starting
    & $Wrapper start | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host ($M.Failed + $LASTEXITCODE); Finish $LASTEXITCODE }
} else {
    Write-Host $M.Running
}
if (Wait-Ready 180) { Finish 0 } else { Finish 4 }
