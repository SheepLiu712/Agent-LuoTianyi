@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0..\.." || exit /b 1
if not "%~3"=="" goto :usage
if /i "%~1"=="conda" goto :conda
if not "%~2"=="" goto :usage
if not "%~1"=="" if /i not "%~1"=="uv" goto :usage
set "python=.venv\Scripts\python.exe"
if not exist "%python%" (
    echo Run scripts\deploy\install_windows.bat uv first. 1>&2
    exit /b 1
)
set "VIRTUAL_ENV=%CD%\.venv"
set "PATH=%VIRTUAL_ENV%\Scripts;%PATH%"
goto :start

:conda
set "env_name=%~2"
if not defined env_name set "env_name=lty"
call conda.bat activate "%env_name%" || exit /b 1
set "python=python"

:start
set "direct=localhost,127.0.0.1,::1,api.siliconflow.cn,dashscope.aliyuncs.com,restapi.amap.com,vcpedia.cn"
if defined NO_PROXY set "direct=%direct%,%NO_PROXY%"
set "NO_PROXY=%direct%"
"%python%" server_main.py
exit /b %ERRORLEVEL%

:usage
echo Usage: start_server.bat [uv^|conda [env-name]] 1>&2
exit /b 2
