@echo off
REM Use system default code page so this .bat works when saved as UTF-8
setlocal EnableExtensions
set "ROOT=%~dp0"
REM Drop trailing backslash so "ROOT" in quotes never ends with \"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

if not exist "%ROOT%\.venv\Scripts\activate.bat" (
    echo [ERROR] Missing .venv. Run once from project root:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate.bat
    echo   pip install -r backend\requirements.txt
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm not found. Install Node.js from https://nodejs.org/
    pause
    exit /b 1
)

if not exist "%ROOT%\frontend\node_modules\" (
    echo [INFO] Running npm install in frontend ...
    pushd "%ROOT%\frontend"
    call npm install
    if errorlevel 1 (
        echo npm install failed.
        popd
        pause
        exit /b 1
    )
    popd
)

title AlphaScan Launcher
echo Stopping anything still listening on :8000 / :1420 ^(old uvicorn or vite^) ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\kill-dev-ports.ps1" -ProjectRoot "%ROOT%"
ping -n 2 127.0.0.1 >nul

echo Starting backend :8000 and frontend :1420 ...
start "AlphaScan Backend" cmd /k pushd "%ROOT%" ^&^& call .venv\Scripts\activate.bat ^&^& uvicorn backend.main:app --reload --port 8000
start "AlphaScan Frontend" cmd /k pushd "%ROOT%\frontend" ^&^& npm run dev

echo.
echo Waiting ~6s then opening browser (Vite UI on :1420)...
REM ping delay works even when "timeout" fails (no console input)
ping -n 7 127.0.0.1 >nul
start "" "http://localhost:1420/"

echo.
echo You should see two new windows: AlphaScan Backend / AlphaScan Frontend.
echo UI: http://localhost:1420/   API docs: http://localhost:8000/docs
echo To stop: close those windows or press Ctrl+C inside them.
echo.
pause
