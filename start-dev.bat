@echo off
setlocal
set "SCRIPT=%~dp0scripts\dev\start-dev.bat"

if not exist "%SCRIPT%" (
    echo [ERROR] Launcher script not found: %SCRIPT%
    pause
    exit /b 1
)

call "%SCRIPT%"
