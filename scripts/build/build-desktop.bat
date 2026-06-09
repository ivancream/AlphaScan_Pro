@echo off
REM ============================================================
REM  AlphaScan Pro — 桌面端全自動打包腳本
REM  執行位置：專案根目錄
REM  用法：scripts\build\build-desktop.bat
REM ============================================================
setlocal EnableExtensions EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

echo.
echo =========================================
echo  AlphaScan Pro Desktop Build
echo =========================================
echo  Root: %ROOT%
echo.

REM ── 前置檢查 ──────────────────────────────────────────────
if not exist "%ROOT%\.venv\Scripts\activate.bat" (
    echo [ERROR] .venv not found. Run once:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate.bat
    echo   pip install -r backend\requirements.txt
    pause & exit /b 1
)

where rustc >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Rust not found. Install from https://rustup.rs
    pause & exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm not found. Install Node.js from https://nodejs.org
    pause & exit /b 1
)

REM ── 取得 Rust target triple ───────────────────────────────
for /f "tokens=2" %%A in ('rustc -vV ^| findstr /i "host:"') do set "RUST_TRIPLE=%%A"
echo [INFO] Rust target triple: %RUST_TRIPLE%

REM ── Step 1: 安裝後端依賴 ──────────────────────────────────
echo.
echo [Step 1/5] Installing Python dependencies...
call "%ROOT%\.venv\Scripts\python.exe" -m pip install -q -r "%ROOT%\backend\requirements.txt"
if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause & exit /b 1
)
call "%ROOT%\.venv\Scripts\python.exe" -m pip install -q pyinstaller
if errorlevel 1 (
    echo [ERROR] pyinstaller install failed.
    pause & exit /b 1
)
echo [OK] Python dependencies ready.

REM ── Step 2: PyInstaller 打包後端 ──────────────────────────
echo.
echo [Step 2/5] Packaging FastAPI backend with PyInstaller...
if exist "%ROOT%\dist\alphascan-backend.exe" del /f /q "%ROOT%\dist\alphascan-backend.exe"
call "%ROOT%\.venv\Scripts\pyinstaller.exe" --clean --noconfirm "%ROOT%\backend.spec"
if errorlevel 1 (
    echo [ERROR] PyInstaller failed. Check backend.spec and try again.
    pause & exit /b 1
)
if not exist "%ROOT%\dist\alphascan-backend.exe" (
    echo [ERROR] alphascan-backend.exe not found after PyInstaller.
    pause & exit /b 1
)
echo [OK] Backend packaged: dist\alphascan-backend.exe

REM ── Step 3: 複製 sidecar 到 Tauri binaries 目錄 ───────────
echo.
echo [Step 3/5] Copying sidecar to Tauri binaries...
set "BINARIES_DIR=%ROOT%\frontend\src-tauri\binaries"
if not exist "%BINARIES_DIR%" mkdir "%BINARIES_DIR%"
set "SIDECAR_NAME=alphascan-backend-%RUST_TRIPLE%.exe"
copy /y "%ROOT%\dist\alphascan-backend.exe" "%BINARIES_DIR%\%SIDECAR_NAME%"
if errorlevel 1 (
    echo [ERROR] Copy failed.
    pause & exit /b 1
)
echo [OK] Sidecar: %BINARIES_DIR%\%SIDECAR_NAME%

REM ── Step 4: 安裝前端 Node 依賴 ───────────────────────────
echo.
echo [Step 4/5] Installing frontend dependencies...
pushd "%ROOT%\frontend"
if not exist "node_modules\" (
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        popd & pause & exit /b 1
    )
)
popd
echo [OK] Node dependencies ready.

REM ── Step 5: Tauri build ───────────────────────────────────
echo.
echo [Step 5/5] Building Tauri desktop application...
pushd "%ROOT%\frontend"
call npm run tauri build
if errorlevel 1 (
    echo [ERROR] Tauri build failed.
    popd & pause & exit /b 1
)
popd

echo.
echo =========================================
echo  Build complete!
echo  Installer: frontend\src-tauri\target\release\bundle\
echo =========================================
echo.
pause
