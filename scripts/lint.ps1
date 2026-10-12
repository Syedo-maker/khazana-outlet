<#
.SYNOPSIS
    Lint, format and type check the API without needing ruff to run on Windows.

.DESCRIPTION
    Smart App Control on this machine blocks unsigned executables, which is
    what ruff, mypy and black ship as. They cannot run directly here.

    This script runs the same tools inside Linux containers, where Windows
    application control does not apply. It pins the same ruff version as CI,
    so a pass here means a pass there.

    It also does not need `make`, which is not installed on this machine.

.PARAMETER Fix
    Apply fixes instead of only reporting them.

.PARAMETER Types
    Also run mypy. Slower, because it installs the dependencies first.

.EXAMPLE
    .\scripts\lint.ps1
    Check lint and formatting.

.EXAMPLE
    .\scripts\lint.ps1 -Fix
    Fix what can be fixed automatically.

.EXAMPLE
    .\scripts\lint.ps1 -Types
    Check lint, formatting and types.
#>

[CmdletBinding()]
param(
    [switch]$Fix,
    [switch]$Types
)

$ErrorActionPreference = 'Stop'

# Keep this in step with .github/workflows/ci.yml and apps/api/pyproject.toml.
$RuffImage = 'ghcr.io/astral-sh/ruff:0.8.4'

$repoRoot = Split-Path -Parent $PSScriptRoot
$apiPath = Join-Path $repoRoot 'apps\api'

if (-not (Test-Path $apiPath)) {
    Write-Error "Could not find $apiPath. Run this from inside the repository."
}

# Fail early with something actionable rather than a raw Docker error.
try {
    docker info --format '{{.ServerVersion}}' 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'engine not reachable' }
}
catch {
    Write-Host ''
    Write-Host 'Docker is not running.' -ForegroundColor Yellow
    Write-Host 'Start Docker Desktop, wait until its whale icon stops animating, then run this again.'
    Write-Host ''
    Write-Host 'Why Docker: ruff cannot run directly on this machine because Smart App'
    Write-Host 'Control blocks unsigned executables. Inside a Linux container it runs fine.'
    exit 1
}

$mount = "${apiPath}:/io"
$failed = $false

function Invoke-Ruff {
    param([string[]]$RuffArgs, [string]$Label)

    Write-Host "== $Label ==" -ForegroundColor Cyan
    docker run --rm -v $mount -w /io $RuffImage @RuffArgs
    if ($LASTEXITCODE -ne 0) {
        $script:failed = $true
        Write-Host "$Label failed" -ForegroundColor Red
    }
}

if ($Fix) {
    Invoke-Ruff -RuffArgs @('check', '--fix', '.') -Label 'Lint, fixing what it can'
    Invoke-Ruff -RuffArgs @('format', '.') -Label 'Formatting'
}
else {
    Invoke-Ruff -RuffArgs @('check', '.') -Label 'Lint'
    Invoke-Ruff -RuffArgs @('format', '--check', '.') -Label 'Format check'
}

if ($Types) {
    Write-Host '== Type check, this installs dependencies first ==' -ForegroundColor Cyan
    docker run --rm -v $mount -w /io python:3.11-slim bash -c "pip install -q -e '.[dev]' && mypy src"
    if ($LASTEXITCODE -ne 0) {
        $failed = $true
        Write-Host 'Type check failed' -ForegroundColor Red
    }
}

Write-Host ''
if ($failed) {
    Write-Host 'Something needs attention. Run with -Fix to apply the automatic fixes.' -ForegroundColor Red
    exit 1
}

Write-Host 'All checks passed. Safe to push.' -ForegroundColor Green
