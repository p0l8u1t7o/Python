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
    .\scripts\sim-console.ps1
    Bring the registered devices online as simulated MQTT clients (separate
    window; the stack itself never starts a simulator).
#>
[CmdletBinding()]
param(
    [switch]$Setup,
    [switch]$Full,
    [switch]$NoBroker,
    [double]$HistoryDays = 3,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$pidFile = Join-Path $root '.dev-pids.json'


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
        # The development broker, ruff and pytest live here. Installing them is
        # what makes the live path work out of the box without Docker.
        Invoke-Native -FilePath $python -Arguments @(
            '-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', 'requirements-dev.txt'
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

    # Default: the bundled development broker plus a combined
    # ingestor+worker process. That gives the whole live path - publish,
    # ingest, store, command - with nothing to install and nothing to run in
    # Docker. -Full swaps in real EMQX and Redis; -NoBroker drops the live
    # path entirely for anyone who only wants the console and the API.
    $busBackend = 'memory'
    $mqttEnabled = '1'
    $mqttProtocol = '311'   # the bundled broker speaks 3.1.1 only
    $mqttShared = '0'       # ...and has no shared subscriptions
    $useBundledBroker = -not $Full -and -not $NoBroker

    if ($NoBroker) {
        $mqttEnabled = '0'
        Write-Warn 'running without a broker (-NoBroker): live ingest and commands are off'
    }

    if ($useBundledBroker -and (Test-Port -Port 1883)) {
        # Something is already on 1883 - very likely a real EMQX the developer
        # started on purpose. Use it rather than failing to bind on top of it.
        $useBundledBroker = $false
        $mqttProtocol = '5'
        $mqttShared = '1'
        Write-Ok 'a broker is already listening on 1883 - using it'
    }

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
        $mqttEnabled = '1'
        $mqttProtocol = '5'
        $mqttShared = '1'
        Write-Ok 'Redis and EMQX reachable'
    }

    # ----------------------------------------------------------------------
    # Launch
    # ----------------------------------------------------------------------
    Write-Step 'Starting services'
    $env:BUS_BACKEND = $busBackend
    $env:MQTT_ENABLED = $mqttEnabled
    $env:MQTT_PROTOCOL_VERSION = $mqttProtocol
    $env:MQTT_USE_SHARED_SUBSCRIPTION = $mqttShared
    $childEnv = "`$env:BUS_BACKEND='$busBackend'; `$env:MQTT_ENABLED='$mqttEnabled'; " +
        "`$env:MQTT_PROTOCOL_VERSION='$mqttProtocol'; `$env:MQTT_USE_SHARED_SUBSCRIPTION='$mqttShared';"

    if ($useBundledBroker) {
        Start-DevService -Title 'zqs-broker' -Command `
            "$childEnv & '$python' manage.py run_broker"
        # No bind wait: the pipeline retries its broker connection, so the
        # only cost of racing it is one retry line in the log.
    }

    Start-DevService -Title 'zqs-api' -Command `
        "$childEnv & '$python' manage.py runserver 127.0.0.1:8000"

    if ($Full) {
        Start-DevService -Title 'zqs-ingestor' -Command `
            "$childEnv & '$python' manage.py run_ingestor"
        Start-DevService -Title 'zqs-worker' -Command `
            "$childEnv & '$python' manage.py run_worker"
    }
    elseif (-not $NoBroker) {
        # One process, because the in-memory bus cannot cross a process
        # boundary - see run_pipeline's docstring.
        Start-DevService -Title 'zqs-pipeline' -Command `
            "$childEnv & '$python' manage.py run_pipeline"
    }

    # Its own process, with its own tick. The scheduler's jobs are minutes
    # apart; a drawn control flow needs seconds of resolution, and one loop
    # cannot serve both.
    Start-DevService -Title 'zqs-workflows' -Command `
        "$childEnv & '$python' manage.py run_workflows"

    # Energy intervals, rollups, sessions and the dispatch engine. A 60 s
    # cycle rather than the production 300 s, so a strategy decision shows
    # up on the battery within a minute of the readings that triggered it.
    Start-DevService -Title 'zqs-scheduler' -Command `
        "$childEnv & '$python' manage.py run_scheduler --interval 60"

    Start-DevService -Title 'zqs-frontend' -Command 'npm run dev' `
        -WorkingDirectory (Join-Path $root 'frontend')

    # No simulator is started here on purpose: every registered device comes
    # up offline, and the desktop console (scripts\sim-console.ps1) is the one
    # place that brings them online as MQTT clients.

    $script:started | ConvertTo-Json | Set-Content -Path $pidFile -Encoding utf8

    # ----------------------------------------------------------------------
    # Report - both services polled in one loop, so the total wait is the
    # slower of the two, not their sum.
    # ----------------------------------------------------------------------
    Write-Step 'Waiting for the API and the console'
    $apiUp = $false
    $consoleUp = $false
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline -and -not ($apiUp -and $consoleUp)) {
        if (-not $apiUp) { $apiUp = Test-Port -Port 8000 -TimeoutMs 250 }
        if (-not $consoleUp) { $consoleUp = Test-Port -Port 5173 -TimeoutMs 250 }
        if (-not ($apiUp -and $consoleUp)) { Start-Sleep -Milliseconds 200 }
    }
    if ($apiUp) { Write-Ok 'API is up' } else { Write-Warn 'API did not answer in time; check the zqs-api window.' }
    if ($consoleUp) {
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
    if ($useBundledBroker) {
        Write-Ok 'development broker on mqtt://127.0.0.1:1883 - anonymous, no ACL, dev only'
        Write-Ok 'Devices are offline until you bring them online in .\scripts\sim-console.ps1'
    }
    if ($NoBroker) {
        Write-Host ''
        Write-Warn 'Live MQTT ingest is not running (-NoBroker). The health card shows MQTT as disabled, not failed.'
    }
} finally {
    Pop-Location
}

