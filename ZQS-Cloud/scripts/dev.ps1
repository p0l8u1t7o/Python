<#
.SYNOPSIS
    Starts the ZQS Cloud development stack.

.DESCRIPTION
    Default mode runs the API and the React console only. That needs no broker
    and no queue: the API talks to SQLite directly, so the console is fully
    usable for browsing, configuration and history.

    -Full additionally starts the MQTT ingestor and the queue worker, which is
    what you want when testing the live data path. That mode needs Redis and
    EMQX, because the ingestor and worker are separate processes and cannot
    share the in-memory bus.

.PARAMETER Setup
    First-time setup: create the virtualenv, install dependencies, migrate,
    seed the demo tenant and generate history. Safe to re-run.

.PARAMETER Full
    Also start the ingestor and worker. Requires Redis (6379) and EMQX (1883).

.PARAMETER Simulate
    Also start device simulators publishing live telemetry. Implies -Full.

.PARAMETER HistoryDays
    Days of backfilled telemetry to generate during -Setup.

.PARAMETER NoBrowser
    Do not open the console in a browser.

.EXAMPLE
    .\scripts\dev.ps1 -Setup
    First run: installs everything, seeds demo data, then starts the stack.

.EXAMPLE
    .\scripts\dev.ps1
    Day-to-day: just start the API and the console.

.EXAMPLE
    .\scripts\dev.ps1 -Simulate
    Full pipeline with fake hardware publishing over MQTT.
