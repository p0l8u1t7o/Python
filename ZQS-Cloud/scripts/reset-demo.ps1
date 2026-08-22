<#
.SYNOPSIS
    Wipe the local database and rebuild the customer showcase from scratch.

.DESCRIPTION
    Stops the running stack, deletes the SQLite database, migrates, loads the
    catalogues, seeds the multi-site showcase tenant, generates a few days of
    history (so the savings figures exist on first open), then starts the
    stack. Devices stay offline until .\scripts\sim-console.ps1 brings them online.

.PARAMETER HistoryDays
    Days of synthetic history to generate. Default 7.

.PARAMETER NoStart
    Rebuild only; do not start the stack afterwards.

.EXAMPLE
    .\scripts\reset-demo.ps1
    .\scripts\reset-demo.ps1 -HistoryDays 14 -NoStart
#>
[CmdletBinding()]
param(
    [double]$HistoryDays = 7,
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "No virtualenv at $python; run .\scripts\dev.ps1 -Setup first." }

$env:PYTHONIOENCODING = 'utf-8'
$env:LOG_LEVEL = 'WARNING'

Write-Host '==> Stopping any running stack' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'stop.ps1') | Out-Null

$db = Join-Path $root 'data\zqs_cloud.sqlite3'
if ($env:DB_NAME) { $db = $env:DB_NAME }
foreach ($suffix in '', '-wal', '-shm', '-journal') {
    $path = "$db$suffix"
    if (Test-Path $path) { Remove-Item -Force $path }
}
Write-Host "==> Removed $db" -ForegroundColor Cyan

Push-Location $root
try {
    Write-Host '==> Migrating' -ForegroundColor Cyan
    & $python manage.py migrate --noinput
    if ($LASTEXITCODE -ne 0) { throw 'migrate failed' }

    Write-Host '==> Catalogues' -ForegroundColor Cyan
    & $python manage.py bootstrap
    if ($LASTEXITCODE -ne 0) { throw 'bootstrap failed' }

    Write-Host '==> Showcase tenant' -ForegroundColor Cyan
    & $python manage.py seed_showcase
    if ($LASTEXITCODE -ne 0) { throw 'seed_showcase failed' }

    if ($HistoryDays -gt 0) {
        Write-Host "==> $HistoryDays day(s) of history" -ForegroundColor Cyan
        & $python manage.py generate_history --days $HistoryDays --interval 300 --clear --with-faults
        if ($LASTEXITCODE -ne 0) { throw 'generate_history failed' }
    }
} finally {
    Pop-Location
}

if (-not $NoStart) {
    & (Join-Path $PSScriptRoot 'dev.ps1')
}
