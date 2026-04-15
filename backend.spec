# backend.spec — PyInstaller 打包設定
# 用於將 FastAPI 後端打包為 Tauri sidecar 執行檔
#
# 執行步驟（在專案根目錄）：
#   pip install pyinstaller
#   pyinstaller backend.spec
#
# 產出：dist/alphascan-backend.exe（Windows）
# 複製至：frontend/src-tauri/binaries/alphascan-backend-aarch64-pc-windows-msvc.exe
#   （檔名後綴需符合目標平台 triple，可用 `rustc -vV` 查詢）

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['backend/main.py'],
    pathex=[str(Path('backend').resolve())],
    binaries=[],
    datas=[
        # 包含 .env（若有）
        ('.env', '.'),
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'duckdb',
        'pandas_ta',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='alphascan-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
