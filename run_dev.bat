@echo off  
set ENVIRONMENT=development  
set GITHUB_REDIRECT_URI=http://localhost:8000/auth/github/callback  
set DATABASE_URL=sqlite:///./app.db  
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 
