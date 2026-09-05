#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Compatibility shim: the old scheduled-task installer now forwards to scripts\service.ps1.

.DESCRIPTION
    Kept so existing notes and shortcuts keep working. It registers the same scheduled task as before
    (service.ps1 install -Mode task). New installs should use the NSSM service instead:
        .\scripts\service.ps1 install            (or: vsctl service install)

.EXAMPLE
    .\scripts\install_service.ps1
    .\scripts\install_service.ps1 -User "PLANT\\vision" -Password **** -Port 8000
    .\scripts\install_service.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string]$TaskName = "VisionSequence",
    [string]$User = "SYSTEM",
    [string]$Password = "",
    [int]$Port = 8000,
    [string]$BindHost = "0.0.0.0",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$service = Join-Path $PSScriptRoot "service.ps1"
Write-Host "install_service.ps1 is a compatibility shim; prefer scripts\service.ps1 install (Windows service via NSSM)." -ForegroundColor DarkGray
if ($User -eq "SYSTEM") { $User = "LocalSystem" }
if ($Uninstall) {
    & $service uninstall -Mode task -Name $TaskName
} else {
    & $service install -Mode task -Name $TaskName -User $User -Password $Password -Port $Port -BindHost $BindHost
}
exit $LASTEXITCODE
