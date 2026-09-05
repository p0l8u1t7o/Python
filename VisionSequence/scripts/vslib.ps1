# VisionSequence 現場腳本共用函式（Windows PowerShell 5.1）。由 service.ps1／proxy.ps1／vsctl.ps1／install.ps1 dot-source：
#   . (Join-Path $PSScriptRoot 'vslib.ps1')
# 只放「三層配置解析、.env 讀寫、找工具、跑 manage.py、輸出格式」這些每支腳本都要的東西；不做任何副作用。

Set-StrictMode -Version 2.0

function Test-VsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-VsStep([string]$Text) { Write-Host ("==> " + $Text) -ForegroundColor Cyan }
function Write-VsOk([string]$Text) { Write-Host ("  OK   " + $Text) -ForegroundColor Green }
function Write-VsWarn([string]$Text) { Write-Host ("  WARN " + $Text) -ForegroundColor Yellow }
function Write-VsFail([string]$Text) { Write-Host ("  FAIL " + $Text) -ForegroundColor Red }

function Read-VsDotEnv([string]$Path) {
    # 讀 .env 成 hashtable：跳過註解與空行、去掉成對引號；不展開變數（python-dotenv 也不會）。
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $values }
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $eq = $t.IndexOf('=')
        if ($eq -lt 1) { continue }
        $k = $t.Substring(0, $eq).Trim()
        $v = $t.Substring($eq + 1).Trim()
        if ($v.Length -ge 2 -and (($v[0] -eq '"' -and $v[-1] -eq '"') -or ($v[0] -eq "'" -and $v[-1] -eq "'"))) { $v = $v.Substring(1, $v.Length - 2) }
        $values[$k] = $v
    }
    return $values
}

function Set-VsDotEnv([string]$Path, [string]$Key, [string]$Value) {
    # 就地改一個鍵：已有（未註解）的那一行改值，沒有就補在檔尾；註解與順序保留；寫 UTF-8 無 BOM（dotenv 不吃 BOM）。
    $lines = @()
    if (Test-Path -LiteralPath $Path) { $lines = @([IO.File]::ReadAllLines($Path)) }
    $done = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ('^\s*' + [regex]::Escape($Key) + '\s*=')) {
            $lines[$i] = "$Key=$Value"
            $done = $true
            break
        }
    }
    if (-not $done) { $lines += "$Key=$Value" }
    [IO.File]::WriteAllText($Path, (($lines -join "`r`n") + "`r`n"), (New-Object Text.UTF8Encoding $false))
}

