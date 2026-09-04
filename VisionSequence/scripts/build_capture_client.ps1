# VisionSequence 擷取端打包（Windows PowerShell 5.1）
#   .\scripts\build_capture_client.ps1                第一次：建 .venv-capture、安裝依賴；之後：PyInstaller → zip 到 data\downloads\
#   .\scripts\build_capture_client.ps1 -WithBasler    一併安裝 pypylon（Basler）；-WithIds 安裝 ids_peak／ids_peak_ipl（建置機需先裝 IDS peak）；-WithUeye 安裝 pyueye
#   .\scripts\build_capture_client.ps1 -SkipInstall   不重裝依賴（只重新打包）
#   .\scripts\build_capture_client.ps1 -Clean         先清掉 build\capture 與 .venv-capture
# 產物：data\downloads\VisionSequenceCapture-<版本>-win64.zip 與 manifest.json（網頁「影像來源」→「下載擷取端」讀它）。
# 從 Bash 工具執行請包成：powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_capture_client.ps1
param(
    [switch]$WithBasler,
    [switch]$WithIds,
    [switch]$WithUeye,
    [switch]$SkipInstall,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venv = Join-Path $root ".venv-capture"
$py = Join-Path $venv "Scripts\python.exe"
$buildDir = Join-Path $root "build\capture"
$outDir = Join-Path $root "data\downloads"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

if ($Clean) {
    foreach ($p in @($buildDir, $venv)) { if (Test-Path $p) { Remove-Item -Recurse -Force $p } }
}
if (-not (Test-Path $py)) {
    Write-Host "建立 .venv-capture（與伺服端 .venv 分開：opencv-python 與 opencv-python-headless 同名互蓋）"
    & py -3.12 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "建立 .venv-capture 失敗（需要 Python 3.12：py -3.12）" }
}
if (-not $SkipInstall) {
    & $py -m pip install --upgrade pip
    & $py -m pip install -r (Join-Path $root "vscapture\requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "安裝依賴失敗" }
    if ($WithBasler) { & $py -m pip install "pypylon>=4.0"; if ($LASTEXITCODE -ne 0) { throw "安裝 pypylon 失敗" } }
    if ($WithIds) { & $py -m pip install "ids_peak>=1.10" "ids_peak_ipl>=1.10"; if ($LASTEXITCODE -ne 0) { throw "安裝 ids_peak 失敗" } }
    if ($WithUeye) { & $py -m pip install pyueye; if ($LASTEXITCODE -ne 0) { throw "安裝 pyueye 失敗" } }
}

$version = (& $py -c "import vscapture; print(vscapture.__version__)").Trim()
if (-not $version) { throw "讀不到 vscapture.__version__" }
Write-Host "擷取端版本 $version"
& $py -m vscapture --version
if ($LASTEXITCODE -ne 0) { throw "原始碼 smoke 失敗（python -m vscapture --version）" }

$sdks = (& $py -c "import importlib.util as u; print(','.join(m for m in ('pypylon','ids_peak','pyueye','pygrabber') if u.find_spec(m)))").Trim()
if ($sdks) { Write-Host "內含相機 SDK：$sdks" } else { Write-Host "內含相機 SDK：無（只有網路攝影機與模擬相機；要含 Basler／IDS 請加 -WithBasler／-WithIds）" }

$distRoot = Join-Path $buildDir "dist"
$work = Join-Path $buildDir "work"
& $py -m PyInstaller --noconfirm --clean --distpath $distRoot --workpath $work (Join-Path $root "scripts\capture_client.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失敗" }
$dist = Join-Path $distRoot "VisionSequenceCapture"
if (-not (Test-Path (Join-Path $dist "VisionSequenceCapture.exe"))) { throw "找不到建置產物：$dist" }

& (Join-Path $dist "VisionSequenceCapture-console.exe") --version
if ($LASTEXITCODE -ne 0) { throw "打包後的程式無法啟動" }

& $py (Join-Path $root "scripts\package_capture_client.py") --dist $dist --out $outDir --version $version "--sdks=$sdks"
if ($LASTEXITCODE -ne 0) { throw "打包 zip 失敗" }
Write-Host "完成：$outDir\VisionSequenceCapture-$version-win64.zip（伺服端執行中時，網頁「影像來源」→「下載擷取端」即可取得）"
