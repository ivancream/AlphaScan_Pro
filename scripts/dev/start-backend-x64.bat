@echo off
setlocal EnableExtensions
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

set "PYTHON_X64=%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe"
set "PYTHONPATH=%ROOT%\.venv\Lib\site-packages;%ROOT%"

if not exist "%PYTHON_X64%" (
    echo [ERROR] x64 Python not found: %PYTHON_X64%
    pause
    exit /b 1
)

echo Starting AlphaScan backend at http://127.0.0.1:8000/
"%PYTHON_X64%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
