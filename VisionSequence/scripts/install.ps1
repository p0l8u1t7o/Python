<#
.SYNOPSIS
    First install of a VisionSequence station from a release tree (called by the setup wizard, or run by hand).

.DESCRIPTION
    Run from an elevated PowerShell inside the release tree (the folder that holds python\, manage.py and release.json):
        .\scripts\install.ps1 -Root C:\VisionSequence -StationId ST01 -HostNames vision-st01,192.168.1.10 -Subnet 192.168.1.0/24 -Https internal

    What it does, in order: check the tree -> create <Root>\{data,plugins,packs,certs} -> write .env once (random keys,
    DEBUG=0, absolute paths) -> put the tree at <Root>\app\<version> and point <Root>\current at it -> migrate ->
    create the first administrator BEFORE any port is open -> publish the capture client -> HTTPS proxy config ->
    firewall -> services -> doctor -> summary. Re-running is safe: existing .env, data and plugins are kept.

    -Unattended never prompts (setup wizard / mass rollout): give -AdminPassword or -AdminPasswordEnv, otherwise a random
    password is generated and printed once.
#>
[CmdletBinding()]
param(
    [string]$Root = 'C:\VisionSequence',
    [string]$StationId = '',
    [string[]]$HostNames = @(),
    [string]$Subnet = '',
    [ValidateSet('internal', 'custom', 'none')][string]$Https = 'internal',
    [string]$Cert = '',
    [string]$Key = '',
    [int]$HttpPort = 8000,
    [int]$HttpsPort = 443,
    [ValidateSet('service', 'task')][string]$Mode = 'service',
    [string]$User = 'LocalSystem',
    [string]$Password = '',
    [switch]$Interactive,
    [string]$AdminUser = 'admin',
    [string]$AdminPassword = '',
    [string]$AdminPasswordEnv = '',
    [switch]$NoTcpAuth,
    [switch]$NoFirewall,
    [switch]$NoService,
    [switch]$Unattended,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'vslib.ps1')
$source = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path.TrimEnd('\')
$Root = $Root.TrimEnd('\')
if (-not $StationId) { $StationId = $env:COMPUTERNAME }
$started = Get-Date

function Fail([string]$Message) { Write-VsFail $Message; exit 1 }

# ---- 0. 前置檢查 -------------------------------------------------------------------------
Write-VsStep "Checking the release tree at $source"
foreach ($rel in @('python\python.exe', 'manage.py', 'apps', 'config', 'frontend\dist\index.html', 'scripts\service.ps1', 'scripts\vsctl.ps1')) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $rel))) { Fail "Missing $rel - run this from a release tree built by scripts\build_release.ps1, not from a checkout." }
}
$version = ''
if (Test-Path -LiteralPath (Join-Path $source 'release.json')) { $version = [string]((Get-Content -LiteralPath (Join-Path $source 'release.json') -Raw | ConvertFrom-Json).version) }
elseif (Test-Path -LiteralPath (Join-Path $source 'VERSION')) { $version = (Get-Content -LiteralPath (Join-Path $source 'VERSION') -Raw).Trim() }
if (-not $version) { Fail "No release.json/VERSION in the tree." }
if (-not (Test-VsAdmin) -and -not ($NoService -and $NoFirewall)) { Fail "Run from an elevated PowerShell (services and firewall rules need it), or pass -NoService -NoFirewall for a user-level trial." }
if ($Https -eq 'custom' -and (-not $Cert -or -not $Key)) { Fail "-Https custom needs -Cert and -Key." }
if ($Mode -eq 'task' -and $Https -ne 'none') { Write-VsWarn "-Mode task with HTTPS: the proxy still runs as a service." }
$os = [Environment]::OSVersion.Version
if ($os.Major -lt 10) { Fail "Windows 10 / Server 2016 or newer is required." }
if (-not [Environment]::Is64BitOperatingSystem) { Fail "64-bit Windows is required." }
Write-VsOk "VisionSequence $version, Windows $($os.Major).$($os.Build), 64-bit"

