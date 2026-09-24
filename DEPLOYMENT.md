# Backtrace Public Deployment Guide (Cloudflare Tunnel)

This guide documents the complete procedure to run the full **Backtrace** stack locally and expose it securely to the public internet via **Cloudflare Tunnel** (Zero Trust), requiring no router port-forwarding, no static public IP, and no paid hosting infrastructure.

---

## 1. System Architecture

```
[ Public Internet Users ]
           │ (HTTPS / WSS)
           ▼
[ Cloudflare Global Anycast Edge ]
           │ (Secure Outbound Encrypted QUIC/HTTP2 Tunnel)
           ▼
[ backtrace_cloudflared ] (Docker Container)
           │ (Docker Internal Network: default)
           ▼
[ backtrace_production_app ] (FastAPI :8000)
    ├── [ backtrace_postgres ] (:5432 - Internal Only)
    ├── [ backtrace_redis ] (:6379 - Internal Only)
    └── [ backtrace_piston ] (:2000 - Cgroups v2 Isolated Sandbox)
```

### Key Security Properties
- **Zero Inbound Open Ports**: Cloudflare Tunnel establishes outbound connections to Cloudflare's edge. Your home/local IP and ports are never exposed to the WAN.
- **Fail-Closed Sandbox**: In `ENVIRONMENT=production`, local host execution fallback is disabled. Unsandboxed code execution on the host machine is completely prevented.
- **Automatic Reboot Recovery**: All persistent services use `restart: unless-stopped`, ensuring the entire stack recovers automatically across machine reboots.

---

## 2. Cloudflare Tunnel Setup (Step-by-Step)

Cloudflare Zero Trust Tunnels are free and do not require a credit card.

### Option A: Named Tunnel with Custom Domain (Recommended for Permanent Setup)

