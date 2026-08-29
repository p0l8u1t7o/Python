# 啟動後端 (Django, 8001) 與前端 (Vite, 5174)。
#   .\start.ps1           背景啟動，PID 記錄於 .run/，用 .\stop.ps1 停止
#   .\start.ps1 -Attach   前景模式：視窗保持開啟，按 Ctrl+C（或關閉視窗）即自動停止兩個服務
param([switch]$Attach)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'
$runDir = Join-Path $root '.run'
New-Item -ItemType Directory -Force $runDir | Out-Null

function Test-Alive($pidFile) {
    if (-not (Test-Path $pidFile)) { return $false }
    $procId = [int](Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    return [bool](Get-Process -Id $procId -ErrorAction SilentlyContinue)
}

# 已在執行 → 提示；PID 檔過期（程序已不在）→ 自動清掉
$bePid = Join-Path $runDir 'backend.pid'; $fePid = Join-Path $runDir 'frontend.pid'
if ((Test-Alive $bePid) -or (Test-Alive $fePid)) {
    Write-Host '服務已在執行中，請先執行 .\stop.ps1' -ForegroundColor Yellow
    exit 1
}
Remove-Item $bePid, $fePid -Force -ErrorAction SilentlyContinue
& (Join-Path $root 'stop.ps1') -Quiet   # 保險：釋放殘留的 8001/5174

# 載入專案根目錄 .env（例如 ANTHROPIC_API_KEY）；已存在的環境變數優先
$envFile = Join-Path $root '.env'
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile -Encoding UTF8) {
        $line = $line.Trim()
        if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) { continue }
        $k, $v = $line.Split('=', 2); $k = $k.Trim(); $v = $v.Trim().Trim('"').Trim("'")
        if (-not [Environment]::GetEnvironmentVariable($k)) { [Environment]::SetEnvironmentVariable($k, $v) }
    }
}

# CAD Studio 環境檢查（缺少只提示，不阻擋啟動）
if (-not (Test-Path (Join-Path $root 'cad\.venv\Scripts\python.exe')) -or -not (Test-Path (Join-Path $root 'cad\text-to-cad\skills\cad\scripts\export'))) {
    Write-Host 'CAD Studio 尚未安裝環境：請先執行 .\setup-cad.ps1（只需一次）' -ForegroundColor Yellow
}
if (-not $env:GEMINI_API_KEY -and -not $env:ANTHROPIC_API_KEY -and -not $env:CAD_STUDIO_API_KEY) {
    Write-Host 'CAD Studio 的 AI 產碼模式需要 API 金鑰：複製 .env.example 為 .env 並填入 GEMINI_API_KEY（程式模式不需要）' -ForegroundColor DarkGray
}

Write-Host '[1/3] 資料庫遷移與種子資料...' -ForegroundColor Cyan
& $py (Join-Path $root 'backend\manage.py') migrate -v 0
& $py (Join-Path $root 'backend\manage.py') load_seed | Out-Null

Write-Host '[2/3] 啟動 Django (http://127.0.0.1:8001, API 文件 /api/docs)' -ForegroundColor Cyan
$be = Start-Process -FilePath $py -ArgumentList 'manage.py', 'runserver', '8001', '--noreload' `
    -WorkingDirectory (Join-Path $root 'backend') -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $runDir 'backend.log') -RedirectStandardError (Join-Path $runDir 'backend.err.log')
$be.Id | Out-File $bePid -Encoding ascii

Write-Host '[3/3] 啟動 Vite (http://localhost:5174)' -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) {
    Push-Location (Join-Path $root 'frontend'); npm install; Pop-Location
}
$fe = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npx vite --port 5174 --strictPort' `
    -WorkingDirectory (Join-Path $root 'frontend') -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $runDir 'frontend.log') -RedirectStandardError (Join-Path $runDir 'frontend.err.log')
$fe.Id | Out-File $fePid -Encoding ascii

Start-Sleep -Seconds 3
Write-Host ''
Write-Host '已啟動：' -ForegroundColor Green
Write-Host '  Web        http://localhost:5174'
Write-Host '  CAD Studio http://localhost:5174/cad-studio'
Write-Host '  API 文件   http://127.0.0.1:8001/api/docs'
Write-Host '  Admin      http://127.0.0.1:8001/admin'
Write-Host "  日誌       $runDir"
Start-Process 'http://localhost:5174'

if ($Attach) {
    Write-Host ''
    Write-Host '前景模式：按 Ctrl+C 停止所有服務。' -ForegroundColor Yellow
    try {
        while ($true) {
            Start-Sleep -Seconds 1
            if (-not (Test-Alive $bePid) -and -not (Test-Alive $fePid)) { Write-Host '服務已結束。'; break }
        }
    } finally {
        & (Join-Path $root 'stop.ps1')
    }
} else {
    Write-Host '背景執行中；停止請執行 .\stop.ps1（或改用 .\start.ps1 -Attach 讓 Ctrl+C 直接停止）'
}
