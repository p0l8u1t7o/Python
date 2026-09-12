[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$uv = Join-Path $projectRoot ".venv\Scripts\uv.exe"

function Assert-LastExitCode {
    param([Parameter(Mandatory)][string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath $uv)) {
    throw "uv is missing. Run: .\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt"
}

$previousUvLinkMode = $env:UV_LINK_MODE

Push-Location $projectRoot
try {
    $env:UV_LINK_MODE = "copy"
    New-Item -ItemType Directory -Force -Path ".local/data" | Out-Null
    & $uv sync --all-packages
    Assert-LastExitCode "uv sync"
    & $uv run alembic upgrade head
    Assert-LastExitCode "Alembic upgrade"
    & $uv run python scripts/export_schemas.py
    Assert-LastExitCode "Schema export"
} finally {
    if ($null -eq $previousUvLinkMode) {
        Remove-Item Env:UV_LINK_MODE -ErrorAction SilentlyContinue
    } else {
        $env:UV_LINK_MODE = $previousUvLinkMode
    }
    Pop-Location
}
