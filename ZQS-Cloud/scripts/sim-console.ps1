<#
.SYNOPSIS
    Opens the standalone device simulator console.

.DESCRIPTION
    The simulator is an independent MQTT client: it only knows the broker and
    the gateways/devices described in simulator\fleet.json, and talks to the
    platform purely over Sparkplug B. If no fleet.json exists yet, one is
    exported from the platform's registry first (the same description a
    vendor would be handed).

.PARAMETER Config
    Path to a fleet.json. Default: simulator\fleet.json.

.PARAMETER Export
    Re-export fleet.json from the platform before opening the console.
#>
param(
    [string]$Config = '',
    [switch]$Export
)
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Virtualenv not found. Run .\scripts\dev.ps1 -Setup first.' }
if (-not $Config) { $Config = Join-Path $root 'simulator\fleet.json' }

$env:PYTHONIOENCODING = 'utf-8'
if ($Export -or -not (Test-Path $Config)) {
    Push-Location $root
    try { & $python manage.py export_fleet_config --out $Config } finally { Pop-Location }
}
& $python -m simulator.console -c $Config
