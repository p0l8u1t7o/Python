# 開發用：在背景啟動平台服務 (python -m xrayvision serve)，等到健康檢查回應後結束。
# 產品安裝後請改用安裝目錄 service\ 內的 start-service.cmd (Windows 服務)。
param(
    [string]$Data = "",
    [int]$Port = 8600,
    [switch]$NoWatch,
    [switch]$SkipLicense,
    [int]$TimeoutSec = 60
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$RunDir = Join-Path $Root "temp\dev-service"
$PidFile = Join-Path $RunDir "service.json"
if (-not $Data) { $Data = Join-Path $Root "temp\dev-data" }

if (-not (Test-Path $Python)) { Write-Host "找不到 $Python，請先建立 .venv（見 README 開發環境）"; exit 1 }
New-Item -ItemType Directory -Force $RunDir | Out-Null

# 開發環境免手動啟用授權：沒有有效授權時以開發用私鑰簽發並匯入 (-SkipLicense 可略過，用來測試未授權畫面)
if (-not $SkipLicense) {
    & $Python -X utf8 (Join-Path $PSScriptRoot "dev_license.py") $Data
    if ($LASTEXITCODE -ne 0) { Write-Host "未取得開發授權，服務仍會啟動，但無法執行分析。" }
}

# 已在執行就不重複啟動
if (Test-Path $PidFile) {
    $info = Get-Content $PidFile -Raw | ConvertFrom-Json
    if (Get-Process -Id $info.pid -ErrorAction SilentlyContinue) {
        Write-Host "服務已在執行 (PID $($info.pid))：http://127.0.0.1:$($info.port)/"
        exit 0
    }
    Remove-Item $PidFile
}

$cmdLine = "`"$Python`" -X utf8 -m xrayvision serve --data `"$Data`" --port $Port"
if ($NoWatch) { $cmdLine += " --no-watch" }
$cmdLine += " 1>>`"$RunDir\stdout.log`" 2>>`"$RunDir\stderr.log`""
# 以 cmd 轉存輸出，並在隱藏的獨立主控台執行：關閉目前視窗不影響服務，stop.ps1 也能附加到該主控台送出中斷訊號正常關閉
$proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/d /s /c `"$cmdLine`"" -WorkingDirectory $Root -WindowStyle Hidden -PassThru
@{ pid = $proc.Id; port = $Port; data = $Data; started = (Get-Date -Format s) } | ConvertTo-Json | Set-Content $PidFile -Encoding utf8

$url = "http://127.0.0.1:$Port/api/health"
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) {
        Remove-Item $PidFile -ErrorAction SilentlyContinue
        Write-Host "服務啟動失敗 (結束代碼 $($proc.ExitCode))，錯誤輸出："
        Get-Content (Join-Path $RunDir "stderr.log") -Tail 20 -ErrorAction SilentlyContinue
        exit 1
    }
    try {
        Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 | Out-Null
        Write-Host "服務已啟動 (PID $($proc.Id))：http://127.0.0.1:$Port/"
        Write-Host "資料目錄：$Data"
        Write-Host "記錄：$RunDir"
        exit 0
    } catch { Start-Sleep -Milliseconds 500 }
}
Write-Host "服務在 $TimeoutSec 秒內沒有回應，仍在背景執行 (PID $($proc.Id))；請查看 $RunDir 內的記錄。"
exit 2