1. **Create Cloudflare Account**:
   - Sign up at [cloudflare.com](https://cloudflare.com) (free).
   - Add your domain to Cloudflare (or use a free domain).
2. **Access Zero Trust Dashboard**:
   - Navigate to [one.dash.cloudflare.com](https://one.dash.cloudflare.com/).
   - In the left sidebar, go to **Networks** -> **Tunnels**.
   - Click **Create a tunnel** (or **Add a tunnel**).
   - Select **Cloudflare Tunnel (cloudflared)** and click **Next**.
   - Enter a name (e.g. `backtrace-tunnel`) and click **Save tunnel**.
3. **Obtain Tunnel Token**:
   - In the "Install and run a connector" step, select **Docker**.
   - The dashboard will show a command like:
     ```bash
     docker run cloudflare/cloudflared:latest tunnel --no-autoupdate run --token eyJhIjoi...
     ```
   - Copy the long token string starting with `ey...`.
4. **Configure Public Hostname**:
   - Under the tunnel configuration in Zero Trust dashboard, go to the **Public Hostname** tab.
   - Click **Add a public hostname**.
   - Fill in:
     - **Subdomain**: `backtrace` (or whatever subdomain you prefer)
     - **Domain**: `yourdomain.com`
     - **Path**: (leave empty)
     - **Type**: `HTTP`
     - **URL**: `backtrace-app:8000`
   - Click **Save hostname**.
5. **Add Token to Environment**:
   - Open `.env.production` (and `.env`):
     ```bash
     CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoi...
     ```

---

### Option B: Quick Tunnel (Instant Testing / No Domain Needed)

For immediate ad-hoc testing without setting up a Cloudflare domain, you can spin up a temporary Quick Tunnel (`*.trycloudflare.com`):

```bash
docker compose run --rm cloudflared tunnel --url http://backtrace-app:8000
```
This prints a live public HTTPS URL in the console (e.g. `https://random-words-1234.trycloudflare.com`).

---

## 3. Production Environment Configuration (`.env.production`)

Update `.env.production` before launching:

```env
# Core Application Settings
ENVIRONMENT=production
APP_NAME=Backtrace
DEBUG=false
HOST=0.0.0.0
PORT=8000
ENABLE_PUBLIC_LEADERBOARD=false

# Cloudflare Tunnel Token
CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoi...

# Database & Redis (Internal Docker Network)
POSTGRES_USER=backtrace_admin
POSTGRES_PASSWORD=0d42c801c53e5cf45018fd9dfb1ad46ff07a2808f4485ab9
POSTGRES_DB=backtrace
DATABASE_URL=postgresql+psycopg2://backtrace_admin:0d42c801c53e5cf45018fd9dfb1ad46ff07a2808f4485ab9@postgres:5432/backtrace
REDIS_PASSWORD=599e74761be1ef737b46e972715988986029912e7d4d07df
REDIS_URL=redis://:599e74761be1ef737b46e972715988986029912e7d4d07df@redis:6379/0
PISTON_URL=http://piston:2000

# Authentication & JWT Secrets (256-bit cryptographically secure key)
JWT_SECRET_KEY=202caf63b76fc8edecad4b3b1783fe1b758a963e2af8810513f460ed9c82ff88
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=30

# URLs (Update <YOUR_TUNNEL_HOSTNAME> with your actual public hostname)
GITHUB_REDIRECT_URI=https://<YOUR_TUNNEL_HOSTNAME>/auth/github/callback
GITHUB_FRONTEND_REDIRECT_URI=https://<YOUR_TUNNEL_HOSTNAME>/auth/github/callback
STRIPE_SUCCESS_URL=https://<YOUR_TUNNEL_HOSTNAME>/dashboard?session_id={CHECKOUT_SESSION_ID}
STRIPE_CANCEL_URL=https://<YOUR_TUNNEL_HOSTNAME>/dashboard
CORS_ALLOWED_ORIGINS=https://<YOUR_TUNNEL_HOSTNAME>,http://localhost:8000,http://localhost:3000
```

---

## 4. Manual Actions Required by Repository Owner

> [!IMPORTANT]
> The following two steps require your personal account access on GitHub and Stripe:

### 1. GitHub OAuth Application Re-Registration
1. Go to [GitHub Developer Settings -> OAuth Apps](https://github.com/settings/developers).
2. Select your Backtrace OAuth Application.
3. Update the fields:
   - **Homepage URL**: `https://<YOUR_TUNNEL_HOSTNAME>`
   - **Authorization callback URL**: `https://<YOUR_TUNNEL_HOSTNAME>/auth/github/callback`
4. Click **Update application**.

### 2. Stripe Webhook & Redirect Verification
1. `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and `STRIPE_PRICE_ID_PRO` are intentionally left in **test mode** (`sk_test_...`) for safe staging.
2. In the [Stripe Dashboard](https://dashboard.stripe.com/test/webhooks), ensure your test webhook endpoint is set to:
   - `https://<YOUR_TUNNEL_HOSTNAME>/api/billing/webhook`

---

## 5. Starting, Stopping, and Managing the Stack

### Automated Launch Scripts
- **Linux / WSL / Cloud VPS**:
  ```bash
  chmod +x deploy.sh
  ./deploy.sh
  ```
- **Windows PowerShell**:
  ```powershell
  .\deploy.ps1
  ```

### Manual Docker Compose Commands
- **Start the Full Stack (Detached)**:
  ```bash
  docker compose up -d
  ```
- **Stop the Stack**:
  ```bash
  docker compose down
  ```
- **View Real-Time Logs**:
  ```bash
  # All services
  docker compose logs -f

  # Application backend
  docker compose logs -f backtrace-app

  # Cloudflare tunnel status
  docker compose logs -f cloudflared

  # Piston sandbox
  docker compose logs -f piston
  ```
- **Restart a Single Service**:
  ```bash
  docker compose restart cloudflared
  ```

---

## 6. Verification and Health Check

Once the stack is up, verify health over both the local interface and the public tunnel URL:

### Local Check:
```bash
curl http://localhost:8000/health
```

### Public Tunnel Check:
```bash
curl https://<YOUR_TUNNEL_HOSTNAME>/health
```

### Expected 200 OK Response:
```json
{
  "status": "healthy",
  "timestamp": "2026-09-24T07:28:49.198985+00:00",
  "version": "1.0.0",
  "checks": {
    "database": {
      "status": "healthy",
      "latency_ms": 3.13
    },
    "storage_cache": {
      "status": "healthy",
      "tracked_repos": 0
    },
    "pipeline_orchestrator": {
      "status": "healthy",
      "registered_parsers": 8
    },
    "piston_sandbox": {
      "status": "healthy",
      "is_available": true,
      "runtimes_count": 11
    },
    "redis": {
      "status": "healthy",
      "latency_ms": 8.82,
      "is_connected": true
    }
  }
}
```

---

## 7. Machine Reboot Behavior

Every service in `docker-compose.yml` (`backtrace-app`, `postgres`, `redis`, `piston`, `nginx`, `cloudflared`) has `restart: unless-stopped` specified.

- **On System Boot**: When the Docker daemon starts after a system restart, it will automatically restart all containers.
- **Dependency Handling**: `piston-init` executes once to verify runtime installations, and `backtrace-app` starts as soon as `postgres` and `redis` report healthy. `cloudflared` starts as soon as `backtrace-app` reports healthy.
- **Zero Manual Steps**: No interactive intervention is required after host reboot.
