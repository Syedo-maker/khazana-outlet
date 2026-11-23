<#
.SYNOPSIS
    Lint, format and type check the API.

.DESCRIPTION
    Runs the pinned ruff and mypy natively when they work, which is fast and
    needs no network. Falls back to Linux containers when they do not, which
    happens when Windows Smart App Control blocks unsigned executables.

    You should not have to care which path runs. The script picks.

    The container fallback caches downloaded Python packages in a named Docker
    volume, so the slow first run happens once rather than every time.

.PARAMETER Fix
    Apply fixes instead of only reporting them.

.PARAMETER Types
    Also run mypy.

.PARAMETER Docker
    Force the container path even when the native tools work. Useful for
    checking that the containers still agree with CI.

.EXAMPLE
    .\scripts\lint.ps1
    Lint and format check.

.EXAMPLE
    .\scripts\lint.ps1 -Fix -Types
    Fix what can be fixed, then type check.
#>

[CmdletBinding()]
param(
    [switch]$Fix,
    [switch]$Types,
    [switch]$Docker
)

$ErrorActionPreference = 'Stop'

# Keep in step with apps/api/pyproject.toml, which pins the same versions.
$RuffImage = 'ghcr.io/astral-sh/ruff:0.16.10'
$PythonImage = 'python:3.11-slim'
$PipCacheVolume = 'khazana-pip-cache'

$repoRoot = Split-Path -Parent $PSScriptRoot
$apiPath = Join-Path $repoRoot 'apps\api'
$venvPython = Join-Path $apiPath '.venv\Scripts\python.exe'

if (-not (Test-Path $apiPath)) {
    Write-Error "Could not find $apiPath. Run this from inside the repository."
}

$script:failed = $false

function Test-NativeTools {
    <#  Can ruff and mypy actually run on this machine?
        Smart App Control blocks unsigned executables, and when it does these
        fail with an Application Control error rather than a normal one. #>
    if (-not (Test-Path $venvPython)) { return $false }
    try {
        & $venvPython -m ruff --version *> $null
        if ($LASTEXITCODE -ne 0) { return $false }
        & $venvPython -m mypy --version *> $null
        return $LASTEXITCODE -eq 0
    }
    catch { return $false }
}

function Invoke-Step {
    param([string]$Label, [scriptblock]$Action)

    Write-Host "== $Label ==" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        $script:failed = $true
        Write-Host "$Label failed" -ForegroundColor Red
    }
}

# ----------------------------------------------------------------- native

$useNative = (-not $Docker) -and (Test-NativeTools)

if ($useNative) {
    Write-Host 'Running the pinned tools natively.' -ForegroundColor DarkGray
    Push-Location $apiPath
    try {
        if ($Fix) {
            Invoke-Step 'Lint, fixing what it can' { & $venvPython -m ruff check --fix . }
            Invoke-Step 'Formatting' { & $venvPython -m ruff format . }
        }
        else {
            Invoke-Step 'Lint' { & $venvPython -m ruff check . }
            Invoke-Step 'Format check' { & $venvPython -m ruff format --check . }
        }

        if ($Types) {
            Invoke-Step 'Type check' { & $venvPython -m mypy src }
        }
    }
    finally { Pop-Location }
}
else {

    # ------------------------------------------------------------- container

    if ($Docker) {
        Write-Host 'Container path requested.' -ForegroundColor DarkGray
    }
    else {
        Write-Host 'Native ruff or mypy cannot run here, using containers instead.' -ForegroundColor Yellow
    }

    try {
        docker info --format '{{.ServerVersion}}' 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'engine not reachable' }
    }
    catch {
        Write-Host ''
        Write-Host 'Docker is not running.' -ForegroundColor Yellow
        Write-Host 'Start Docker Desktop, wait for the whale icon to settle, then run this again.'
        exit 1
    }

    $mount = "${apiPath}:/io"

    if ($Fix) {
        Invoke-Step 'Lint, fixing what it can' {
            docker run --rm -v $mount -w /io $RuffImage check --fix .
        }
        Invoke-Step 'Formatting' { docker run --rm -v $mount -w /io $RuffImage format . }
    }
    else {
        Invoke-Step 'Lint' { docker run --rm -v $mount -w /io $RuffImage check . }
        Invoke-Step 'Format check' { docker run --rm -v $mount -w /io $RuffImage format --check . }
    }

    if ($Types) {
        # A named volume keeps the downloaded wheels between runs, so the slow
        # first run happens once instead of every time. The longer timeout and
        # extra retries are for connections where a 100 MB download does not
        # reliably complete in pip's default 15 seconds per read.
        docker volume create $PipCacheVolume 2>&1 | Out-Null

        Write-Host '== Type check in a container ==' -ForegroundColor Cyan
        Write-Host '   First run downloads dependencies and can take a few minutes.' -ForegroundColor DarkGray
        Write-Host '   Later runs reuse the cache and are quick.' -ForegroundColor DarkGray

        docker run --rm `
            -v $mount -w /io `
            -v "${PipCacheVolume}:/root/.cache/pip" `
            -e PIP_DEFAULT_TIMEOUT=120 `
            -e PIP_RETRIES=10 `
            -e PIP_DISABLE_PIP_VERSION_CHECK=1 `
            -e PIP_ROOT_USER_ACTION=ignore `
            $PythonImage `
            bash -c "pip install -q -e '.[dev]' && mypy src"

        if ($LASTEXITCODE -ne 0) {
            $script:failed = $true
            Write-Host ''
            Write-Host 'Type check failed.' -ForegroundColor Red
            Write-Host 'If that was a network timeout rather than a type error, run it again:' -ForegroundColor Yellow
            Write-Host 'the packages it managed to download are cached, so each attempt gets further.'
        }
    }
}

Write-Host ''
if ($script:failed) {
    Write-Host 'Something needs attention. Run with -Fix to apply the automatic fixes.' -ForegroundColor Red
    exit 1
}
Write-Host 'All checks passed. Safe to push.' -ForegroundColor Green
