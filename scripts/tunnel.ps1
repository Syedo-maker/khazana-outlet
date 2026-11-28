<#
.SYNOPSIS
    Run the stack on this laptop and share it through a free Cloudflare quick tunnel.

.DESCRIPTION
    For showing the demo to a brand from your own machine. Starts the
    cloudflared container first, reads the random trycloudflare.com address it
    is given, then starts the rest of the stack with that address as the public
    URL, so invite links and the API's own links point at it.

    Needs Docker Desktop running and a .env.staging file (copy
    .env.staging.example). No Cloudflare account is needed. The address
    changes every time the tunnel starts.

.PARAMETER EnvFile
    The env file to use. Defaults to .env.staging, a demo with sample accounts.

.PARAMETER Down
    Stop the tunnel and the stack.

.PARAMETER Seed
    Load the demo data after starting. The scheduler reseeds a demo nightly,
    so this is only needed the first time.

.EXAMPLE
    .\scripts\tunnel.ps1 -Seed
#>
param(
    [string]$EnvFile = ".env.staging",
    [switch]$Down,
    [switch]$Seed
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$files = @("-f", "docker-compose.prod.yml", "-f", "docker-compose.tunnel.yml", "--env-file", $EnvFile)

if (-not (Test-Path $EnvFile)) {
    Write-Host "No $EnvFile here. Copy .env.staging.example to $EnvFile first."
    exit 1
}

if ($Down) {
    # Compose needs a value to read the file; it is not used when stopping.
    $env:PUBLIC_URL = "https://stopping.invalid"
    docker compose @files down
    exit $LASTEXITCODE
}

# 1. The tunnel alone. Compose reads every service's settings even to start
#    one, so a placeholder stands in until the real address is known.
$env:PUBLIC_URL = "https://pending.invalid"
docker compose @files up -d cloudflared
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$address = $null
for ($i = 0; $i -lt 60 -and -not $address; $i++) {
    Start-Sleep -Seconds 2
    $logs = docker compose @files logs cloudflared 2>&1 | Out-String
    $found = [regex]::Match($logs, "https://[a-z0-9-]+\.trycloudflare\.com")
    if ($found.Success) { $address = $found.Value }
}
if (-not $address) {
    Write-Host "Cloudflare did not hand out an address within two minutes."
    Write-Host "See: docker compose -f docker-compose.prod.yml -f docker-compose.tunnel.yml logs cloudflared"
    exit 1
}

# 2. Everything else, with the tunnel's address as the public URL.
$env:PUBLIC_URL = $address
docker compose @files up -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ready = $false
for ($i = 0; $i -lt 90 -and -not $ready; $i++) {
    Start-Sleep -Seconds 2
    try {
        $answer = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://localhost:8080/api/ready"
        $ready = $answer.StatusCode -eq 200
    } catch {
        $ready = $false
    }
}
if (-not $ready) {
    Write-Host "The stack did not become ready within three minutes. See: docker compose ps"
    exit 1
}

if ($Seed) {
    docker compose @files exec -T api python -m khazana.seed --reset
}

Write-Host ""
Write-Host "Shared at: $address"
Write-Host "On this laptop: http://localhost:8080"
Write-Host "Stop with: .\scripts\tunnel.ps1 -Down"
