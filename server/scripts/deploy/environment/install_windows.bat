@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0..\..\.." || exit /b 1
set "method=%~1"
if not defined method set "method=uv"
set "build=%~2"
if not defined build set "build=cpu"
if not "%~4"=="" goto :usage
for %%B in (cpu cu126 cu128 cu130) do if "%build%"=="%%B" goto :select_method
goto :usage

:select_method
if /i "%method%"=="conda" goto :conda
if /i not "%method%"=="uv" goto :usage
if not "%~3"=="" goto :usage
ffmpeg -version >nul || exit /b 1
if not exist ".venv\Scripts\python.exe" (
    uv venv --python 3.10 .venv || exit /b 1
)
set "python=.venv\Scripts\python.exe"
set "install=uv pip install --python .venv\Scripts\python.exe"
goto :dependencies

:conda
set "env_name=%~3"
if not defined env_name set "env_name=lty"
call conda.bat env update --name "%env_name%" --file "%~dp0windows-conda.yml" || exit /b 1
call conda.bat activate "%env_name%" || exit /b 1
set "python=python"
set "install=python -m pip install"

:dependencies
%python% -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 10) else 'Python 3.10 required')" || exit /b 1
set "torch_version=2.8.0"
set "vision_version=0.23.0"
if "%build%"=="cu130" (
    set "torch_version=2.9.1"
    set "vision_version=0.24.1"
)
%install% torch==%torch_version%+%build% torchaudio==%torch_version%+%build% torchvision==%vision_version%+%build% --index-url https://download.pytorch.org/whl/%build% || exit /b 1
%install% -e ".[speech,song-learning]" "setuptools>=80,<81" "transformers<5" || exit /b 1
%python% -m playwright install chromium || exit /b 1
echo Installation complete.
exit /b 0

:usage
echo Usage: install_windows.bat [uv^|conda] [cpu^|cu126^|cu128^|cu130] [conda-env-name] 1>&2
exit /b 2