function New-VsSecret([int]$Bytes = 32) {
    # URL 安全的隨機字串（API 金鑰、SECRET_KEY）。
    $buf = New-Object byte[] $Bytes
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($buf)
    return ([Convert]::ToBase64String($buf)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Get-VsLayout {
    <#
    三層配置：
      開發：<root>（專案根）＝ VS_HOME；python 是 .venv
      發行：<VS_HOME>\app\<ver>\ ＝ root（scripts\ 的上一層）、<VS_HOME>\current 指向它；python 是 <current>\python\python.exe
    環境變數 VS_HOME 可強制指定（測試用）。回傳的 Current 是「服務要指向的固定路徑」：發行版永遠是 current junction，升級只換它。
    #>
    $root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path.TrimEnd('\')
    $appDir = Split-Path -Parent $root
    $release = ((Split-Path -Leaf $appDir) -eq 'app')
    $vsHome = $root
    if ($release) { $vsHome = Split-Path -Parent $appDir }
    if ($env:VS_HOME) { $vsHome = $env:VS_HOME.TrimEnd('\'); if (-not $release) { $release = ($vsHome -ne $root) } }
    $current = $root
    if ($release -and (Test-Path -LiteralPath (Join-Path $vsHome 'current'))) { $current = Join-Path $vsHome 'current' }
    $python = ''
    foreach ($c in @((Join-Path $current 'python\python.exe'), (Join-Path $root 'python\python.exe'), (Join-Path $current '.venv\Scripts\python.exe'), (Join-Path $root '.venv\Scripts\python.exe'))) {
        if (Test-Path -LiteralPath $c) { $python = $c; break }
    }
    $envFile = Join-Path $vsHome '.env'
    $dotenv = Read-VsDotEnv $envFile
    $dataDir = Join-Path $vsHome 'data'
    if ($env:DATA_DIR) { $dataDir = $env:DATA_DIR } elseif ($dotenv.ContainsKey('DATA_DIR') -and $dotenv['DATA_DIR']) { $dataDir = $dotenv['DATA_DIR'] }
    $pluginDir = Join-Path $vsHome 'plugins'
    if ($env:VISION_PLUGIN_DIR) { $pluginDir = $env:VISION_PLUGIN_DIR } elseif ($dotenv.ContainsKey('VISION_PLUGIN_DIR') -and $dotenv['VISION_PLUGIN_DIR']) { $pluginDir = $dotenv['VISION_PLUGIN_DIR'] }
    # .env 裡的相對路徑（開發用 ./data）以安裝根為基準，服務與 NSSM 一律拿絕對路徑
    foreach ($name in @('dataDir', 'pluginDir')) {
        $v = (Get-Variable $name).Value
        if (-not [IO.Path]::IsPathRooted($v)) { Set-Variable $name ([IO.Path]::GetFullPath((Join-Path $vsHome $v))) }
    }
    $version = ''
    $verFile = Join-Path $root 'VERSION'
    if (Test-Path -LiteralPath $verFile) { $version = ([IO.File]::ReadAllText($verFile)).Trim() }
    elseif (Test-Path -LiteralPath (Join-Path $root 'apps\vision\__init__.py')) {
        $m = [regex]::Match([IO.File]::ReadAllText((Join-Path $root 'apps\vision\__init__.py')), '__version__\s*=\s*"([^"]+)"')
        if ($m.Success) { $version = $m.Groups[1].Value }
    }
    return [pscustomobject]@{
        Root = $root; Home = $vsHome; Release = $release; Current = $current; Python = $python
        EnvFile = $envFile; DotEnv = $dotenv; DataDir = $dataDir; PluginDir = $pluginDir
        ToolsDir = (Join-Path $current 'tools'); Version = $version
    }
}

function Get-VsSetting($Layout, [string]$Key, [string]$Default = '') {
    # 環境變數 > .env > 預設（與 settings.py 的 _env 同一個優先序）。
    $v = [Environment]::GetEnvironmentVariable($Key)
    if ($v) { return $v }
    if ($Layout.DotEnv.ContainsKey($Key) -and $Layout.DotEnv[$Key] -ne '') { return $Layout.DotEnv[$Key] }
    return $Default
}

function Find-VsTool($Layout, [string]$Name, [string]$Override = '') {
    # 順序：明確指定 > <current>\tools\ > <root>\tools\ > PATH。找不到回空字串（呼叫端決定要不要 throw）。
    if ($Override) {
        if (Test-Path -LiteralPath $Override) { return (Resolve-Path -LiteralPath $Override).Path }
        throw "Tool not found: $Override"
    }
    foreach ($dir in @($Layout.ToolsDir, (Join-Path $Layout.Root 'tools'))) {
        $p = Join-Path $dir $Name
        if (Test-Path -LiteralPath $p) { return $p }
    }
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return ''
}

function Invoke-VsManage($Layout, [string[]]$Arguments, [switch]$PassThru) {
    # 在版本樹裡跑 manage.py（VS_HOME 固定指向安裝根，PYTHONIOENCODING 讓中文日誌不炸）。回傳離開碼；-PassThru 回輸出文字。
    if (-not $Layout.Python) { throw "No Python found under $($Layout.Current) (python\python.exe or .venv\Scripts\python.exe)." }
    $env:VS_HOME = $Layout.Home
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    # 維運指令不要外掛掛載那些 INFO 日誌（serve 保留）；stderr 有字時 PowerShell 在 Stop 模式下會把它當成錯誤中止，所以這裡放寬
    $hadLogLevel = [Environment]::GetEnvironmentVariable('LOG_LEVEL')
    if ($Arguments.Count -eq 0 -or $Arguments[0] -ne 'serve') { $env:LOG_LEVEL = 'WARNING' }
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location $Layout.Current
    try {
        if ($PassThru) {
            $out = & $Layout.Python 'manage.py' @Arguments 2>&1 | ForEach-Object { "$_" }
            $script:VsLastExit = $LASTEXITCODE
            return ($out -join "`n")
        }
        & $Layout.Python 'manage.py' @Arguments
        $script:VsLastExit = $LASTEXITCODE
        return $LASTEXITCODE
    } finally {
        Pop-Location
        $ErrorActionPreference = $prevEap
        if ($null -eq $hadLogLevel) { Remove-Item Env:LOG_LEVEL -ErrorAction SilentlyContinue } else { $env:LOG_LEVEL = $hadLogLevel }
    }
}

function Get-VsHealth([int]$Port, [string]$Scheme = 'http', [int]$TimeoutSec = 3) {
    # /healthz → @{ok; version} 或 $null（沒在聽）。HTTPS 自簽時略過憑證檢查（只是本機探測）。
    try {
        if ($Scheme -eq 'https') { [Net.ServicePointManager]::ServerCertificateValidationCallback = { $true } }
        $r = Invoke-WebRequest -UseBasicParsing -Uri "${Scheme}://127.0.0.1:$Port/healthz" -TimeoutSec $TimeoutSec
        $j = $r.Content | ConvertFrom-Json
        return @{ ok = $true; version = $j.version; status = $j.status }
    } catch {
        return $null
    } finally {
        if ($Scheme -eq 'https') { [Net.ServicePointManager]::ServerCertificateValidationCallback = $null }
    }
}

function Get-VsListening([int[]]$Ports) {
    # 回傳這台機器正在聽的那些埠（子集合）。
    $listen = @()
    try {
        $all = Get-NetTCPConnection -State Listen -ErrorAction Stop | Select-Object -ExpandProperty LocalPort -Unique
        foreach ($p in $Ports) { if ($all -contains $p) { $listen += $p } }
    } catch {
        $out = netstat -an | Select-String 'LISTENING'
        foreach ($p in $Ports) { if ($out | Select-String (":$p\s")) { $listen += $p } }
    }
    return $listen
}
