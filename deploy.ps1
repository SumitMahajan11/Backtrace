# ==============================================================================
# Backtrace Production Deployment & Health Verification Script (PowerShell)
# ==============================================================================
# Starts all services via Docker Compose in proper dependency order:
# postgres -> redis -> piston -> piston-init -> backtrace-app -> nginx -> cloudflared
# ==============================================================================

$ErrorActionPreference = "Stop"

$EnvFile = ".env.production"
if (-not (Test-Path $EnvFile)) {
    Write-Error "Error: $EnvFile not found! Please create it before deploying."
    exit 1
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "🚀 Starting Backtrace Stack with Cloudflare Tunnel" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# Check for Cloudflare Tunnel token
$tokenLine = Get-Content $EnvFile | Where-Object { $_ -match "^CLOUDFLARE_TUNNEL_TOKEN=ey" }
if ($tokenLine) {
    Write-Host "✅ Cloudflare Tunnel Token detected in $EnvFile" -ForegroundColor Green
} else {
    Write-Host "⚠️  Note: CLOUDFLARE_TUNNEL_TOKEN is not set or empty in $EnvFile." -ForegroundColor Yellow
    Write-Host "   The stack will start, but cloudflared will wait for a valid token." -ForegroundColor Yellow
}

# Bring up the compose stack
Write-Host "📦 Orchestrating Docker Compose services..." -ForegroundColor Cyan
docker compose -f docker-compose.yml up -d

Write-Host "`n⏳ Waiting for backtrace-app health check to report healthy..." -ForegroundColor Cyan
$MaxRetries = 30
$RetryCount = 0
$Healthy = $false

while ($RetryCount -lt $MaxRetries -and -not $Healthy) {
    Start-Sleep -Seconds 3
    $RetryCount++
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method Get -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($response -and $response.status -eq "healthy") {
            $Healthy = $true
            break
        }
    } catch {
        Write-Host "   Checking /health (attempt $RetryCount/$MaxRetries)..."
    }
}

if (-not $Healthy) {
    Write-Host "❌ Health check timed out after 90 seconds. Checking container status:" -ForegroundColor Red
    docker compose ps
    Write-Host "`n🔍 Recent application logs:" -ForegroundColor Red
    docker compose logs --tail=30 backtrace-app
    exit 1
}

Write-Host "`n========================================================" -ForegroundColor Green
Write-Host "✅ Stack is Healthy & Operational!" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
python -c "import urllib.request, json; resp = urllib.request.urlopen('http://127.0.0.1:8000/health'); print(json.dumps(json.loads(resp.read().decode()), indent=2))"

Write-Host "`n📊 Container Status:" -ForegroundColor Cyan
docker compose ps

Write-Host "`n🌐 Cloudflare Tunnel Status:" -ForegroundColor Cyan
docker compose logs --tail=10 cloudflared
Write-Host "========================================================" -ForegroundColor Cyan
