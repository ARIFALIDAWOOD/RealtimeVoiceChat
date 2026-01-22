@echo off
REM Startup script for server.py in reload mode
cd /d "%~dp0..\code"
python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
pause
