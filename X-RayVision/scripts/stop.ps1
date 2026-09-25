# 開發用：停止 start.ps1 啟動的平台服務。先送中斷訊號正常關閉，逾時才強制結束整個行程樹。
param([int]$TimeoutSec = 30)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$PidFile = Join-Path $Root "temp\dev-service\service.json"

if (-not (Test-Path $PidFile)) { Write-Host "服務未在執行（沒有 $PidFile）"; exit 0 }
$info = Get-Content $PidFile -Raw | ConvertFrom-Json
$proc = Get-Process -Id $info.pid -ErrorAction SilentlyContinue
if (-not $proc) { Remove-Item $PidFile; Write-Host "服務未在執行（PID $($info.pid) 已結束）"; exit 0 }

Write-Host "正在停止服務 (PID $($info.pid))…"
& $Python (Join-Path $PSScriptRoot "console_signal.py") $info.pid
if ($LASTEXITCODE -eq 0 -and $proc.WaitForExit($TimeoutSec * 1000)) {
    Write-Host "服務已停止。"
} else {
    Write-Host "未在 $TimeoutSec 秒內正常結束，強制結束行程樹。"
    taskkill /PID $info.pid /T /F | Out-Null
}
Remove-Item $PidFile -ErrorAction SilentlyContinue
exit 0
