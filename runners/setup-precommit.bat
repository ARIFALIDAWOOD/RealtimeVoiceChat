@echo off
REM Setup script for pre-commit hooks using uv
REM Run this after installing the project dependencies

setlocal enabledelayedexpansion

:: Set current directory
cd /d %~dp0

echo Setting up pre-commit hooks with uv...
echo.

REM Check if .venv exists (uv default)
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

REM Check if uv is available
where uv >nul 2>&1
if errorlevel 1 (
    echo WARNING: uv not found in PATH. Trying to use Python's uv...
    python -m uv --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: uv is not available. Please install uv first.
        echo   Install with: pip install uv
        pause
        exit /b 1
    )
    set UV_CMD=python -m uv
) else (
    set UV_CMD=uv
)

REM Install pre-commit and dev dependencies using uv
echo Installing pre-commit and development dependencies with uv...
%UV_CMD% pip install -r requirements-dev.txt
if errorlevel 1 (
    echo ERROR: Failed to install development dependencies.
    pause
    exit /b 1
)

REM Initialize secrets baseline (required for detect-secrets)
echo.
echo Initializing detect-secrets baseline...
if not exist .secrets.baseline (
    echo Creating initial secrets baseline...
    python -m detect_secrets scan code/ --baseline .secrets.baseline
    if errorlevel 1 (
        echo WARNING: Initial scan failed. Creating empty baseline...
        echo {} > .secrets.baseline
    )
) else (
    echo Updating existing secrets baseline...
    python -m detect_secrets scan code/ --baseline .secrets.baseline
    if errorlevel 1 (
        echo WARNING: detect-secrets scan encountered issues. Check the output above.
        echo You may need to manually review and update .secrets.baseline
    )
)

REM Install pre-commit hooks
echo.
echo Installing pre-commit hooks into .git/hooks/...
pre-commit install
if errorlevel 1 (
    echo ERROR: Failed to install pre-commit hooks.
    pause
    exit /b 1
)

echo.
echo Pre-commit hooks installed successfully!
echo.
echo To test the hooks manually, run:
echo   pre-commit run --all-files
echo.
echo Hooks will now run automatically before each commit.
echo.
pause
