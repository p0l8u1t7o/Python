[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8000,

    [ValidateRange(1, 65535)]
    [int]$WebPort = 5173,

    [switch]$SkipBootstrap,

    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$webRoot = Join-Path $projectRoot "apps\web"
$viteEntrypoint = Join-Path $webRoot "node_modules\vite\bin\vite.js"
$runtimeDir = Join-Path $projectRoot ".local\run"
$logDir = Join-Path $projectRoot ".local\logs"
$stateFile = Join-Path $runtimeDir "dev-processes.json"
$apiStdin = Join-Path $runtimeDir "api.stdin"
$webStdin = Join-Path $runtimeDir "web.stdin"
$workerStdin = Join-Path $runtimeDir "worker.stdin"
$stopScript = Join-Path $PSScriptRoot "stop-dev.ps1"

function Assert-LastExitCode {
    param([Parameter(Mandatory)][string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

function Test-ManagedProcess {
    param([Parameter(Mandatory)][object]$Descriptor)

    $process = Get-Process -Id ([int]$Descriptor.pid) -ErrorAction SilentlyContinue
    if (-not $process) {
        return $false
    }

    try {
        return (
            $process.StartTime.ToUniversalTime().Ticks -eq [long]$Descriptor.start_time_utc_ticks -and
            $process.ProcessName -eq [string]$Descriptor.process_name
        )
    } catch {
        return $false
    }
}

function Find-AvailableTcpPort {
    param([Parameter(Mandatory)][int]$PreferredPort)

    $lastPort = [Math]::Min(65535, $PreferredPort + 20)
    foreach ($candidate in $PreferredPort..$lastPort) {
        $existingListener = Get-NetTCPConnection -State Listen -LocalPort $candidate `
            -ErrorAction SilentlyContinue
        if ($existingListener) {
            continue
        }

        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $candidate)
        try {
            $listener.Start()
            return $candidate
        } catch [Net.Sockets.SocketException] {
            continue
        } finally {
            $listener.Stop()
        }
    }

    throw "No available TCP port was found between $PreferredPort and $lastPort."
}

function Wait-HttpEndpoint {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Uri,
        [int]$TimeoutSeconds = 20
    )

    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(2)

    try {
        $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
        do {
            try {
                $response = ($client.GetAsync($Uri)).GetAwaiter().GetResult()
                try {
                    if ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 500) {
                        Write-Host "$Name is ready: $Uri"
                        return
                    }
                } finally {
                    $response.Dispose()
                }
            } catch {
                Start-Sleep -Milliseconds 250
            }
        } while ([DateTime]::UtcNow -lt $deadline)
    } finally {
        $client.Dispose()
        $handler.Dispose()
    }

    throw "$Name did not become ready within $TimeoutSeconds seconds: $Uri"
}

function Stop-StartedProcess {
    param([System.Diagnostics.Process]$Process)

    if (-not $Process) {
        return
    }

    $current = Get-Process -Id $Process.Id -ErrorAction SilentlyContinue
    if ($current -and $current.StartTime.ToUniversalTime().Ticks -eq $Process.StartTime.ToUniversalTime().Ticks) {
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            & taskkill.exe /PID ([string]$Process.Id) /T /F *> $null
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
    }
}

function Show-LogTail {
    param([Parameter(Mandatory)][string]$Path)

    if (Test-Path -LiteralPath $Path) {
        Write-Host "--- $Path"
        Get-Content -LiteralPath $Path -Tail 30
    }
}

if (Test-Path -LiteralPath $stateFile) {
    $existingState = $null
    try {
        $existingState = Get-Content -Raw -Encoding UTF8 -LiteralPath $stateFile | ConvertFrom-Json
    } catch {
        Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
        Write-Warning "Invalid stale runtime state was removed: $($_.Exception.Message)"
    }

    if ($existingState) {
        $sameRoot = [IO.Path]::GetFullPath([string]$existingState.project_root) -eq $projectRoot
        if (-not $sameRoot) {
            throw "Refusing to use runtime state created for a different project root."
        }

        $apiRunning = Test-ManagedProcess -Descriptor $existingState.api
        $webRunning = Test-ManagedProcess -Descriptor $existingState.web
        $workerRunning = $false
        if ($existingState.PSObject.Properties.Name -contains "worker") {
            $workerRunning = Test-ManagedProcess -Descriptor $existingState.worker
        }
        if ($apiRunning -and $webRunning -and $workerRunning) {
            Write-Host "PseudoPhysicsEngine development services are already running."
            Write-Host "Web: http://127.0.0.1:$($existingState.web.port)"
            Write-Host "API docs: http://127.0.0.1:$($existingState.api.port)/docs"
            return
        }

        if ($apiRunning -or $webRunning -or $workerRunning) {
            Write-Warning "A partial previous startup was found; stopping it before restart."
            & $stopScript
        } else {
            Remove-Item -LiteralPath $stateFile -Force
        }
    }
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Python is missing from .venv. Prepare the Python 3.12 environment first."
}

$npmCommand = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    throw "npm.cmd was not found. Install Node.js and npm before starting the web client."
}

if (-not $SkipBootstrap) {
    & (Join-Path $PSScriptRoot "init-dev.ps1")
    Assert-LastExitCode "Development bootstrap"

    if (-not (Test-Path -LiteralPath (Join-Path $webRoot "node_modules\.bin\vite.cmd"))) {
        Push-Location $webRoot
        try {
            & $npmCommand.Source ci
            Assert-LastExitCode "npm ci"
        } finally {
            Pop-Location
        }
    }
}

$nodeCommand = Get-Command "node.exe" -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
    throw "node.exe was not found. Install Node.js before starting the web client."
}
if (-not (Test-Path -LiteralPath $viteEntrypoint)) {
    throw "Vite is missing. Run without -SkipBootstrap so web dependencies can be installed."
}

Push-Location $webRoot
try {
    & $npmCommand.Source run generate:types
    Assert-LastExitCode "Web contract generation"
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Force -Path $runtimeDir, $logDir | Out-Null
New-Item -ItemType File -Force -Path $apiStdin, $webStdin, $workerStdin | Out-Null

$selectedApiPort = Find-AvailableTcpPort -PreferredPort $ApiPort
$selectedWebPort = Find-AvailableTcpPort -PreferredPort $WebPort
if ($selectedApiPort -ne $ApiPort) {
    Write-Warning "API port $ApiPort is occupied; using $selectedApiPort."
}
if ($selectedWebPort -ne $WebPort) {
    Write-Warning "Web port $WebPort is occupied; using $selectedWebPort."
}

$apiStdout = Join-Path $logDir "api.stdout.log"
$apiStderr = Join-Path $logDir "api.stderr.log"
$webStdout = Join-Path $logDir "web.stdout.log"
$webStderr = Join-Path $logDir "web.stderr.log"
$workerStdout = Join-Path $logDir "worker.stdout.log"
$workerStderr = Join-Path $logDir "worker.stderr.log"
$apiProcess = $null
$webProcess = $null
$workerProcess = $null

$previousPpeHost = $env:PPE_HOST
$previousPpePort = $env:PPE_PORT
$previousCorsOrigins = $env:PPE_CORS_ORIGINS
$previousProxyTarget = $env:VITE_API_PROXY_TARGET
$startFailure = $null

try {
    $env:PPE_HOST = "127.0.0.1"
    $env:PPE_PORT = [string]$selectedApiPort
    $env:PPE_CORS_ORIGINS = "http://127.0.0.1:$selectedWebPort,http://localhost:$selectedWebPort"
    $apiProcess = Start-Process -FilePath $venvPython -ArgumentList @("-m", "ppe_api") `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardInput $apiStdin `
        -RedirectStandardOutput $apiStdout -RedirectStandardError $apiStderr

    $workerApiUrl = "http://127.0.0.1:$selectedApiPort/api/v1"
    $workerProcess = Start-Process -FilePath $venvPython `
        -ArgumentList @("-m", "ppe_worker", "--api-url", $workerApiUrl) `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardInput $workerStdin `
        -RedirectStandardOutput $workerStdout -RedirectStandardError $workerStderr

    $env:VITE_API_PROXY_TARGET = "http://127.0.0.1:$selectedApiPort"
    $webProcess = Start-Process -FilePath $nodeCommand.Source `
        -ArgumentList @("node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", $selectedWebPort, "--strictPort") `
        -WorkingDirectory $webRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardInput $webStdin `
        -RedirectStandardOutput $webStdout -RedirectStandardError $webStderr
} catch {
    $startFailure = $_
} finally {
    if ($null -eq $previousPpeHost) { Remove-Item Env:PPE_HOST -ErrorAction SilentlyContinue } else { $env:PPE_HOST = $previousPpeHost }
    if ($null -eq $previousPpePort) { Remove-Item Env:PPE_PORT -ErrorAction SilentlyContinue } else { $env:PPE_PORT = $previousPpePort }
    if ($null -eq $previousCorsOrigins) { Remove-Item Env:PPE_CORS_ORIGINS -ErrorAction SilentlyContinue } else { $env:PPE_CORS_ORIGINS = $previousCorsOrigins }
    if ($null -eq $previousProxyTarget) { Remove-Item Env:VITE_API_PROXY_TARGET -ErrorAction SilentlyContinue } else { $env:VITE_API_PROXY_TARGET = $previousProxyTarget }
}

if ($startFailure) {
    Stop-StartedProcess -Process $webProcess
    Stop-StartedProcess -Process $workerProcess
    Stop-StartedProcess -Process $apiProcess
    Remove-Item -LiteralPath $apiStdin, $webStdin, $workerStdin -Force -ErrorAction SilentlyContinue
    Show-LogTail -Path $apiStderr
    Show-LogTail -Path $webStderr
    Show-LogTail -Path $workerStderr
    throw $startFailure
}

try {
    if (-not $apiProcess -or -not $webProcess -or -not $workerProcess) {
        throw "One or more development processes could not be started."
    }

    $state = [ordered]@{
        project_root = $projectRoot
        started_at_utc = [DateTime]::UtcNow.ToString("O")
        api = [ordered]@{
            pid = $apiProcess.Id
            process_name = $apiProcess.ProcessName
            start_time_utc_ticks = $apiProcess.StartTime.ToUniversalTime().Ticks
            port = $selectedApiPort
        }
        web = [ordered]@{
            pid = $webProcess.Id
            process_name = $webProcess.ProcessName
            start_time_utc_ticks = $webProcess.StartTime.ToUniversalTime().Ticks
            port = $selectedWebPort
        }
        worker = [ordered]@{
            pid = $workerProcess.Id
            process_name = $workerProcess.ProcessName
            start_time_utc_ticks = $workerProcess.StartTime.ToUniversalTime().Ticks
        }
    }
    $state | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -LiteralPath $stateFile

    $apiHealthUrl = "http://127.0.0.1:$selectedApiPort/api/v1/health"
    $webUrl = "http://127.0.0.1:$selectedWebPort"
    Wait-HttpEndpoint -Name "API" -Uri $apiHealthUrl
    Wait-HttpEndpoint -Name "Web" -Uri $webUrl
    if (-not (Test-ManagedProcess -Descriptor $state.worker)) {
        throw "Rules worker exited during startup."
    }

    Write-Host ""
    Write-Host "PseudoPhysicsEngine is running."
    Write-Host "Web: $webUrl"
    Write-Host "API docs: http://127.0.0.1:$selectedApiPort/docs"
    Write-Host "Worker: rules validation queue is active"
    Write-Host "Logs: $logDir"
    Write-Host "Stop: .\stop-dev.cmd"

    if ($OpenBrowser) {
        Start-Process $webUrl
    }
} catch {
    Stop-StartedProcess -Process $webProcess
    Stop-StartedProcess -Process $workerProcess
    Stop-StartedProcess -Process $apiProcess
    Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $apiStdin, $webStdin, $workerStdin -Force -ErrorAction SilentlyContinue
    Show-LogTail -Path $apiStderr
    Show-LogTail -Path $webStderr
    Show-LogTail -Path $workerStderr
    throw
}
