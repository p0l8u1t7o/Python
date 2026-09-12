[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$stateFile = Join-Path $projectRoot ".local\run\dev-processes.json"
$apiStdin = Join-Path $projectRoot ".local\run\api.stdin"
$webStdin = Join-Path $projectRoot ".local\run\web.stdin"
$workerStdin = Join-Path $projectRoot ".local\run\worker.stdin"

function Test-ManagedProcess {
    param([Parameter(Mandatory)][object]$Descriptor)

    $process = Get-Process -Id ([int]$Descriptor.pid) -ErrorAction SilentlyContinue
    if (-not $process) {
        return $false
    }

    try {
        $startTicksMatch = $process.StartTime.ToUniversalTime().Ticks -eq [long]$Descriptor.start_time_utc_ticks
        $nameMatches = $process.ProcessName -eq [string]$Descriptor.process_name
        return $startTicksMatch -and $nameMatches
    } catch {
        return $false
    }
}

function Stop-ManagedProcess {
    param(
        [Parameter(Mandatory)][string]$Role,
        [Parameter(Mandatory)][object]$Descriptor
    )

    if (-not (Test-ManagedProcess -Descriptor $Descriptor)) {
        Write-Host "$Role is not running (stale state ignored)."
        return
    }

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & taskkill.exe /PID ([string]$Descriptor.pid) /T /F *> $null
        $taskkillExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($taskkillExitCode -ne 0 -and (Test-ManagedProcess -Descriptor $Descriptor)) {
        throw "Could not stop the managed $Role process (PID $($Descriptor.pid))."
    }

    Write-Host "$Role stopped (PID $($Descriptor.pid))."
}

if (-not (Test-Path -LiteralPath $stateFile)) {
    Remove-Item -LiteralPath $apiStdin, $webStdin, $workerStdin -Force -ErrorAction SilentlyContinue
    Write-Host "Development services are not running."
    return
}

try {
    $state = Get-Content -Raw -Encoding UTF8 -LiteralPath $stateFile | ConvertFrom-Json
} catch {
    Remove-Item -LiteralPath $stateFile -Force
    throw "The development runtime state was invalid and has been removed. No process was stopped."
}

if ([IO.Path]::GetFullPath([string]$state.project_root) -ne $projectRoot) {
    throw "Refusing to use runtime state created for a different project root."
}

$stopFailures = [Collections.Generic.List[string]]::new()
$services = [Collections.Generic.List[object]]::new()
$services.Add(@{ Role = "Web"; Descriptor = $state.web })
if ($state.PSObject.Properties.Name -contains "worker") {
    $services.Add(@{ Role = "Worker"; Descriptor = $state.worker })
}
$services.Add(@{ Role = "API"; Descriptor = $state.api })
foreach ($service in $services) {
    try {
        Stop-ManagedProcess -Role $service.Role -Descriptor $service.Descriptor
    } catch {
        $stopFailures.Add($_.Exception.Message)
    }
}

if ($stopFailures.Count -gt 0) {
    throw "One or more services could not be stopped. Runtime state was kept for retry: $($stopFailures -join ' ')"
}

Remove-Item -LiteralPath $stateFile -Force
Remove-Item -LiteralPath $apiStdin, $webStdin, $workerStdin -Force -ErrorAction SilentlyContinue
Write-Host "PseudoPhysicsEngine development services are stopped."
