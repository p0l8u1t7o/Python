# VisionSequence 開發堆疊一鍵啟動（Windows PowerShell 5.1）
#   .\scripts\dev.ps1            啟動後端（uvicorn + TCP）與前端 dev server
#   .\scripts\dev.ps1 -Setup     第一次：建 .venv、安裝套件、migrate、seed 示範資料、npm install
#   .\scripts\dev.ps1 -Lan       前端綁 0.0.0.0（區網其他裝置可連）
#   .\scripts\stop.ps1           停止
param(
    [switch]$Setup,
    [switch]$Lan
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($Setup) {
    if (-not (Test-Path ".venv")) { py -3.12 -m venv .venv }
    & ".venv\Scripts\python.exe" -m pip install --upgrade pip
    & ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    # 外掛依賴：資料夾型外掛（plugins/<name>/requirements.txt）與單檔外掛（plugins/<name>.requirements.txt）
    Get-ChildItem "plugins" -Recurse -Depth 1 -Filter "*requirements.txt" -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "安裝外掛依賴：$($_.FullName)"
        & ".venv\Scripts\python.exe" -m pip install -r $_.FullName
    }
    if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
    & ".venv\Scripts\python.exe" manage.py migrate
    & ".venv\Scripts\python.exe" manage.py seed_demo
    Push-Location frontend
    npm install --no-audit --no-fund
    Pop-Location
}

& ".venv\Scripts\python.exe" manage.py migrate --noinput | Out-Null

$backend = Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "manage.py serve --host 0.0.0.0 --port 8000" -WorkingDirectory $root -PassThru -WindowStyle Minimized
$env:VITE_DEV_HOST = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
$frontend = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev" -WorkingDirectory "$root\frontend" -PassThru -WindowStyle Minimized

"$($backend.Id) $($frontend.Id)" | Set-Content -Path "$root\logs\dev.pids" -Encoding ascii
Write-Host "後端 API   : http://127.0.0.1:8000/api/docs"
Write-Host "TCP 介面   : 127.0.0.1:9000  （例：echo RUN 1 | ncat 127.0.0.1 9000）"
Write-Host "前端       : http://127.0.0.1:5173/"
if ($Lan) {
    Write-Host "區網：若連不到，先確認 Wi-Fi 設定檔為「私人」，再開防火牆："
    Write-Host '  New-NetFirewallRule -DisplayName "VisionSequence" -Direction Inbound -Protocol TCP -LocalPort 5173,8000,9000 -Action Allow'
}
Write-Host "停止：.\scripts\stop.ps1"
