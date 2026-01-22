@echo off
REM Manual secret scanning script for Windows using uv
REM Use this to scan for hardcoded credentials without git-secrets

setlocal enabledelayedexpansion

:: Set current directory
cd /d %~dp0

echo Scanning for potential secrets in code files...
echo.

REM Check if .venv exists and activate if needed
if not exist .venv (
    echo ERROR: Virtual environment not found!
    echo Please run install.bat first to create the virtual environment.
    pause
    exit /b 1
)

REM Activate virtual environment if not already activated
if "%VIRTUAL_ENV%"=="" (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
    if errorlevel 1 (
        echo ERROR: Failed to activate virtual environment.
        pause
        exit /b 1
    )
)

REM Check if detect-secrets is available
python -m detect_secrets --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: detect-secrets not installed.
    echo Install it with: uv pip install -r requirements-dev.txt
    echo Or run: setup-precommit.bat
    pause
    exit /b 1
)

REM Scan Python files in code/ directory
echo Scanning Python files...
python -m detect_secrets scan code/ --baseline .secrets.baseline

if errorlevel 1 (
    echo.
    echo WARNING: Potential secrets found! Review the output above.
    echo To update baseline: python -m detect_secrets scan --baseline .secrets.baseline code/
    pause
    exit /b 1
) else (
    echo.
    echo Scan complete. No new secrets detected.
)

echo.
echo Checking for common secret patterns using findstr...
echo.

REM Search for common secret patterns
findstr /s /i /n "password\|api_key\|secret\|token\|credential" code\*.py 2>nul
if errorlevel 1 (
    echo No obvious password/key/secret patterns found in .py files.
) else (
    echo WARNING: Found potential credential patterns. Review the matches above.
)

echo.
echo Secret scan complete.
pause
