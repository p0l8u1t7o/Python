# VisionSequence 開發堆疊一鍵啟動（Windows PowerShell 5.1）
#   .\scripts\dev.ps1            啟動後端（uvicorn + TCP）與前端 dev server
#   .\scripts\dev.ps1 -Setup     第一次：建 .venv、安裝套件、migrate、seed 示範資料、npm install
#   .\scripts\dev.ps1 -Lan       前端綁 0.0.0.0（區網其他裝置可連）
#   .\scripts\dev.ps1 -Setup -NoStart  只安裝，不啟動（setup_prereqs.ps1 用）
#   .\scripts\stop.ps1           停止
param(
    [switch]$Setup,
    [switch]$Lan,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
# 乾淨 clone 沒有 logs/（不進版控），dev.pids 與日誌都寫在這裡
New-Item -ItemType Directory -Force -Path "$root\logs" | Out-Null

# 外部程式失敗不會觸發 $ErrorActionPreference：每一步都要看離開碼，否則 migrate 失敗還會印「安裝完成」
function Assert-Ok([string]$what) {
    if ($LASTEXITCODE -ne 0) { throw "$what 失敗（離開碼 $LASTEXITCODE），請看上方訊息" }
}

if ($Setup) {
    if (-not (Test-Path ".venv")) { py -3.12 -m venv .venv; Assert-Ok "建立 .venv（需要 Python 3.12：py -3.12）" }
    & ".venv\Scripts\python.exe" -m pip install --upgrade pip
    Assert-Ok "升級 pip"
    # 已裝深度學習依賴（setup_dl.ps1）的機器：onnxruntime-gpu 與 requirements.txt 的 CPU 版 onnxruntime 同名互蓋，
    # 重跑 -Setup 時略過那一行，否則 GPU 版會被蓋壞（import onnxruntime 直接失敗）
    # 沒裝時 pip 會往 stderr 寫警告，Stop 模式下 PowerShell 5.1 會把它當成錯誤中止：暫時放寬、只看離開碼
    $savedPref = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & ".venv\Scripts\python.exe" -m pip show -q onnxruntime-gpu *> $null
    $hasGpuRuntime = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $savedPref
    if ($hasGpuRuntime) {
        $req = Join-Path $env:TEMP "vs-requirements-gpu.txt"
        # -Encoding UTF8 不能省：PowerShell 5.1 預設用系統字碼頁（Big5）讀，中文註解的位元組會把相鄰的套件行吞掉
        # （實測 18 個套件剩 9 個，Django／OpenCV／uvicorn 都不見）
        Get-Content -Encoding UTF8 requirements.txt | Where-Object { $_ -notmatch "^\s*onnxruntime==" } | Set-Content -Path $req -Encoding utf8
        Write-Host "偵測到 onnxruntime-gpu：略過 requirements.txt 的 CPU 版 onnxruntime"
        & ".venv\Scripts\python.exe" -m pip install -r $req
    } else {
        & ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    }
    Assert-Ok "安裝 requirements.txt"
    & ".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
    Assert-Ok "安裝 requirements-dev.txt"
    # 外掛依賴：資料夾型外掛（plugins/<name>/requirements.txt）與單檔外掛（plugins/<name>.requirements.txt）
    Get-ChildItem "plugins" -Recurse -Depth 1 -Filter "*requirements.txt" -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "安裝外掛依賴：$($_.FullName)"
        & ".venv\Scripts\python.exe" -m pip install -r $_.FullName
        Assert-Ok "安裝外掛依賴 $($_.Name)"
    }
    if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
    & ".venv\Scripts\python.exe" manage.py migrate
    Assert-Ok "資料庫 migrate"
    & ".venv\Scripts\python.exe" manage.py seed_demo
    Assert-Ok "建立示範資料（seed_demo）"
    Push-Location frontend
    npm install --no-audit --no-fund
    $npmExit = $LASTEXITCODE
    Pop-Location
    if ($npmExit -ne 0) { throw "前端 npm install 失敗（離開碼 $npmExit），請看上方訊息" }
}
if ($NoStart) { Write-Host "開發環境已安裝完成；啟動：.\scripts\dev.ps1"; return }

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
