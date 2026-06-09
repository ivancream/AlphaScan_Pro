@echo off
setlocal EnableExtensions
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

set "PYTHON_X64=%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe"
set "PYTHONPATH=%ROOT%\.venv\Lib\site-packages;%ROOT%"
set "LOG=%ROOT%\backend-x64.log"

echo [%DATE% %TIME%] Starting AlphaScan backend > "%LOG%"
"%PYTHON_X64%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 >> "%LOG%" 2>&1
echo [%DATE% %TIME%] Backend exited with code %ERRORLEVEL% >> "%LOG%"