# ---- 1. 目錄 ---------------------------------------------------------------------------------
Write-VsStep "Creating $Root"
$appDir = Join-Path $Root 'app'
$target = Join-Path $appDir $version
foreach ($d in @($Root, $appDir, (Join-Path $Root 'data'), (Join-Path $Root 'data\logs'), (Join-Path $Root 'data\run'), (Join-Path $Root 'data\backups'), (Join-Path $Root 'data\downloads'), (Join-Path $Root 'plugins'), (Join-Path $Root 'plugins\_wheels'), (Join-Path $Root 'packs'), (Join-Path $Root 'certs'))) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

# ---- 2. 版本樹 ---------------------------------------------------------------------------------
if ($source -ieq $target) {
    Write-VsOk "Tree already in place: $target"
} else {
    if ((Test-Path -LiteralPath $target) -and -not $Force) {
        Fail "$target already exists. For an upgrade use: vsctl update <zip>; to overwrite the same version pass -Force."
    }
    Write-VsStep "Copying the tree to $target"
    & robocopy $source $target /E /NFL /NDL /NJH /NJS /NP /R:2 /W:2 /XD 'data' 'plugins' | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "robocopy failed (exit $LASTEXITCODE)." }
    Write-VsOk "Copied"
}
$python = Join-Path $target 'python\python.exe'
$link = Join-Path $Root 'current'
$item = Get-Item -LiteralPath $link -ErrorAction SilentlyContinue
if ($item -and $item.Target -and (([string]$item.Target).TrimEnd('\') -ine $target)) {
    if (-not $Force) { Fail "current already points at $($item.Target). Use vsctl update for upgrades, or -Force to repoint." }
    [IO.Directory]::Delete($link)
    $item = $null
}
if (-not $item) { New-Item -ItemType Junction -Path $link -Target $target | Out-Null }
Write-VsOk "current -> $target"

# vsctl.cmd 在安裝根：永遠呼叫 current 裡的 vsctl.ps1（升級後自動是新版）
$cmd = @(
    '@echo off',
    'rem VisionSequence station command line - see docs\deployment.html',
    'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0current\scripts\vsctl.ps1" %*'
) -join "`r`n"
[IO.File]::WriteAllText((Join-Path $Root 'vsctl.cmd'), $cmd + "`r`n", (New-Object Text.ASCIIEncoding))

# ---- 3. .env（只在不存在時產生） -----------------------------------------------------------------
$envFile = Join-Path $Root '.env'
$hosts = @($HostNames | Where-Object { $_ } | ForEach-Object { $_.Trim().ToLower() })
foreach ($h in @('localhost', '127.0.0.1', $env:COMPUTERNAME.ToLower())) { if ($hosts -notcontains $h) { $hosts += $h } }
$generated = $false
if (Test-Path -LiteralPath $envFile) {
    Write-VsOk ".env exists - keeping it (change values with: vsctl env set KEY=VALUE)"
} else {
    Write-VsStep "Writing $envFile"
    $tcpAuth = ''
    if (-not $NoTcpAuth) { $tcpAuth = New-VsSecret 24 }
    $lines = @(
        "# VisionSequence station configuration - generated by install.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm').",
        '# Read: vsctl env list      Change: vsctl env set KEY=VALUE      Reference: current\.env.example',
        '',
        '# ---- Django ----',
        'DEBUG=0',
        "SECRET_KEY=$(New-VsSecret 48)",
        "ALLOWED_HOSTS=$($hosts -join ',')",
        "BEHIND_HTTPS_PROXY=$(if ($Https -eq 'none') { '0' } else { '1' })",
        '',
        '# ---- Paths (absolute; upgrades never touch these) ----',
        "DATA_DIR=$(Join-Path $Root 'data')",
        "VISION_PLUGIN_DIR=$(Join-Path $Root 'plugins')",
        '',
        '# ---- Station ----',
        "VISION_STATION_ID=$StationId",
        "VISION_HTTP_PORT=$HttpPort",
        'VISION_TCP_PORT=9000',
        'VISION_CAPTURE_PORT=9100',
        'VISION_ARCHIVE_DEFAULT=off',
        '',
        '# ---- Keys (integrators, capture clients, TCP commands). Rotate with vsctl env set + vsctl restart ----',
        "VISION_API_KEY=$(New-VsSecret 32)",
        "VISION_CAPTURE_AUTH=$(New-VsSecret 32)",
        "VISION_TCP_AUTH=$tcpAuth",
        '',
        '# ---- AI assistant (optional; leave empty for the offline rule engine) ----',
        'VISION_AGENT_PROVIDER=',
        'VISION_AGENT_API_KEY=',
        'VISION_AGENT_MODEL=',
        'YOLO_OFFLINE=1'
    )
    [IO.File]::WriteAllText($envFile, (($lines -join "`r`n") + "`r`n"), (New-Object Text.UTF8Encoding $false))
    $generated = $true
    Write-VsOk "Generated with random SECRET_KEY, API key, capture key$(if ($tcpAuth) { ', TCP auth key' })"
}
$dotenv = Read-VsDotEnv $envFile

# ---- 4. 資料庫與第一位管理員（開任何埠之前） -------------------------------------------------------
$env:VS_HOME = $Root
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:YOLO_OFFLINE = '1'
Write-VsStep "Database migration"
Push-Location $target
try {
    & $python manage.py migrate --noinput
    if ($LASTEXITCODE -ne 0) { Fail "migrate failed." }
    & $python -c "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); django.setup(); from django.contrib.auth.models import User; import sys; sys.exit(0 if User.objects.exists() else 3)" 2>$null
    $hasUsers = ($LASTEXITCODE -eq 0)
    $adminPrinted = ''
    if ($hasUsers) {
        Write-VsOk "Accounts exist - not creating $AdminUser"
    } else {
        Write-VsStep "Creating the first administrator '$AdminUser' (closes the no-account bootstrap window)"
        $pw = $AdminPassword
        if (-not $pw -and $AdminPasswordEnv) { $pw = [Environment]::GetEnvironmentVariable($AdminPasswordEnv) }
        if (-not $pw) {
            if ($Unattended) { $pw = New-VsSecret 12; $adminPrinted = $pw }
            else {
                $secure = Read-Host -Prompt "Password for $AdminUser" -AsSecureString
                $pw = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
                if (-not $pw) { Fail "Empty password." }
            }
        }
        $env:VS_ADMIN_PASSWORD = $pw
        try { & $python manage.py create_admin $AdminUser --password-env VS_ADMIN_PASSWORD } finally { Remove-Item Env:VS_ADMIN_PASSWORD -ErrorAction SilentlyContinue }
        if ($LASTEXITCODE -ne 0) { Fail "create_admin failed." }
    }
} finally {
    Pop-Location
}

# ---- 5. 擷取端安裝檔 ------------------------------------------------------------------------------
$clientSrc = Join-Path $target 'capture-client'
if (Test-Path -LiteralPath (Join-Path $clientSrc 'manifest.json')) {
    $dst = Join-Path $Root 'data\downloads'
    if (-not (Test-Path -LiteralPath (Join-Path $dst 'manifest.json')) -or $Force) {
        Copy-Item -Path (Join-Path $clientSrc '*') -Destination $dst -Force
        Write-VsOk "Capture client published to $dst (Integration > Capture > Download)"
    }
} else {
    Write-VsWarn "No capture-client\ in this release: the download button on the Capture page stays empty."
}

# ---- 6. HTTPS 代理設定 ---------------------------------------------------------------------------
$proxyScript = Join-Path $target 'scripts\proxy.ps1'
$serviceScript = Join-Path $target 'scripts\service.ps1'
$vsctl = Join-Path $target 'scripts\vsctl.ps1'
$proxyArgs = @{ Https = $Https; HostNames = $hosts; Port = $HttpsPort; Upstream = $HttpPort }
if ($Https -eq 'custom') { $proxyArgs['Cert'] = $Cert; $proxyArgs['Key'] = $Key }
& $proxyScript configure @proxyArgs
if ($Https -ne 'none') { Set-VsDotEnv $envFile 'BEHIND_HTTPS_PROXY' '1' } else { Set-VsDotEnv $envFile 'BEHIND_HTTPS_PROXY' '0' }

# ---- 7. 防火牆 -----------------------------------------------------------------------------------
if ($NoFirewall) { Write-VsWarn "Firewall rules skipped (-NoFirewall)" }
else {
    $fw = @{}
    if ($Subnet) { $fw['Subnet'] = $Subnet }
    & $vsctl firewall @fw
}

# ---- 8. 服務 -------------------------------------------------------------------------------------
$bind = '0.0.0.0'
if ($Https -ne 'none') { $bind = '127.0.0.1' }
if ($NoService) {
    Write-VsWarn "Services skipped (-NoService). Start by hand: vsctl run"
} else {
    $svc = @{ Mode = $Mode; Port = $HttpPort; BindHost = $bind; User = $User }
    if ($Password) { $svc['Password'] = $Password }
    if ($Interactive) { $svc['Interactive'] = $true }
    & $serviceScript install @svc
    if ($LASTEXITCODE -ne 0) { Fail "service install failed." }
    if ($Https -ne 'none') {
        & $proxyScript install
        if ($LASTEXITCODE -ne 0) { Fail "proxy install failed." }
    }
    Write-VsStep "Waiting for the platform"
    $ok = $false
    for ($i = 0; $i -lt 60 -and -not $ok; $i++) { $h = Get-VsHealth $HttpPort; if ($h) { $ok = $true } else { Start-Sleep -Seconds 1 } }
    if ($ok) { Write-VsOk "healthz: $($h.status) $($h.version)" } else { Write-VsWarn "The platform did not answer within 60 s; see $(Join-Path $Root 'data\logs\service.log')" }
}

# ---- 9. 體檢與摘要 ---------------------------------------------------------------------------------
Write-VsStep "Doctor"
Push-Location $target
try { & $python manage.py doctor } finally { Pop-Location }
$scheme = 'https'
$portText = ''
if ($Https -eq 'none') { $scheme = 'http'; $portText = ":$HttpPort" } elseif ($HttpsPort -ne 443) { $portText = ":$HttpsPort" }
$primary = ($hosts | Where-Object { $_ -notin @('localhost', '127.0.0.1') } | Select-Object -First 1)
if (-not $primary) { $primary = $env:COMPUTERNAME.ToLower() }
Write-Host ''
Write-Host "VisionSequence $version installed in $Root  ($([int]((Get-Date) - $started).TotalSeconds) s)" -ForegroundColor Green
Write-Host "  Web interface : ${scheme}://$primary$portText/   (also: $(($hosts | ForEach-Object { "${scheme}://$_$portText" }) -join ', '))"
if ($Https -eq 'internal') { Write-Host "  Client PCs    : import $(Join-Path $Root 'certs\root.crt') into Trusted Root CAs (vsctl certs export / certs import), see docs\deployment.html#https" }
Write-Host "  Sign in       : $AdminUser$(if ($adminPrinted) { "  password: $adminPrinted   (shown once - change it in Settings)" })"
Write-Host "  Integrators   : X-API-Key = vsctl env get VISION_API_KEY     capture clients: vsctl env get VISION_CAPTURE_AUTH     TCP: $(if ($dotenv['VISION_TCP_AUTH']) { 'AUTH <vsctl env get VISION_TCP_AUTH>' } else { 'no AUTH required' })"
Write-Host "  Ports         : $(if ($Https -ne 'none') { "$HttpsPort https" } else { "$HttpPort http" }), 9000 TCP commands, 9100 capture$(if ($Subnet) { "  (firewall: $Subnet only)" })"
Write-Host "  Commands      : $(Join-Path $Root 'vsctl.cmd') status | logs | doctor | backup | update <zip> | plugins install <zip> | dl install <pack>"
Write-Host "  Docs          : $(Join-Path $target 'docs\deployment.html')"
