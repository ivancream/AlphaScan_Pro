@echo off
setlocal EnableExtensions
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%\frontend"

echo Starting AlphaScan frontend at http://localhost:1420/
"C:\Program Files\nodejs\node.exe" node_modules\vite\bin\vite.js --host localhost --port 1420
