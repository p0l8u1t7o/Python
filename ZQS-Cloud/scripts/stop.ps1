<#
.SYNOPSIS
    Stops everything scripts\dev.ps1 started.

.DESCRIPTION
    Uses the PID file written at launch. Falls back to matching command lines,
    so a stack started before the PID file existed - or one whose file was
    deleted - can still be stopped.

    One process-table snapshot, one kill call. The previous version walked the
    process tree with a CIM query per node, which took seconds per service;
    everything it needs is in a single Win32_Process listing.
#>
[CmdletBinding()]
param([switch]$Quiet)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$pidFile = Join-Path $root '.dev-pids.json'

function Write-Info($message) { if (-not $Quiet) { Write-Host $message } }

# One snapshot of the whole table; every lookup below is in-memory.
$all = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Select-Object ProcessId, ParentProcessId, Name, CommandLine

$childrenOf = @{}
foreach ($process in $all) {
    $parent = [int]$process.ParentProcessId
    if (-not $childrenOf.ContainsKey($parent)) { $childrenOf[$parent] = [System.Collections.Generic.List[int]]::new() }
    $childrenOf[$parent].Add([int]$process.ProcessId)
}

# Roots: the PID file's launcher windows, plus anything matching how dev.ps1
# launches its services (covers a deleted PID file or a pre-PID-file stack).
$patterns = @(
    '*manage.py runserver*',
    '*manage.py run_ingestor*',
    '*manage.py run_worker*',
    '*manage.py run_pipeline*',
    '*manage.py run_broker*',
    '*manage.py run_workflows*',
    '*manage.py simulate_device*',
    '*vite*'
)

$roots = [System.Collections.Generic.HashSet[int]]::new()

if (Test-Path $pidFile) {
    $entries = Get-Content $pidFile -Raw | ConvertFrom-Json
    foreach ($entry in @($entries)) { [void]$roots.Add([int]$entry.pid) }
    Remove-Item $pidFile -Force
}

foreach ($process in $all) {
    if ($process.ProcessId -eq $PID) { continue }
    $commandLine = $process.CommandLine
    if (-not $commandLine) { continue }
    foreach ($pattern in $patterns) {
        if ($commandLine -like $pattern) { [void]$roots.Add([int]$process.ProcessId); break }
    }
}

# Expand each root to its whole descendant tree, killing children first so a
# launcher window cannot orphan its python/node child.
$ordered = [System.Collections.Generic.List[int]]::new()
$seen = [System.Collections.Generic.HashSet[int]]::new()

function Add-Tree {
    param([int]$ProcessId)
    if (-not $seen.Add($ProcessId)) { return }
    if ($childrenOf.ContainsKey($ProcessId)) {
        foreach ($child in $childrenOf[$ProcessId]) { Add-Tree -ProcessId $child }
    }
    $ordered.Add($ProcessId)
}

foreach ($processId in $roots) { Add-Tree -ProcessId $processId }

$stopped = 0
foreach ($processId in $ordered) {
    try {
        Stop-Process -Id $processId -Force -ErrorAction Stop
        $stopped++
    } catch {
        # Already gone.
    }
}

Write-Info "stopped $stopped process(es)"
