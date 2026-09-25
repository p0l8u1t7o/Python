# 開發用：顯示 start.ps1 啟動的平台服務狀態
$Root = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $Root "temp\dev-service\service.json"
if (-not (Test-Path $PidFile)) { Write-Host "服務未在執行"; exit 1 }
$info = Get-Content $PidFile -Raw | ConvertFrom-Json
if (-not (Get-Process -Id $info.pid -ErrorAction SilentlyContinue)) { Write-Host "服務未在執行（PID $($info.pid) 已結束）"; exit 1 }
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:$($info.port)/api/health" -TimeoutSec 3
    Write-Host "執行中 (PID $($info.pid))：http://127.0.0.1:$($info.port)/  版本 $($h.version)"
} catch {
    Write-Host "行程存在 (PID $($info.pid))，但健康檢查沒有回應"
}
Write-Host "資料目錄：$($info.data)  啟動時間：$($info.started)"
exit 0
