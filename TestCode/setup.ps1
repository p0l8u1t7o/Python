<#
  環境設定：clone 之後執行一次（Windows PowerShell 5.1 以上）。
    powershell -ExecutionPolicy Bypass -File setup.ps1            # 檢查 Node／瀏覽器／Git，跑快速檢查
    powershell -ExecutionPolicy Bypass -File setup.ps1 -All       # 另外建立 Python 環境、下載 ffmpeg
  選項：
    -Python        建立 .venv（Python 3.12）並安裝 requirements.txt
    -Ffmpeg        下載支援 NVENC 的 ffmpeg／ffprobe 到 MilitaryGradePC/tools/bin（錄影用，不進版控）
    -FfmpegZip <p> 改用本機已下載的 zip（內含 bin/ffmpeg.exe、bin/ffprobe.exe）
    -SkipCheck     不跑 node core/tools/check.mjs --quick
  需求說明見 REQUIREMENTS.md。
#>
param(
  [switch]$All,
  [switch]$Python,
  [switch]$Ffmpeg,
  [string]$FfmpegZip = '',
  [string]$FfmpegUrl = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip',
  [switch]$SkipCheck
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
if ($All) { $Python = $true; $Ffmpeg = $true }
$problems = @()

function Step($text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "  OK  $text" -ForegroundColor Green }
function Warn($text) { Write-Host "  !!  $text" -ForegroundColor Yellow }

# ---------------------------------------------------------------- Node.js 22+
Step 'Node.js'
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
  $problems += 'Node.js'
  Warn '找不到 node。安裝：winget install OpenJS.NodeJS.LTS（需要 22 以上），裝完重開終端機再執行本腳本。'
} else {
  $ver = (& node --version).Trim()
  $major = [int]($ver.TrimStart('v').Split('.')[0])
  if ($major -lt 22) { $problems += 'Node.js 版本'; Warn "node $ver 太舊，需要 22 以上。" } else { Ok "node $ver" }
}

# ---------------------------------------------------------------- 瀏覽器（ui-check、shots）
Step 'Chrome／Edge（瀏覽器檢查用）'
$browsers = @($env:CHROME_PATH,
  'C:\Program Files\Google\Chrome\Application\chrome.exe',
  'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
  'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
  'C:\Program Files\Microsoft\Edge\Application\msedge.exe') | Where-Object { $_ -and (Test-Path $_) }
if ($browsers) { Ok ($browsers | Select-Object -First 1) } else { $problems += '瀏覽器'; Warn '找不到 Chrome 或 Edge；請安裝，或設定環境變數 CHROME_PATH。' }

# ---------------------------------------------------------------- Git
Step 'Git'
if (Get-Command git -ErrorAction SilentlyContinue) { Ok ((& git --version).Trim()) } else { $problems += 'Git'; Warn '找不到 git。安裝：winget install Git.Git' }

# ---------------------------------------------------------------- Python（選用）
if ($Python) {
  Step 'Python 環境（.venv）'
  $py = $null
  if (Get-Command py -ErrorAction SilentlyContinue) {
    try { & py -3.12 -c "import sys" 2>$null; if ($LASTEXITCODE -eq 0) { $py = @('py', '-3.12') } } catch { }
  }
  if (-not $py -and (Get-Command python -ErrorAction SilentlyContinue)) { $py = @('python') }
  if (-not $py) {
    $problems += 'Python'
    Warn '找不到 Python 3.12。安裝：winget install Python.Python.3.12'
  } else {
    $venvPy = Join-Path $Root '.venv\Scripts\python.exe'
    if (-not (Test-Path $venvPy)) {
      $exe = $py[0]; $rest = @(); if ($py.Count -gt 1) { $rest = $py[1..($py.Count - 1)] }
      & $exe @rest -m venv .venv
      if ($LASTEXITCODE -ne 0) { throw '建立 .venv 失敗' }
    }
    & $venvPy -m pip install --upgrade pip --quiet
    & $venvPy -m pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) { $problems += 'pip install'; Warn 'pip 安裝失敗，請看上方訊息。' } else { Ok ((& $venvPy --version).Trim() + '，已安裝 requirements.txt') }
    if (-not (Test-Path 'C:\Windows\Fonts\msjh.ttc') -and -not $env:CIRCUIT_FONT) { Warn '找不到微軟正黑體 msjh.ttc；電路圖需要中文字型，可設 CIRCUIT_FONT。' }
  }
}

# ---------------------------------------------------------------- ffmpeg（選用，錄影）
if ($Ffmpeg -or $FfmpegZip) {
  Step 'ffmpeg／ffprobe（錄影輸出）'
  $bin = Join-Path $Root 'MilitaryGradePC\tools\bin'
  if ((Test-Path (Join-Path $bin 'ffmpeg.exe')) -and (Test-Path (Join-Path $bin 'ffprobe.exe'))) {
    Ok "已存在：$bin"
  } else {
    New-Item -ItemType Directory -Force $bin | Out-Null
    $tmp = Join-Path $Root 'TEMP\ffmpeg-download'
    New-Item -ItemType Directory -Force $tmp | Out-Null
    $zip = $FfmpegZip
    if (-not $zip) {
      $zip = Join-Path $tmp 'ffmpeg.zip'
      Write-Host "  下載 $FfmpegUrl"
      [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
      Invoke-WebRequest -Uri $FfmpegUrl -OutFile $zip -UseBasicParsing
    }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $found = Get-ChildItem -Path $tmp -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
    if (-not $found) { throw "zip 內找不到 ffmpeg.exe：$zip" }
    Copy-Item (Join-Path $found.DirectoryName 'ffmpeg.exe') $bin -Force
    Copy-Item (Join-Path $found.DirectoryName 'ffprobe.exe') $bin -Force
    $license = Get-ChildItem -Path $tmp -Recurse -Filter 'LICENSE*' | Select-Object -First 1
    if ($license) { Copy-Item $license.FullName (Join-Path $bin 'LICENSE.txt') -Force }
    Remove-Item $tmp -Recurse -Force
    Ok "已放到 $bin"
  }
  $encoders = & (Join-Path $bin 'ffmpeg.exe') -hide_banner -encoders 2>$null | Out-String
  if ($encoders -match 'h264_nvenc') { Ok '支援 h264_nvenc（實際能否使用依顯示卡而定，不可用時錄影程式自動改用 libx264）' } else { Warn '這個 ffmpeg 不含 h264_nvenc，錄影會用 libx264（較慢）。' }
}

# ---------------------------------------------------------------- 快速檢查
if (-not $SkipCheck -and -not ($problems -contains 'Node.js') -and -not ($problems -contains 'Node.js 版本')) {
  Step '快速檢查（node core/tools/check.mjs --quick，約數分鐘）'
  & node core/tools/check.mjs --quick
  if ($LASTEXITCODE -ne 0) { $problems += '快速檢查' }
}

Write-Host ''
if ($problems.Count) {
  Write-Host ("未完成：" + ($problems -join '、')) -ForegroundColor Yellow
  exit 1
}
Write-Host '環境就緒。本機展示：node core/tools/serve.mjs → http://127.0.0.1:8770/' -ForegroundColor Green
