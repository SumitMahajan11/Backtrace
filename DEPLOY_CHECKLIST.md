# Deployment Checklist: Free Split Deploy (Render + Neon + Upstash)

This checklist outlines the dashboard actions in order for deploying Backtrace to Render (Free Web Service), Neon (Free Serverless Postgres), and Upstash (Free Serverless Redis).

---

### Step 1: Neon Dashboard (Database)
1. Log into the [Neon Console](https://console.neon.tech).
2. Click **Create Project**. Name the project (e.g., `backtrace-db`).
3. Ensure Postgres version 16 is selected.
4. Copy the connection string provided in the dashboard.
   - Ensure the string format is `postgresql://<user>:<password>@<ep-hostname>.neon.tech/<dbname>?sslmode=require`.
   - **Do not commit or paste this connection string into source code**.

---

### Step 2: Upstash Dashboard (Redis Cache & Rate Limiting)
1. Log into the [Upstash Console](https://console.upstash.com).
2. Click **Create Database**.
3. Select **Redis**, choose the **Free** tier, and select the region closest to your Render region (e.g., US East / Ohio).
4. In the database details page, locate the **Node / Python / Redis Client** connection section.
5. Copy the TLS connection URL starting with `rediss://` (e.g., `rediss://default:<password>@<endpoint>.upstash.io:6379`).
   - Ensure the scheme is `rediss://` (with two 's's for SSL/TLS).
   - **Do not commit or paste this URL into source code**.

---

### Step 3: Render Dashboard (Web Service)
1. Log into the [Render Dashboard](https://dashboard.render.com).
2. Click **New +** -> **Web Service**.
3. Connect your GitHub repository (`Reverse` / `Backtrace`).
4. Configure the Web Service:
   - **Name**: `backtrace-app` (or chosen unique name).
   - **Branch**: `deploy-prep`
   - **Runtime**: **Docker**
   - **Instance Type**: **Free** ($0/mo, 0.1 CPU, 512 MB RAM).
     - *STOP*: If Render prompts for a credit card or requires selecting a paid plan, stop immediately.
5. Set the **Health Check Path**:
   - In **Advanced Settings**, set **Health Check Path** to: `/health`
6. Configure the Environment Variables:
   Add each of the following environment variable names. Paste values from your respective dashboard consoles and GitHub/Stripe settings. Do not include quotes around values.

   **Core Application & Server:**
   - `ENVIRONMENT` (set to `production`)
   - `APP_NAME` (e.g., `Backtrace`)
   - `DEBUG` (set to `false`)
   - `HOST` (set to `0.0.0.0`)
   - `PORT` (leave default or set to `10000`; Render injects `PORT` automatically)
   - `ENABLE_PUBLIC_LEADERBOARD` (set to `false`)

   **Database (Neon):**
   - `DATABASE_URL` (paste your Neon connection string with `?sslmode=require`)
   - `DB_POOL_SIZE` (recommend `5` for serverless / free pooler)
   - `DB_MAX_OVERFLOW` (recommend `5`)
   - `DB_POOL_TIMEOUT` (e.g., `30.0`)
   - `DB_POOL_RECYCLE` (e.g., `1800`)

   **Redis Cache & Rate Limiting (Upstash):**
   - `REDIS_URL` (paste your Upstash `rediss://...` URL)
   - `RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD` (e.g., `5`)
   - `RATE_LIMIT_REDIS_TIMEOUT` (recommend `1.5`)

   **Sandbox Execution Flag:**
   - `SANDBOX_ENABLED` (set to `false`)

   **Ingestion Limits:**
   - `MAX_REPO_MB` (e.g., `200`)

   **Authentication & JWT:**
   - `JWT_SECRET_KEY` (generate random 32+ character hex string, e.g. `openssl rand -hex 32`)
   - `JWT_ALGORITHM` (set to `HS256`)
   - `ACCESS_TOKEN_EXPIRE_MINUTES` (e.g., `15`)
   - `REFRESH_TOKEN_EXPIRE_DAYS` (e.g., `30`)

   **GitHub OAuth Application:**
   - `GITHUB_CLIENT_ID` (from GitHub Developer Settings -> OAuth Apps)
   - `GITHUB_CLIENT_SECRET` (from GitHub Developer Settings -> OAuth Apps)
   - `GITHUB_REDIRECT_URI` (set to `https://<render-url>/auth/github/callback`)
   - `GITHUB_FRONTEND_REDIRECT_URI` (set to `https://<render-url>/auth/github/callback`)

   **Stripe Billing (Must remain in TEST mode):**
   - `STRIPE_SECRET_KEY` (must start with `sk_test_...`)
   - `STRIPE_WEBHOOK_SECRET` (must start with `whsec_...`)
   - `STRIPE_PRICE_ID_PRO` (must start with `price_...`)
   - `STRIPE_SUCCESS_URL` (set to `https://<render-url>/dashboard?session_id={CHECKOUT_SESSION_ID}`)
   - `STRIPE_CANCEL_URL` (set to `https://<render-url>/dashboard`)
   - `FREE_TIER_MONTHLY_LIMIT` (e.g., `5`)

   **CORS Settings:**
   - `CORS_ALLOWED_ORIGINS` (set to `https://<render-url>`)

   **Optional Monitoring:**
   - `SENTRY_DSN`
   - `SENTRY_TRACES_SAMPLE_RATE`
   - `POSTHOG_API_KEY`
   - `POSTHOG_HOST`

7. Click **Deploy Web Service**.

---

### Step 4: GitHub Developer Settings (OAuth App)
1. Go to [GitHub Developer Settings -> OAuth Apps](https://github.com/settings/developers).
2. Select your OAuth Application (or create a new one).
3. Set **Homepage URL** to: `https://<render-url>`
4. Set **Authorization callback URL** to: `https://<render-url>/auth/github/callback`
   *(Confirmed from codebase route: `app/api/auth.py` mounted at `/auth/github/callback`)*
5. Click **Update application**.

---

### Step 5: Stripe Dashboard (Verification)
1. Go to [Stripe Dashboard](https://dashboard.stripe.com).
2. Verify that **Test mode** toggle is **ON** (orange badge in top bar).
3. Confirm API keys used in Render start with `sk_test_`. Do not switch to Live mode.
4. Add a test webhook pointing to `https://<render-url>/api/billing/webhook` with event `checkout.session.completed`.
