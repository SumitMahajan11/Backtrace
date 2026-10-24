# Keepalive Configuration
Ping https://<app>/healthz every 10 minutes using cron-job.org (free).
Set HTTP request method to GET with no database or auth overhead.
This prevents Render free-tier instances from spinning down and avoids cold starts.
