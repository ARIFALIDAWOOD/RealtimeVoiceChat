@echo off

setlocal enabledelayedexpansion

:: Set current directory
cd /d %~dp0

echo Starting installation process...
echo.
echo Detecting CUDA version...
nvcc --version | findstr /C:"release"
echo.

:: Remove old venv if it exists
if exist .venv (
    echo Removing old virtual environment...
    rmdir /S /Q .venv
)

:: Create virtual environment with uv using Python 3.10
echo Creating virtual environment with uv (Python 3.10)...
uv venv --python 3.10
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment. Make sure Python 3.10 is installed.
    echo You can install it with: uv python install 3.10
    pause
    exit /b 1
)

:: Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat

:: Install PyTorch (version compatible with DeepSpeed wheel)
echo.
echo Installing PyTorch 2.5.1 with CUDA 12.1 (compatible with bundled DeepSpeed wheel)...
uv pip install "torch==2.5.1+cu121" "torchaudio==2.5.1+cu121" torchvision --index-url https://download.pytorch.org/whl/cu121

:: Install DeepSpeed
echo.
echo Installing DeepSpeed...
echo Attempting to install pre-built wheel...
uv pip install https://raw.githubusercontent.com/KoljaB/RealtimeVoiceChat/main/wheels/deepspeed-0.16.1%%2Bunknown-cp310-cp310-win_amd64.whl
if errorlevel 1 (
    echo WARNING: Pre-built DeepSpeed wheel failed. Building from source...
    echo This may take several minutes...
    set TORCH_CUDA_ARCH_LIST=8.0;8.6;9.0
    uv pip install deepspeed
)

:: Install requirements
echo.
echo Installing requirements from requirements.txt...
uv pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install requirements. Check the error messages above.
    pause
    exit /b 1
)

:: Install spaCy model for Kokoro TTS engine (required for text-to-phoneme conversion)
echo.
echo Installing spaCy English model for Kokoro TTS engine...
uv pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl
if errorlevel 1 (
    echo WARNING: Failed to install spaCy model. Kokoro TTS engine may not work.
    echo You can install it manually with:
    echo   uv pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl
)

:: Verify installation
echo.
echo Verifying PyTorch CUDA availability...
python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA version: {torch.version.cuda if torch.cuda.is_available() else \"N/A\"}')"

echo.
echo Installation complete!
echo.
echo To activate the virtual environment in the future, run:
echo   .venv\Scripts\activate
echo.
pause
