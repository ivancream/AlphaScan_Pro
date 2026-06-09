@echo off
setlocal EnableExtensions
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

set "PYTHON_ARM64=%USERPROFILE%\Python312_ARM64\python.exe"
if not exist "%PYTHON_ARM64%" (
    echo [ERROR] Python not found: %PYTHON_ARM64%
    pause
    exit /b 1
)

echo Starting AlphaScan frontend dist at http://localhost:1420/
"%PYTHON_ARM64%" scripts\dev\serve_frontend_dist.py
