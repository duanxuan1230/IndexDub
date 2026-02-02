@echo off
set "VENV_DIR=.venv"

echo [IndexDub] Starting unified environment setup...

:: 1. Check for uv
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo [Error] 'uv' is not installed or not in PATH. Please install uv first.
    pause
    exit /b 1
)

:: 2. Create Virtual Environment
if not exist "%VENV_DIR%" (
    echo [Setup] Creating virtual environment in %VENV_DIR%...
    uv venv --python 3.10
) else (
    echo [Setup] Virtual environment already exists.
)

:: 3. Install Dependencies with Custom Index for PyTorch
echo [Setup] Installing dependencies from requirements.txt...
echo [Setup] Note: Using PyTorch 2.8.0 from cu128 index per IndexTTS requirements.

:: We use uv pip install with --extra-index-url for pytorch to allow PyPI fallback, and unsafe-best-match to find newer packages on PyPI if needed
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128 --index-strategy unsafe-best-match

if %errorlevel% neq 0 (
    echo [Error] Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo [Success] Environment is ready!
echo [Info] To activate: call .venv\Scripts\activate
echo [Info] To run IndexDub: uv run python main.py
echo.
pause
