@echo off
cd /d "%~dp0"
set "ENV_NAME="
echo Please enter a conda environment name (default: lty_agent):
set /p ENV_NAME=
if not defined ENV_NAME set "ENV_NAME=lty"

echo Creating environment: %ENV_NAME%
call conda create -n %ENV_NAME% python=3.10 -y
call conda activate %ENV_NAME%

call conda install ffmpeg -y
pip install setup/live2d_py-0.6.0-cp310-cp310-win_amd64.whl
call conda install pyside6 -y
pip install -r setup/requirements.txt
pause