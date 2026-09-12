[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

function Show-CommandVersion {
    param(
        [Parameter(Mandatory)]
        [string]$Name,
        [Parameter(Mandatory)]
        [string[]]$VersionArguments,
        [Parameter(Mandatory)]
        [bool]$Required
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        $status = if ($Required) { "MISSING (required)" } else { "not installed (optional)" }
        Write-Host ("{0,-12} {1}" -f $Name, $status)
        return $Required
    }

    $version = & $command.Source @VersionArguments 2>&1 | Select-Object -First 1
    Write-Host ("{0,-12} {1}" -f $Name, $version)
    return $false
}

$hasMissingRequired = $false

if (Test-Path -LiteralPath $venvPython) {
    $pythonVersion = & $venvPython --version 2>&1
    Write-Output ("{0,-12} {1}" -f "Python", $pythonVersion)
} else {
    Write-Output ("{0,-12} {1}" -f "Python", "MISSING .venv (required)")
    $hasMissingRequired = $true
}

$venvUv = Join-Path $projectRoot ".venv\Scripts\uv.exe"
if (Test-Path -LiteralPath $venvUv) {
    $uvVersion = & $venvUv --version 2>&1
    Write-Output ("{0,-12} {1}" -f "uv", $uvVersion)
} else {
    Write-Output ("{0,-12} {1}" -f "uv", "MISSING in .venv (required)")
    $hasMissingRequired = $true
}

$nodeMissing = Show-CommandVersion -Name "node" -VersionArguments @("--version") -Required $true
$npmMissing = Show-CommandVersion -Name "npm" -VersionArguments @("--version") -Required $true
$gitMissing = Show-CommandVersion -Name "git" -VersionArguments @("--version") -Required $true
$hasMissingRequired = $hasMissingRequired -or $nodeMissing -or $npmMissing -or $gitMissing

Write-Output ""
Write-Output "Phase-specific workers (not required for the current baseline):"
[void](Show-CommandVersion -Name "cmake" -VersionArguments @("--version") -Required $false)
[void](Show-CommandVersion -Name "blender" -VersionArguments @("--version") -Required $false)
[void](Show-CommandVersion -Name "docker" -VersionArguments @("--version") -Required $false)

$gitRoot = & git -C $projectRoot rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Output ""
    Write-Output "Git root: $gitRoot"
    if ((Resolve-Path $gitRoot).Path -ne (Resolve-Path $projectRoot).Path) {
        Write-Output "Git scope: parent repository retained; commands must remain path-limited to this project."
    }
}

if ($hasMissingRequired) {
    exit 1
}
