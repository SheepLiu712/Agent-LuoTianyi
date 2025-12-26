@echo off
set "ENV_NAME="
echo Please enter a conda environment name (default: lty_agent):
set /p ENV_NAME=
if not defined ENV_NAME set "ENV_NAME=lty"

echo Creating environment: %ENV_NAME%
call conda create -n %ENV_NAME% python=3.10 -y
call conda activate %ENV_NAME%

set "INSTALL_CUDA="
echo Please decide whether to install pytorch with CUDA support (y/n, default: n):
set /p INSTALL_CUDA=
if not defined INSTALL_CUDA set "INSTALL_CUDA=n"

if /I "%INSTALL_CUDA%"=="y" (
    echo Installing PyTorch with CUDA support...
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
) else (
    echo Not installing PyTorch with CUDA support, Pytorch will be installed later.
)

pip install -r setup/gsv_requirements.txt
call conda install ffmpeg -y
pip install setup/live2d_py-0.6.0-cp310-cp310-win_amd64.whl
call conda install pyside6 -y
pip install -r setup/requirements.txt
pause