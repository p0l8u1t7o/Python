[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,

    [string]$ProjectsRoot = "",

    [ValidateRange(1, 300)]
    [int]$StartupTimeoutSeconds = 15,

    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runtimeRoot = Join-Path $projectRoot ".cellforge-runtime"
$metadataPath = Join-Path $runtimeRoot "server.json"
$logsRoot = Join-Path $runtimeRoot "logs"
$stdoutPath = Join-Path $logsRoot "server.stdout.log"
$stderrPath = Join-Path $logsRoot "server.stderr.log"
$healthUrl = "http://127.0.0.1:$Port/api/health"
$siteUrl = "http://127.0.0.1:$Port"

if ([string]::IsNullOrWhiteSpace($ProjectsRoot)) {
    $ProjectsRoot = Join-Path $runtimeRoot "projects"
}
$ProjectsRoot = [IO.Path]::GetFullPath($ProjectsRoot)

function Get-CellForgeHealth {
    try {
        return Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1 -Method Get
    }
    catch {
        return $null
    }
}

function Test-CellForgeProcess {
    param([int]$ProcessId)

    $processInfo = Get-CimInstance Win32_Process `
        -Filter "ProcessId = $ProcessId" `
        -ErrorAction SilentlyContinue
    if ($null -eq $processInfo) {
        return $false
    }

    $command = [string]$processInfo.CommandLine
    return (
        $command.Contains("server.main:app") -and
        $command.Contains($projectRoot)
    )
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python virtual environment not found: $pythonPath`nRun the Python 3.12 environment setup first."
}

New-Item -ItemType Directory -Path $logsRoot -Force | Out-Null
New-Item -ItemType Directory -Path $ProjectsRoot -Force | Out-Null

$health = Get-CellForgeHealth
if ($null -ne $health -and $health.service -eq "CellForge") {
    $runningProjectsRoot = [IO.Path]::GetFullPath([string]$health.projects_root)
    if (-not $runningProjectsRoot.Equals($ProjectsRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Port $Port is serving another CellForge projects root: $runningProjectsRoot"
    }
    if (-not (Test-CellForgeProcess -ProcessId ([int]$health.pid))) {
        throw "Port $Port reports CellForge, but PID $($health.pid) does not belong to this workspace."
    }

    $running = Get-Process -Id ([int]$health.pid) -ErrorAction Stop
    $adopted = [ordered]@{
        pid = [int]$health.pid
        port = $Port
        project_root = $projectRoot
        projects_root = $runningProjectsRoot
        started_utc = $running.StartTime.ToUniversalTime().ToString("o")
    }
    $adopted | ConvertTo-Json | Set-Content -LiteralPath $metadataPath -Encoding UTF8

    Write-Host "CellForge is already running: $siteUrl (PID $($health.pid))"
    if ($OpenBrowser) {
        Start-Process $siteUrl | Out-Null
    }
    exit 0
}

if (Test-Path -LiteralPath $metadataPath) {
    try {
        $stale = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (Test-CellForgeProcess -ProcessId ([int]$stale.pid)) {
            throw "CellForge PID $($stale.pid) is running but its health endpoint is unavailable. Check $stderrPath"
        }
    }
    catch {
        if ($_.Exception.Message -like "CellForge PID*") {
            throw
        }
    }
    Remove-Item -LiteralPath $metadataPath -Force
}

$previousProjectsRoot = $env:CELLFORGE_PROJECTS_ROOT
try {
    $env:CELLFORGE_PROJECTS_ROOT = $ProjectsRoot
    $serverArguments = (
        '-m uvicorn server.main:app --app-dir "{0}" --host 127.0.0.1 --port {1}' -f
        $projectRoot.Replace('"', '\"'), $Port
    )
    $server = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList $serverArguments `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru
}
finally {
    if ($null -eq $previousProjectsRoot) {
        Remove-Item Env:CELLFORGE_PROJECTS_ROOT -ErrorAction SilentlyContinue
    }
    else {
        $env:CELLFORGE_PROJECTS_ROOT = $previousProjectsRoot
    }
}

$metadata = [ordered]@{
    pid = $server.Id
    port = $Port
    project_root = $projectRoot
    projects_root = $ProjectsRoot
    started_utc = $server.StartTime.ToUniversalTime().ToString("o")
}
$metadata | ConvertTo-Json | Set-Content -LiteralPath $metadataPath -Encoding UTF8

$deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
$actualServerId = 0
while ([DateTime]::UtcNow -lt $deadline) {
    if ($server.HasExited) {
        break
    }

    $health = Get-CellForgeHealth
    if (
        $null -ne $health -and
        $health.service -eq "CellForge" -and
        (Test-CellForgeProcess -ProcessId ([int]$health.pid))
    ) {
        $actualServerId = [int]$health.pid
        $actualServer = Get-Process -Id $actualServerId -ErrorAction Stop
        $metadata.pid = $actualServerId
        $metadata.started_utc = $actualServer.StartTime.ToUniversalTime().ToString("o")
        $metadata | ConvertTo-Json | Set-Content -LiteralPath $metadataPath -Encoding UTF8

        Write-Host "CellForge started: $siteUrl (PID $actualServerId)"
        Write-Host "Projects: $ProjectsRoot"
        Write-Host "Logs: $logsRoot"
        if ($OpenBrowser) {
            Start-Process $siteUrl | Out-Null
        }
        # Start-Process uses asynchronous readers for redirected streams.  Dispose
        # our local handle before this short-lived launcher exits, otherwise a
        # caller such as start.cmd can remain attached until the server stops.
        $server.Dispose()
        exit 0
    }

    Start-Sleep -Milliseconds 250
    $server.Refresh()
}

if (-not $server.HasExited) {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
}
if ($actualServerId -gt 0 -and $actualServerId -ne $server.Id) {
    Stop-Process -Id $actualServerId -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $metadataPath -Force -ErrorAction SilentlyContinue

Write-Error "CellForge did not start within $StartupTimeoutSeconds seconds. See $stderrPath"
if (Test-Path -LiteralPath $stderrPath) {
    Get-Content -LiteralPath $stderrPath -Tail 30
}
exit 1
