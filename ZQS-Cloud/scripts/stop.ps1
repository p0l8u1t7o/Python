<#
.SYNOPSIS
    Stops everything scripts\dev.ps1 started.

.DESCRIPTION
    Uses the PID file written at launch. Falls back to matching command lines,
    so a stack started before the PID file existed - or one whose file was
    deleted - can still be stopped.
#>
[CmdletBinding()]
param([switch]$Quiet)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$pidFile = Join-Path $root '.dev-pids.json'

function Write-Info($message) { if (-not $Quiet) { Write-Host $message } }

$stopped = 0

# The launcher window is a PowerShell host; killing it leaves the python or
# node child running, so walk down to the descendants first.
function Stop-Tree {
    param([int]$ProcessId)
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) { Stop-Tree -ProcessId $child.ProcessId }
    try {
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
        $script:stopped++
    } catch {
        # Already gone.
    }
}

if (Test-Path $pidFile) {
    $entries = Get-Content $pidFile -Raw | ConvertFrom-Json
    foreach ($entry in @($entries)) {
        if (Get-Process -Id $entry.pid -ErrorAction SilentlyContinue) {
            Write-Info "stopping $($entry.title) (PID $($entry.pid))"
            Stop-Tree -ProcessId $entry.pid
        }
    }
    Remove-Item $pidFile -Force
}

# Sweep anything left over, matched on how it was launched.
$patterns = @(
    '*manage.py runserver*',
    '*manage.py run_ingestor*',
    '*manage.py run_worker*',
    '*manage.py simulate_device*',
    '*vite*'
)
$leftovers = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $commandLine = $_.CommandLine
        $_.ProcessId -ne $PID -and
        $commandLine -and
        ($patterns | Where-Object { $commandLine -like $_ })
    }

foreach ($process in $leftovers) {
    Write-Info "stopping stray $($process.Name) (PID $($process.ProcessId))"
    try {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        $stopped++
    } catch {
        # Already gone.
    }
}

Write-Info "stopped $stopped process(es)"
