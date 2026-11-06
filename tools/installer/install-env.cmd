@echo off
rem Installs the pinned Python and AMA into the folder this script is in (ADR 0017).
rem The installer runs it after copying the files:
rem   install-env.cmd PYTHON_VERSION WHEEL CACHE_DIR
rem Everything goes under this folder (python\, venv\) and the uv cache under CACHE_DIR;
rem nothing is registered with Windows. Safe to run again: it rebuilds venv\.
setlocal
set "APP=%~dp0"
set "APP=%APP:~0,-1%"
set "UV=%APP%\uv.exe"
set "PY=%APP%\venv\Scripts\python.exe"
set "UV_PYTHON_INSTALL_DIR=%APP%\python"
set "UV_CACHE_DIR=%~3"
set "UV_LINK_MODE=copy"
set "UV_NO_CONFIG=1"
set "UV_PYTHON_PREFERENCE=only-managed"
set "UV_NO_PROGRESS=1"

echo Installing Python %~1
"%UV%" python install --no-bin --no-registry "%~1" || exit /b 1
echo Creating the environment
"%UV%" venv --clear --python "%~1" "%APP%\venv" || exit /b 2
echo Installing AMA's locked dependencies
"%UV%" pip sync --python "%PY%" --require-hashes "%APP%\requirements.txt" || exit /b 3
echo Installing %~2
"%UV%" pip install --python "%PY%" --no-deps "%APP%\%~2" || exit /b 4
"%PY%" -c "import ama.__main__" || exit /b 5
echo Done
