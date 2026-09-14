[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,

    [ValidateRange(1, 300)]
    [int]$ShutdownTimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runtimeRoot = Join-Path $projectRoot ".cellforge-runtime"
$metadataPath = Join-Path $runtimeRoot "server.json"
$healthUrl = "http://127.0.0.1:$Port/api/health"

function Get-CellForgeHealth {
    try {
        return Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1 -Method Get
    }
    catch {
        return $null
    }
}

function Get-VerifiedProcess {
    param(
        [int]$ProcessId,
        [AllowNull()][string]$ExpectedStartUtc
    )

    $processInfo = Get-CimInstance Win32_Process `
        -Filter "ProcessId = $ProcessId" `
        -ErrorAction SilentlyContinue
    if ($null -eq $processInfo) {
        return $null
    }

    $command = [string]$processInfo.CommandLine
    if (
        -not $command.Contains("server.main:app") -or
        -not $command.Contains($projectRoot)
    ) {
        throw "Refusing to stop PID $ProcessId because it is not this workspace's CellForge server."
    }

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $null
    }

    if (-not [string]::IsNullOrWhiteSpace($ExpectedStartUtc)) {
        $expected = [DateTime]::Parse($ExpectedStartUtc).ToUniversalTime()
        $actual = $process.StartTime.ToUniversalTime()
        if ([Math]::Abs(($actual - $expected).TotalSeconds) -gt 2) {
            throw "Refusing to stop PID $ProcessId because its start time does not match server.json."
        }
    }

    return $process
}

$metadata = $null
if (Test-Path -LiteralPath $metadataPath) {
    try {
        $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $Port = [int]$metadata.port
        $healthUrl = "http://127.0.0.1:$Port/api/health"
    }
    catch {
        Write-Warning "server.json is invalid; falling back to health discovery."
        $metadata = $null
    }
}

$processId = if ($null -ne $metadata) { [int]$metadata.pid } else { 0 }
$expectedStartUtc = if ($null -ne $metadata) { [string]$metadata.started_utc } else { $null }

if ($processId -le 0) {
    $health = Get-CellForgeHealth
    if ($null -ne $health -and $health.service -eq "CellForge") {
        $processId = [int]$health.pid
    }
}

if ($processId -le 0) {
    Write-Host "CellForge is not running."
    Remove-Item -LiteralPath $metadataPath -Force -ErrorAction SilentlyContinue
    exit 0
}

$process = Get-VerifiedProcess -ProcessId $processId -ExpectedStartUtc $expectedStartUtc
if ($null -eq $process) {
    Write-Host "CellForge is already stopped; removing stale metadata."
    Remove-Item -LiteralPath $metadataPath -Force -ErrorAction SilentlyContinue
    exit 0
}

Stop-Process -Id $processId -ErrorAction Stop
$deadline = [DateTime]::UtcNow.AddSeconds($ShutdownTimeoutSeconds)
while ([DateTime]::UtcNow -lt $deadline) {
    if ($process.HasExited) {
        break
    }

    Start-Sleep -Milliseconds 200
    $process.Refresh()
}

if (-not $process.HasExited) {
    Stop-Process -Id $processId -Force -ErrorAction Stop
    $process.WaitForExit(2000) | Out-Null
}

Remove-Item -LiteralPath $metadataPath -Force -ErrorAction SilentlyContinue
Write-Host "CellForge stopped (PID $processId)."
exit 0
