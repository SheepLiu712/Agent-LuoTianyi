@echo off
setlocal
cd /d "%~dp0\.."

set "ENV_NAME="
echo Please enter a conda environment name (default: lty):
set /p ENV_NAME=
if not defined ENV_NAME set "ENV_NAME=lty"

echo Creating conda environment: %ENV_NAME%
call conda create -n "%ENV_NAME%" python=3.10 -y
if errorlevel 1 goto :fail
call conda activate "%ENV_NAME%"
if errorlevel 1 goto :fail

set "TORCH_BUILD="
echo Please select PyTorch build (1: CUDA 13.0, 2: CUDA 12.8, 3: CUDA 12.6, 4: CPU, default: 4):
set /p TORCH_BUILD=
if not defined TORCH_BUILD set "TORCH_BUILD=4"

if "%TORCH_BUILD%"=="1" (
    echo Installing PyTorch with CUDA 13.0 support...
    call python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130
) else if "%TORCH_BUILD%"=="2" (
    echo Installing PyTorch with CUDA 12.8 support...
    call python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
) else if "%TORCH_BUILD%"=="3" (
    echo Installing PyTorch with CUDA 12.6 support...
    call python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
) else if "%TORCH_BUILD%"=="4" (
    echo Installing CPU-only PyTorch...
    call python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
) else (
    echo Unsupported PyTorch build selection: %TORCH_BUILD%
    goto :fail
)
if errorlevel 1 goto :fail

echo Installing FFmpeg into the conda environment...
call conda install ffmpeg -y
if errorlevel 1 goto :fail

echo Installing AgentLuo Server and runtime feature groups from pyproject.toml...
call python -m pip install --upgrade pip
if errorlevel 1 goto :fail
call python -m pip install -e ".[speech,song-learning]"
if errorlevel 1 goto :fail

echo Installing Playwright Chromium...
call python -m playwright install chromium
if errorlevel 1 goto :fail

echo.
echo AgentLuo Server installation completed.
echo For developer tools, run: python -m pip install -e ".[dev]"
pause
exit /b 0

:fail
echo.
echo AgentLuo Server installation failed. Review the command output above.
pause
exit /b 1
