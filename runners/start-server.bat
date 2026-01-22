@echo off
REM Startup script for server.py in reload mode (using uv)

REM Kill any existing process on port 8000
echo Checking for existing processes on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000.*LISTENING"') do (
    echo Killing existing process with PID %%a on port 8000...
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

cd /d "%~dp0..\code"
uv run uvicorn server:app --host 0.0.0.0 --port 8000 --reload
pause
