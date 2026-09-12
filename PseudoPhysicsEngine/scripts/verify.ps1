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

Push-Location $projectRoot
try {
    & $uv lock --check
    Assert-LastExitCode "uv lock check"
    & $uv run ruff format --check .
    Assert-LastExitCode "Ruff format check"
    & $uv run ruff check .
    Assert-LastExitCode "Ruff lint"
    & $uv run mypy apps packages tests scripts migrations
    Assert-LastExitCode "mypy"
    & $uv run pytest
    Assert-LastExitCode "pytest"
    & $uv run python scripts/export_schemas.py
    Assert-LastExitCode "Schema export"

    Push-Location "apps/web"
    try {
        npm run generate:types
        Assert-LastExitCode "Web contract generation"
        npm run lint
        Assert-LastExitCode "Web lint"
        npm run build
        Assert-LastExitCode "Web build"
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}