#>
[CmdletBinding()]
param(
    [switch]$Setup,
    [switch]$Full,
    [switch]$Simulate,
    [double]$HistoryDays = 3,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$pidFile = Join-Path $root '.dev-pids.json'

if ($Simulate) { $Full = $true }

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Ok($message) { Write-Host "    $message" -ForegroundColor Green }
function Write-Warn($message) { Write-Host "    $message" -ForegroundColor Yellow }

function Test-Port {
    param([string]$ComputerName = '127.0.0.1', [int]$Port, [int]$TimeoutMs = 700)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($ComputerName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-Python {
    $venv = Join-Path $root '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    if (-not $Setup) {
        throw "Virtualenv not found at .venv. Run: .\scripts\dev.ps1 -Setup"
    }
    return $null
}

function Initialize-NodePath {
    if (Get-Command npm -ErrorAction SilentlyContinue) { return }
    # A fresh Node install is not on PATH until the shell is restarted.
    foreach ($candidate in @("$env:ProgramFiles\nodejs", "${env:ProgramFiles(x86)}\nodejs")) {
        if (Test-Path (Join-Path $candidate 'npm.cmd')) {
            $env:Path = "$env:Path;$candidate"
            return
        }
    }
    throw 'npm was not found. Install Node.js 20+ and re-open the terminal.'
}

$script:started = @()

function Start-DevService {
    param([string]$Title, [string]$Command, [string]$WorkingDirectory = $root)

    $process = Start-Process powershell `
        -ArgumentList '-NoExit', '-NoLogo', '-Command', "`$Host.UI.RawUI.WindowTitle='$Title'; $Command" `
        -WorkingDirectory $WorkingDirectory `
        -PassThru
    $script:started += [pscustomobject]@{ title = $Title; pid = $process.Id }
    Write-Ok "$Title (PID $($process.Id))"
}

function Invoke-Native {
    <#
        Windows PowerShell 5.1 turns a native command's stderr into ErrorRecords
        when the stream is redirected, and $ErrorActionPreference = 'Stop' then
        makes them terminating. Django logs to stderr, so an ordinary INFO line
        would abort setup. Run natives with 'Continue' and judge them by their
        exit code, which is the only signal that actually means failure.
    #>
    param([Parameter(Mandatory)][string]$FilePath, [string[]]$Arguments = @())

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$(Split-Path $FilePath -Leaf) $($Arguments -join ' ') exited with $LASTEXITCODE"
        }
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Wait-ForHttp {
    param([string]$Url, [int]$TimeoutSeconds = 45)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 | Out-Null
            return $true
        } catch {
            Start-Sleep -Milliseconds 600
        }
    }
    return $false
}

# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------
Push-Location $root
try {
    if ($Setup) {
        Write-Step 'Setting up the backend'
        # Framework INFO logs go to stderr, which PowerShell surfaces as error
        # records. Setup should show the commands' own summaries, nothing else.
        $previousLogLevel = $env:LOG_LEVEL
        $env:LOG_LEVEL = 'WARNING'
        $python = Get-Python
        if (-not $python) {
            $launcher = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
            $venvArgs = if ($launcher -eq 'py') { @('-3.12', '-m', 'venv', '.venv') } else { @('-m', 'venv', '.venv') }
            Invoke-Native -FilePath $launcher -Arguments $venvArgs
            $python = Join-Path $root '.venv\Scripts\python.exe'
            Write-Ok 'created .venv'
        }
        Invoke-Native -FilePath $python -Arguments @(
            '-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', 'requirements.txt'
        )
        Write-Ok 'python dependencies installed'

        if (-not (Test-Path (Join-Path $root '.env'))) {
            Copy-Item (Join-Path $root '.env.example') (Join-Path $root '.env')
            Write-Ok 'created .env from .env.example'
        }

        Invoke-Native -FilePath $python -Arguments @('manage.py', 'migrate', '--noinput')
        Invoke-Native -FilePath $python -Arguments @('manage.py', 'bootstrap')
        Invoke-Native -FilePath $python -Arguments @('manage.py', 'seed_demo')
        Write-Ok 'database migrated, catalogues and demo tenant seeded'

        if ($HistoryDays -gt 0) {
            Write-Step "Generating $HistoryDays day(s) of telemetry history"
            # --with-faults on purpose: -Setup is a demo bootstrap, and without
            # excursions the alerts page and the device logs start out empty.
            Invoke-Native -FilePath $python -Arguments @(
                'manage.py', 'generate_history',
                '--days', "$HistoryDays", '--interval', '120', '--clear', '--with-faults'
            )
        }

        $env:LOG_LEVEL = $previousLogLevel

        Write-Step 'Setting up the front end'
        Initialize-NodePath
        Push-Location (Join-Path $root 'frontend')
        try {
            Invoke-Native -FilePath 'npm.cmd' -Arguments @(
                'install', '--no-audit', '--no-fund', '--silent'
            )
            Write-Ok 'node dependencies installed'
        } finally {
            Pop-Location
        }
    }

    $python = Get-Python
    Initialize-NodePath

    # ----------------------------------------------------------------------
    # Preconditions
    # ----------------------------------------------------------------------
    foreach ($port in @(8000, 5173)) {
        if (Test-Port -Port $port) {
            throw "Port $port is already in use. Run .\scripts\stop.ps1 first."
        }
    }

    $busBackend = 'memory'
    if ($Full) {
        $redisUp = Test-Port -Port 6379
        $mqttUp = Test-Port -Port 1883

        if (-not $redisUp -or -not $mqttUp) {
            Write-Warn 'The live data path needs Redis and EMQX:'
            if (-not $redisUp) { Write-Warn '  docker run -d --name redis -p 6379:6379 redis:7-alpine' }
            if (-not $mqttUp) { Write-Warn '  docker run -d --name emqx -p 1883:1883 -p 18083:18083 emqx/emqx:5.8' }
            throw 'Start the missing services and try again, or drop -Full.'
        }
        # Ingestor and worker are separate processes, so the queue has to be
        # a real broker; the in-memory bus is per-process only.
        $busBackend = 'redis'
        Write-Ok 'Redis and EMQX reachable'
    }

    # ----------------------------------------------------------------------
    # Launch
    # ----------------------------------------------------------------------
    Write-Step 'Starting services'
    $env:BUS_BACKEND = $busBackend

    Start-DevService -Title 'zqs-api' -Command `
        "`$env:BUS_BACKEND='$busBackend'; & '$python' manage.py runserver 127.0.0.1:8000"

    if ($Full) {
        Start-DevService -Title 'zqs-ingestor' -Command `
            "`$env:BUS_BACKEND='$busBackend'; & '$python' manage.py run_ingestor"
        Start-DevService -Title 'zqs-worker' -Command `
            "`$env:BUS_BACKEND='$busBackend'; & '$python' manage.py run_worker"
    }

    Start-DevService -Title 'zqs-frontend' -Command 'npm run dev' `
        -WorkingDirectory (Join-Path $root 'frontend')

    if ($Simulate) {
        $profiles = @(
            @{ device = 'ZQS-BESS-0001'; profile = 'battery'; interval = 5 },
            @{ device = 'ZQS-METER-0001'; profile = 'meter'; interval = 5 },
            @{ device = 'ZQS-PV-0001'; profile = 'pv'; interval = 10 }
        )
        foreach ($item in $profiles) {
            Start-DevService -Title "zqs-sim-$($item.profile)" -Command `
                "& '$python' manage.py simulate_device --device $($item.device) --profile $($item.profile) --interval $($item.interval)"
        }
    }

    $script:started | ConvertTo-Json | Set-Content -Path $pidFile -Encoding utf8

    # ----------------------------------------------------------------------
    # Report
    # ----------------------------------------------------------------------
    Write-Step 'Waiting for the API'
    if (Wait-ForHttp -Url 'http://127.0.0.1:8000/healthz') {
        Write-Ok 'API is up'
    } else {
        Write-Warn 'API did not answer in time; check the zqs-api window.'
    }

    Write-Step 'Waiting for the console'
    if (Wait-ForHttp -Url 'http://127.0.0.1:5173/' -TimeoutSeconds 60) {
        Write-Ok 'console is up'
        if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:5173' }
    } else {
        Write-Warn 'Vite did not answer in time; check the zqs-frontend window.'
    }

    Write-Host ''
    Write-Host 'ZQS Cloud is running' -ForegroundColor Green
    Write-Host '  console    http://127.0.0.1:5173'
    Write-Host '  API docs   http://127.0.0.1:8000/api/docs'
    if ($Full) { Write-Host '  EMQX       http://127.0.0.1:18083  (admin / public)' }
    Write-Host ''
    Write-Host '  sign in    admin@example.com / ChangeMe-2026!'
    Write-Host '             operator@example.com, viewer@example.com (same password)'
    Write-Host ''
    Write-Host '  stop with  .\scripts\stop.ps1'
    if (-not $Full) {
        Write-Host ''
        Write-Warn 'Live MQTT ingest is not running. Use -Full or -Simulate for that.'
    }
} finally {
    Pop-Location
}
