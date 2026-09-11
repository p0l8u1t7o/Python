<#
.SYNOPSIS
    建置機一鍵準備：用 winget 安裝缺少的軟體（Python 3.12、Node.js LTS、Git，可選 Inno Setup 6、Chrome），
    接著建立開發環境（.venv、套件、資料庫、示範資料、前端套件），可選再裝深度學習依賴。

.DESCRIPTION
    已經裝好的軟體只檢查版本、不重裝。每一步都印出做了什麼；-DryRun 只印不做。
    需要 Windows 10 1809 以上或 Windows 11（winget 隨「應用程式安裝程式」提供）。
    NVIDIA 顯示卡驅動不經 winget 安裝：-Dl 時只檢查 nvidia-smi，缺的話請到 nvidia.com 下載。

.EXAMPLE
    .\scripts\setup_prereqs.ps1                  # 必要軟體＋開發環境
    .\scripts\setup_prereqs.ps1 -Release         # 另裝 Inno Setup 6（build_release.ps1 產安裝精靈用）
    .\scripts\setup_prereqs.ps1 -Browser         # 另裝 Chrome（docs 截圖腳本與瀏覽器檢查用）
    .\scripts\setup_prereqs.ps1 -Dl              # 另裝深度學習依賴（torch cu128 等，約 3GB）；沒有 NVIDIA GPU 加 -Cpu
    .\scripts\setup_prereqs.ps1 -NoSetup         # 只裝軟體，不建開發環境
    .\scripts\setup_prereqs.ps1 -DryRun          # 只列出會做的事
#>
[CmdletBinding()]
param(
    [switch]$Release,
    [switch]$Browser,
    [switch]$Dl,
    [switch]$Cpu,
    [switch]$NoSetup,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 版本需求：與 README「建置環境」一致
$PythonMinor = '3.12'          # 伺服端與擷取端都鎖 3.12（發行版內嵌的 CPython 也是 3.12）
$NodeMinMajor = 20             # vite 6／vitest 2 需要 18+；開發與測試用 24 LTS

function Say([string]$text, [string]$color = 'Gray') { Write-Host $text -ForegroundColor $color }
function Step([string]$text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }

# 原生程式把警告寫到 stderr：暫時放寬錯誤處理，只看離開碼
function Invoke-Native([scriptblock]$block) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $block; return $LASTEXITCODE } finally { $ErrorActionPreference = $saved }
}

# winget 裝完的程式要重新讀一次 PATH 才找得到（同一個 PowerShell 視窗）
function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

function Install-Package([string]$id, [string]$name) {
    $cmd = "winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements --disable-interactivity"
    if ($DryRun) { Say "  [DryRun] $cmd" 'Yellow'; return }
    Say "  安裝 $name（$id）…"
    $code = Invoke-Native { winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements --disable-interactivity }
    Update-SessionPath
    if ($code -ne 0) { throw "winget 安裝 $name 失敗（離開碼 $code）。可改到官方網站下載安裝後再執行本腳本。" }
}

function Test-Python {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { return $null }
    $saved = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        $v = & py "-$PythonMinor" -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { return "$v".Trim() } else { return $null }
    } finally { $ErrorActionPreference = $saved }
}

function Test-Node {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) { return $null }
    $v = "$(& node --version)".Trim().TrimStart('v')
    if ([int]($v.Split('.')[0]) -lt $NodeMinMajor) { return $null }
    return $v
}

function Find-Iscc {
    foreach ($c in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
        if (Test-Path -LiteralPath $c) { return $c }
    }
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Find-Chrome {
    foreach ($c in @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")) {
        if (Test-Path -LiteralPath $c) { return $c }
    }
    return $null
}

Step '檢查 winget'
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw '找不到 winget。請從 Microsoft Store 安裝或更新「應用程式安裝程式」（App Installer）後再執行。'
}
Say "  winget $(& winget --version)"

Step "Python $PythonMinor"
$py = Test-Python
if ($py) { Say "  已安裝 Python $py" 'Green' }
else {
    Install-Package 'Python.Python.3.12' "Python $PythonMinor"
    if (-not $DryRun) {
        $py = Test-Python
        if (-not $py) { throw "安裝後仍找不到 py -$PythonMinor。請關閉這個視窗、開新的 PowerShell 再執行一次。" }
        Say "  已安裝 Python $py" 'Green'
    }
}

Step "Node.js（$NodeMinMajor 以上，建議 LTS）"
$node = Test-Node
if ($node) { Say "  已安裝 Node.js $node、npm $(& npm --version)" 'Green' }
else {
    Install-Package 'OpenJS.NodeJS.LTS' 'Node.js LTS'
    if (-not $DryRun) {
        $node = Test-Node
        if (-not $node) { throw '安裝後仍找不到 node。請關閉這個視窗、開新的 PowerShell 再執行一次。' }
        Say "  已安裝 Node.js $node" 'Green'
    }
}

Step 'Git'
if (Get-Command git -ErrorAction SilentlyContinue) { Say "  已安裝 $(& git --version)" 'Green' }
else { Install-Package 'Git.Git' 'Git' }

if ($Release) {
    Step 'Inno Setup 6（build_release.ps1 產安裝精靈）'
    $iscc = Find-Iscc
    if ($iscc) { Say "  已安裝：$iscc" 'Green' } else { Install-Package 'JRSoftware.InnoSetup' 'Inno Setup 6' }
}

if ($Browser) {
    Step 'Google Chrome（docs 截圖與瀏覽器檢查；腳本以 PW_EXE 或預設路徑使用系統 Chrome）'
    $chrome = Find-Chrome
    if ($chrome) { Say "  已安裝：$chrome" 'Green' } else { Install-Package 'Google.Chrome' 'Google Chrome' }
}

if ($Dl -and -not $Cpu) {
    Step 'NVIDIA 顯示卡驅動（深度學習 GPU）'
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        $gpu = Invoke-Native { & nvidia-smi --query-gpu=name,driver_version --format=csv,noheader }
        Say "  已偵測：$gpu" 'Green'
    } else {
        Say '  找不到 nvidia-smi：請到 https://www.nvidia.com/Download/index.aspx 安裝驅動（RTX 50 系列需 570 版以上），或改用 -Cpu。' 'Yellow'
    }
}

if (-not $NoSetup) {
    Step '開發環境（.venv、requirements、資料庫、示範資料、前端套件）'
    if ($DryRun) { Say '  [DryRun] .\scripts\dev.ps1 -Setup -NoStart' 'Yellow' }
    else { & (Join-Path $PSScriptRoot 'dev.ps1') -Setup -NoStart }

    if ($Dl) {
        Step '深度學習依賴'
        if ($DryRun) { Say "  [DryRun] .\scripts\setup_dl.ps1$(if ($Cpu) { ' -Cpu' })" 'Yellow' }
        elseif ($Cpu) { & (Join-Path $PSScriptRoot 'setup_dl.ps1') -Cpu }
        else { & (Join-Path $PSScriptRoot 'setup_dl.ps1') }
    }
}

Step '完成'
if ($NoSetup) { Say '  軟體已就緒。建立開發環境：.\scripts\dev.ps1 -Setup' }
else { Say '  啟動：.\scripts\dev.ps1（後端 8000、TCP 9000、前端 5173）；停止：.\scripts\stop.ps1' }
if (-not $Release) { Say '  要產發行版安裝精靈再加 -Release（Inno Setup 6）；沒有也能產 zip。' }
