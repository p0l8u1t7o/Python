<#
.SYNOPSIS
    Opens the desktop simulator console (Sparkplug gateway + devices in one).
#>
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Virtualenv not found. Run .\scripts\dev.ps1 -Setup first.' }
& $python (Join-Path $root 'scripts\sim_console.py')
