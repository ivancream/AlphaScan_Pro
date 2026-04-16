"""載入 data/stock_themes.json 小視野覆寫（優先於 DB / 內建 theme_data）。"""

from __future__ import annotations

import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
THEMES_JSON = _PROJECT_ROOT / "data" / "stock_themes.json"


def load_json_theme_micros() -> dict[str, str]:
    """stock_id -> 小視野題材字串。僅接受純數字代號鍵。"""
    if not THEMES_JSON.exists():
        return {}
    try:
        raw = THEMES_JSON.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        themes = data.get("themes", data) if isinstance(data, dict) else {}
        if not isinstance(themes, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in themes.items():
            ks = str(k).strip()
            if not ks.isdigit():
                continue
            if v is None or not str(v).strip():
                continue
            out[ks] = str(v).strip()
        return out
    except Exception:
        return {}
