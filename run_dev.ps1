# Local dev server launcher - sets correct env vars before starting uvicorn
$env:ENVIRONMENT = "development"
$env:GITHUB_REDIRECT_URI = "http://localhost:8000/auth/github/callback"
$env:DATABASE_URL = "sqlite:///./app.db"
Write-Host "Starting Backtrace dev server..." -ForegroundColor Cyan
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
