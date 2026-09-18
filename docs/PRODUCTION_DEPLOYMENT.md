# Production Deployment Guide & Architecture Runbook (Prompt 28)

This document specifies the complete cutover procedure and infrastructure architecture for deploying **Backtrace** to an actual production environment with automated TLS/SSL, containerized microservices, live Stripe billing, and distributed rate limiting.

---

## 1. Hosting Target & Sizing Analysis

Under the project's **"no money / minimal cost"** constraint, Backtrace requires hosting that can simultaneously run:
- **FastAPI ASGI Backend** (Python 3.13)
- **PostgreSQL 16** (relational storage & ledger)
- **Redis 7** (distributed rate limiting & cache)
- **Piston Sandbox** (multi-language code execution engine requiring Linux `cgroups v2` and `isolate`)
- **Nginx** (TLS termination and reverse proxy)

### Provider & Architecture Strategy

| Provider / Tier | Compute & Specs | Price | Architecture Decision |
| :--- | :--- | :--- | :--- |
| **Oracle Cloud Always Free (Ampere A1 ARM64)** *(Target)* | 4 OCPU (ARM64), 24 GB RAM, 200 GB NVMe | **$0.00 / mo** | **Selected Target**: Runs Nginx, Backtrace FastAPI backend, PostgreSQL 16, and Redis 7 with huge RAM and compute headroom at zero cost. **Piston execution is kept disabled/offline by default** on ARM64; the backend's graceful degradation returns verified 503 fast-fails for remote execution while structural Tier-3 grading, repo ingestion, and analysis continue to work completely. |
| **DuckDNS + Let's Encrypt** | Free Dynamic DNS Subdomain (`*.duckdns.org`) | **$0.00 / mo** | Automated Let's Encrypt TLS issuance via Certbot HTTP-01 challenge. |
| **Stripe Integration** | Test Mode (`sk_test_...`) | **$0.00 / mo** | Kept in test mode on deployed demo to prevent accidental financial charges. |

### Provisioning the Oracle ARM Host (Ubuntu 24.04 LTS)
```bash
# 1. Update OS and install Docker + Docker Compose
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y ca-certificates curl gnupg lsb-release ufw

# Install Docker CE
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 2. Configure Firewall (UFW)
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP (ACME challenge & HTTPS redirect)
sudo ufw allow 443/tcp   # HTTPS (TLS Traffic)
sudo ufw enable
```

---

## 2. Domain & DNS Configuration

1. **DNS Records**:
   - **Apex Domain (`backtrace.dev`)**: `A` record pointing to VPS Public IPv4 (`X.X.X.X`).
   - **API Subdomain (`api.backtrace.dev`)**: `CNAME` or `A` record pointing to VPS Public IPv4.
   - **IPv6 (Optional)**: `AAAA` records pointing to VPS Public IPv6.
2. **TTL**: Set initial TTL to `300` (5 minutes) during cutover to facilitate rapid rollback if needed.
3. **Bare IP Bootstrap**: During pre-DNS staging, the application can be accessed directly over HTTP on the VPS IP before acquiring certificates.

---

## 3. Automated Let's Encrypt TLS/SSL Setup

Certificates are issued via Certbot using the ACME Webroot challenge and mounted into the Nginx reverse proxy.

### Initial Certificate Issuance
```bash
# Obtain certificates before starting Nginx HTTPS listener
sudo docker run -it --rm --name certbot \
  -v backtrace_certbot_certs:/etc/letsencrypt \
  -v backtrace_certbot_www:/var/www/certbot \
  -p 80:80 \
  certbot/certbot certonly --standalone \
  -d backtrace.dev -d api.backtrace.dev \
  --email security@backtrace.dev --agree-tos --no-eff-email
```

### Automated Renewal (Cronjob)
Add to system crontab (`sudo crontab -e`):
```cron
# Run renewal check twice daily at 03:00 and 15:00 UTC
0 3,15 * * * docker run --rm -v backtrace_certbot_certs:/etc/letsencrypt -v backtrace_certbot_www:/var/www/certbot certbot/certbot renew --webroot -w /var/www/certbot --quiet && docker exec backtrace_nginx nginx -s reload
```

---

## 4. Stripe Live-Mode Cutover Runbook

> [!CAUTION]
> Live mode keys process **real financial transactions** and incur actual card charges.

### Cutover Checklist
1. **Switch API Keys in `.env.production`**:
   - Replace `STRIPE_SECRET_KEY=sk_test_...` with `STRIPE_SECRET_KEY=sk_live_...`.
   - Update `STRIPE_PRICE_ID_PRO` to the live price ID (e.g., `price_1UGWsi...`).
2. **Register Live Webhook in Stripe Dashboard**:
   - Navigate to: **Stripe Dashboard -> Developers -> Webhooks -> Add destination**.
   - Endpoint URL: `https://api.backtrace.dev/api/billing/webhook`.
   - Events to listen for:
     - `checkout.session.completed`
     - `customer.subscription.created`
     - `customer.subscription.updated`
     - `customer.subscription.deleted`
   - Copy the live Signing Secret into `STRIPE_WEBHOOK_SECRET=whsec_...` in `.env.production`.
3. **Verification**:
   - Perform a live $1.00 / test checkout using a real credit card.
   - Confirm the webhook receives the event, verifies the signature, and grants the user's `is_pro` status.
   - Issue an immediate refund from the Stripe Dashboard to reconcile.

---

## 5. Reverse Proxy & Security Hardening

The Nginx configuration (`docker/nginx/default.conf`) enforces:
- **HTTP -> HTTPS 301 Permanent Redirect**.
- **Modern TLS (1.2 & 1.3)** with hardened cipher suites.
- **HSTS (`Strict-Transport-Security`)**: Enforced with `includeSubDomains; preload` for 2 years.
- **Security Headers**: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`.
- **WebSocket & SSE Passthrough**: Upgrades connections for real-time progress streams.
- **Rate Limit Header Passthrough**: Forwards `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, and `Retry-After`.

---

## 6. Live Health Verification

The `/health` endpoint executes dynamic live probes against all backend subsystems:
- **Database**: Performs `SELECT 1` and measures latency on PostgreSQL.
- **Storage / Cache**: Verifies ORM table access and tracked repository count.
- **Pipeline Orchestrator**: Asserts all 8 language parsers are loaded.
- **Piston Sandbox**: Connects to the isolated Piston instance and checks runtime packages.
- **Redis Limiter**: Pings Redis and checks round-trip latency.

Expected 200 OK Health Payload:
```json
{
  "status": "healthy",
  "timestamp": "2026-09-18T14:30:00.000000Z",
  "version": "1.0.0",
  "checks": {
    "database": {
      "status": "healthy",
      "latency_ms": 1.42
    },
    "storage_cache": {
      "status": "healthy",
      "tracked_repos": 14
    },
    "pipeline_orchestrator": {
      "status": "healthy",
      "registered_parsers": 8
    },
    "piston_sandbox": {
      "status": "healthy",
      "is_available": true,
      "latency_ms": 2.15,
      "runtimes_count": 8
    },
    "redis": {
      "status": "healthy",
      "latency_ms": 0.85,
      "is_connected": true
    }
  }
}
```
