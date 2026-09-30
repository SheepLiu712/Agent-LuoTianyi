@echo off
setlocal

cd /d "%~dp0"

set "CONDA_BAT=D:\Anaconda\condabin\conda.bat"
if not exist "%CONDA_BAT%" (
    echo [ERROR] Conda launcher not found: %CONDA_BAT%
    exit /b 1
)

echo Activating conda environment: lty
call "%CONDA_BAT%" activate lty
if errorlevel 1 (
    echo [ERROR] Failed to activate conda environment: lty
    exit /b 1
)

set "NO_PROXY=localhost,127.0.0.1,::1,api.siliconflow.cn,dashscope.aliyuncs.com,restapi.amap.com,vcpedia.cn"
echo NO_PROXY=%NO_PROXY%

echo Starting AgentLuo server...
python server_main.py
set "SERVER_EXIT_CODE=%ERRORLEVEL%"

if not "%SERVER_EXIT_CODE%"=="0" (
    echo [ERROR] AgentLuo server exited with code %SERVER_EXIT_CODE%.
)
exit /b %SERVER_EXIT_CODE%
