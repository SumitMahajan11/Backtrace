#!/usr/bin/env bash
# ==============================================================================
# Backtrace Production Deployment & Health Verification Script
# ==============================================================================
# Starts all services via Docker Compose in proper dependency order:
# postgres -> redis -> piston -> piston-init -> backtrace-app -> nginx -> cloudflared
# ==============================================================================

set -euo pipefail

ENV_FILE=".env.production"
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: $ENV_FILE not found! Please create it before deploying."
    exit 1
fi

echo "========================================================"
echo "🚀 Starting Backtrace Stack with Cloudflare Tunnel"
echo "========================================================"

# Check for Cloudflare Tunnel token
if grep -q "^CLOUDFLARE_TUNNEL_TOKEN=ey" "$ENV_FILE"; then
    echo "✅ Cloudflare Tunnel Token detected in $ENV_FILE"
else
    echo "⚠️  Note: CLOUDFLARE_TUNNEL_TOKEN is not set or empty in $ENV_FILE."
    echo "   The stack will start, but cloudflared will wait for a valid token."
fi

# Bring up the compose stack
echo "📦 Orchestrating Docker Compose services..."
docker compose -f docker-compose.yml up -d

echo ""
echo "⏳ Waiting for backtrace-app health check to report healthy..."
MAX_RETRIES=30
RETRY_COUNT=0
HEALTH_URL="http://127.0.0.1:8000/health"

until curl -s -f "$HEALTH_URL" > /dev/null 2>&1 || [ $RETRY_COUNT -ge $MAX_RETRIES ]; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "   Checking /health (attempt $RETRY_COUNT/$MAX_RETRIES)..."
    sleep 3
done

if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
    echo "❌ Health check timed out after 90 seconds. Checking container status:"
    docker compose ps
    echo ""
    echo "🔍 Recent application logs:"
    docker compose logs --tail=30 backtrace-app
    exit 1
fi

echo ""
echo "========================================================"
echo "✅ Stack is Healthy & Operational!"
echo "========================================================"
curl -s "$HEALTH_URL" | python3 -m json.tool || curl -s "$HEALTH_URL"
echo ""
echo "📊 Container Status:"
docker compose ps
echo ""
echo "🌐 Cloudflare Tunnel Status:"
docker compose logs --tail=10 cloudflared || true
echo "========================================================"
