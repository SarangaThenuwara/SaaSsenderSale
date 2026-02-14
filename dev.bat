@echo off
echo Starting SaaS Sender on 0.0.0.0 for Local/Public IP access...
set PORT=8000
uvicorn app.main:app --host 0.0.0.0 --port %PORT% --reload
pause
