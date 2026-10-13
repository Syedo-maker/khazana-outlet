<#
.SYNOPSIS
    One entry point for the containerised development environment.

.DESCRIPTION
    Everything runs inside Docker, so nothing depends on what is installed on
    this machine or on what its security policy allows to run.

    Dependencies live in the images, not in a cache that is rebuilt per run,
    so after the first build these commands start immediately and download
    nothing.

.PARAMETER Command
    build    Build the API and web images. Needed once, and after changing
             pyproject.toml or package.json.
    up       Start everything. API on 8000, web on 3000.
    down     Stop everything. Data in the volumes is kept.
    reset    Stop everything and delete the data volumes too.
    test     Run the test suite.
    pgtest   Run the PostgreSQL only tests, in a disposable database.
    lint     Lint and format check.
    fix      Apply the automatic lint and format fixes.
    types    Type check.
    check    lint, types and test together, which is what CI runs.
    evals    Run the AI eval suites against recorded fixtures.
    migrate  Apply database migrations.
    seed     Load the synthetic marketplace.
    logs     Follow the logs.
    shell    A shell inside the API container.
    status   What is running.

.EXAMPLE
    .\scripts\dev.ps1 build
    .\scripts\dev.ps1 up
    .\scripts\dev.ps1 check
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('build', 'up', 'down', 'reset', 'test', 'pgtest', 'lint', 'fix',
        'types', 'check', 'evals', 'migrate', 'seed', 'logs', 'shell', 'status')]
    [string]$Command = 'status',

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# The PostgreSQL only tests drop every table, so they get their own database.
# Pointing them at the working one destroys it.
$TestDbUrl = 'postgresql+psycopg://khazana:khazana@db:5432/khazana_test'

function Assert-Docker {
    # No 2>&1 here on purpose. See the note above the switch block: redirecting
    # a native command's stderr under ErrorActionPreference Stop turns any
    # warning docker prints into a terminating error, and this function would
    # then announce that Docker is not running while it is running fine. The
    # exit code is the only thing worth reading.
    $null = docker info --format '{{.ServerVersion}}'
    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Host 'Docker is not running.' -ForegroundColor Yellow
        Write-Host 'Start Docker Desktop, wait for the whale icon to settle, then try again.'
        exit 1
    }
}

function Invoke-Api {
    <#  Runs a command in the API container.

        Deliberately returns nothing. An earlier version returned the exit
        code, which meant every call site piped it to Out-Null to discard the
        return value, and that swallowed docker's own output too. A failing
        step then printed "failed" and nothing about why. The exit code is
        read from $LASTEXITCODE instead. #>
    param([string[]]$ApiArgs, [switch]$NoDeps)

    $run = @('compose', 'run', '--rm')
    if ($NoDeps) { $run += '--no-deps' }
    $run += 'api'
    & docker @run @ApiArgs
}

Assert-Docker

# Windows PowerShell 5.1 wraps a native command's stderr in error records when
# that stream is redirected, and under ErrorActionPreference Stop the first one
# terminates the script. docker compose writes all its progress to stderr, so
# "dev.ps1 up 2>&1 | Select-Object -Last 4" failed with NativeCommandError
# while every container started correctly. Nothing below depends on Stop, and
# every step checks $LASTEXITCODE itself.
$ErrorActionPreference = 'Continue'

switch ($Command) {
    'build' {
        Write-Host 'Building images. The first build downloads dependencies and takes a few minutes.' -ForegroundColor Cyan
        docker compose build @Rest
    }

    'up' {
        docker compose up -d @Rest
        if ($LASTEXITCODE -eq 0) {
            Write-Host ''
            Write-Host 'API  http://localhost:8000      docs at /docs' -ForegroundColor Green
            Write-Host 'Web  http://localhost:3000' -ForegroundColor Green
        }
    }

    'down' { docker compose down }

    'reset' {
        Write-Host 'This deletes the database and uploaded files.' -ForegroundColor Yellow
        $answer = Read-Host 'Type yes to continue'
        if ($answer -ne 'yes') { Write-Host 'Cancelled.'; exit 0 }
        docker compose down --volumes
    }

    'test' { Invoke-Api -NoDeps -ApiArgs (@('pytest') + $Rest); exit $LASTEXITCODE }

    'pgtest' {
        # Create the disposable database if it is not there yet. Already
        # existing is not an error worth showing.
        docker compose exec -T db createdb -U khazana khazana_test 2>$null | Out-Null
        docker compose run --rm -e "TEST_DATABASE_URL=$TestDbUrl" api `
            pytest tests/test_search_postgres.py @Rest
        exit $LASTEXITCODE
    }

    'lint' {
        Invoke-Api -NoDeps -ApiArgs @('ruff', 'check', '.')
        $a = $LASTEXITCODE
        Invoke-Api -NoDeps -ApiArgs @('ruff', 'format', '--check', '.')
        if ($a -ne 0 -or $LASTEXITCODE -ne 0) { exit 1 }
    }

    'fix' {
        Invoke-Api -NoDeps -ApiArgs @('ruff', 'check', '--fix', '.')
        Invoke-Api -NoDeps -ApiArgs @('ruff', 'format', '.')
    }

    'types' { Invoke-Api -NoDeps -ApiArgs @('mypy', 'src'); exit $LASTEXITCODE }

    'check' {
        $failed = $false
        foreach ($step in @(
                @{ Label = 'Lint'; Args = @('ruff', 'check', '.') },
                @{ Label = 'Format'; Args = @('ruff', 'format', '--check', '.') },
                @{ Label = 'Types'; Args = @('mypy', 'src') },
                @{ Label = 'Tests'; Args = @('pytest', '-q') }
            )) {
            Write-Host "== $($step.Label) ==" -ForegroundColor Cyan
            Invoke-Api -NoDeps -ApiArgs $step.Args
            if ($LASTEXITCODE -ne 0) {
                $failed = $true
                Write-Host "$($step.Label) failed" -ForegroundColor Red
            }
        }
        Write-Host ''
        if ($failed) {
            Write-Host 'Something needs attention. Try: .\scripts\dev.ps1 fix' -ForegroundColor Red
            exit 1
        }
        Write-Host 'All checks passed. Safe to push.' -ForegroundColor Green
    }

    'evals' {
        Invoke-Api -NoDeps -ApiArgs @('python', '-m', 'khazana.ai.evals.run', '--offline')
        exit $LASTEXITCODE
    }

    'migrate' { Invoke-Api -ApiArgs (@('alembic', 'upgrade', 'head') + $Rest); exit $LASTEXITCODE }

    'seed' { Invoke-Api -ApiArgs (@('python', '-m', 'khazana.seed') + $Rest); exit $LASTEXITCODE }

    'logs' { docker compose logs -f @Rest }

    'shell' { docker compose run --rm api bash }

    'status' {
        docker compose ps
        Write-Host ''
        Write-Host 'Commands: build, up, down, reset, test, pgtest, lint, fix, types,' -ForegroundColor DarkGray
        Write-Host '          check, evals, migrate, seed, logs, shell, status' -ForegroundColor DarkGray
        Write-Host 'Details:  Get-Help .\scripts\dev.ps1 -Full' -ForegroundColor DarkGray
    }
}
