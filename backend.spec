# backend.spec — PyInstaller 打包設定
# 用於將 FastAPI 後端打包為 Tauri sidecar 執行檔
#
# 執行步驟（在專案根目錄，.venv 已啟動）：
#   pyinstaller backend.spec --clean
#
# 產出：dist/alphascan-backend.exe（Windows）
# 複製至：frontend/src-tauri/binaries/alphascan-backend-<triple>.exe
#   （triple 可用 `rustc -vV | findstr host` 查詢）

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['backend/main.py'],
    pathex=[
        str(Path('backend').resolve()),
        str(Path('.').resolve()),
    ],
    binaries=[],
    datas=[
        # .env 放在 exe 旁（不打包進去，讓使用者自行設定）
        # 若要打包，取消下面這行的註解：
        # ('.env', '.'),

        # config / databases 目錄（若存在）
        ('config', 'config'),
        ('databases', 'databases'),
    ],
    hiddenimports=[
        # ── uvicorn ──────────────────────────────────────────────
        'uvicorn',
        'uvicorn.main',
        'uvicorn.config',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.loops.uvloop',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        # ── fastapi / starlette ───────────────────────────────────
        'fastapi',
        'starlette',
        'starlette.middleware',
        'starlette.middleware.cors',
        'starlette.routing',
        # ── database ──────────────────────────────────────────────
        'duckdb',
        'sqlite3',
        # ── data science ──────────────────────────────────────────
        'pandas',
        'pandas._libs.tslibs.np_datetime',
        'pandas._libs.tslibs.nattype',
        'pandas._libs.tslibs.timedeltas',
        'pandas._libs.skiplist',
        'pandas_ta',
        'numpy',
        'scipy',
        'scipy.special',
        'scipy.special._ufuncs',
        'scipy.linalg',
        'scipy.stats',
        'statsmodels',
        'statsmodels.tsa',
        'statsmodels.tsa.stattools',
        'statsmodels.tsa.tsatools',
        'statsmodels.tsa.adfvalues',
        'statsmodels.regression',
        'statsmodels.regression.linear_model',
        'statsmodels.iolib',
        'statsmodels.stats',
        # ── networking / http ─────────────────────────────────────
        'aiohttp',
        'aiofiles',
        'httpx',
        'requests',
        'urllib3',
        'certifi',
        # ── shioaji ───────────────────────────────────────────────
        'shioaji',
        'shioaji.contracts',
        'shioaji.order',
        'shioaji.data',
        'shioaji.account',
        'shioaji.constant',
        # ── yfinance ──────────────────────────────────────────────
        'yfinance',
        'yfinance.base',
        'yfinance.ticker',
        # ── scheduling ────────────────────────────────────────────
        'apscheduler',
        'apscheduler.schedulers',
        'apscheduler.schedulers.background',
        'apscheduler.triggers',
        'apscheduler.triggers.cron',
        'apscheduler.triggers.interval',
        # ── selenium ──────────────────────────────────────────────
        'selenium',
        'selenium.webdriver',
        'selenium.webdriver.chrome',
        'selenium.webdriver.chrome.options',
        'selenium.webdriver.chrome.service',
        'selenium.webdriver.common.by',
        'selenium.webdriver.support.ui',
        'selenium.webdriver.support.expected_conditions',
        'webdriver_manager',
        'webdriver_manager.chrome',
        # ── google generativeai ───────────────────────────────────
        'google.generativeai',
        'google.api_core',
        'google.auth',
        'google.protobuf',
        # ── misc ──────────────────────────────────────────────────
        'dotenv',
        'python_dotenv',
        'multipart',
        'PIL',
        'PIL.Image',
        'pydantic',
        'pydantic.v1',
        'email_validator',
        'h11',
        'anyio',
        'sniffio',
        'websockets',
        'wsproto',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
    ],
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
    upx_exclude=[
        'vcruntime140.dll',
        'msvcp140.dll',
        'python*.dll',
    ],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
