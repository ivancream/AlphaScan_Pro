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


def _get_env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return float(default)


# 雙刀戰法綜合評分權重（建議總和為 1.0，可透過 .env 微調）
CORR_WEIGHT_CROSSINGS = _get_env_float("CORR_WEIGHT_CROSSINGS", 0.50)
CORR_WEIGHT_HALFLIFE = _get_env_float("CORR_WEIGHT_HALFLIFE", 0.35)
CORR_WEIGHT_PEARSON = _get_env_float("CORR_WEIGHT_PEARSON", 0.15)


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
