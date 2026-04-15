"""
載入專案根目錄的 `.env`，並提供永豐金 Shioaji 相關設定。

啟動方式為 `uvicorn backend.main:app` 時，工作目錄不影響載入路徑（以檔案位置推算根目錄）。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def sinopac_credentials_configured() -> bool:
    key = os.getenv("SINOPAC_API_KEY", "").strip()
    secret = os.getenv("SINOPAC_SECRET_KEY", "").strip()
    return bool(key and secret)


def get_sinopac_env() -> dict:
    """供 Shioaji `api.login(...)` 與憑證路徑使用。"""
    return {
        "api_key": os.getenv("SINOPAC_API_KEY", "").strip(),
        "secret_key": os.getenv("SINOPAC_SECRET_KEY", "").strip(),
        "ca_path": os.getenv("SINOPAC_CA_PATH", "").strip() or None,
        "ca_password": os.getenv("SINOPAC_CA_PASSWORD", "").strip() or None,
        "simulation": os.getenv("SINOPAC_SIMULATION", "false").strip().lower()
        in ("1", "true", "yes"),
    }
