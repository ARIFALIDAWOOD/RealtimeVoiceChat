@echo off
REM Startup script for server.py in reload mode (using uv)
cd /d "%~dp0..\code"
uv run uvicorn server:app --host 0.0.0.0 --port 8000 --reload
pause
