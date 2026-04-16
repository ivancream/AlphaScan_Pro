"""
小視野題材來源（合併後供 heatmap / refresh）：

1. 專案根目錄 theme.json — 題材分類表：{ "題材名": ["代號", ...], ... }，會反轉為代號→題材列表。
2. data/stock_themes.json — { "themes": { "代號": "題材" | ["題材", ...] } }；若某代號有設定，整組覆寫 theme.json 該檔的題材。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
THEMES_JSON = _PROJECT_ROOT / "data" / "stock_themes.json"
THEME_CATALOG_JSON = _PROJECT_ROOT / "theme.json"


def _theme_tags_from_json_value(v: Any) -> list[str]:
    """單一 JSON 值 -> 題材標籤列表（去重、保序）。"""
    if v is None:
        return []
    if isinstance(v, list):
        seen: set[str] = set()
        out: list[str] = []
        for item in v:
            if item is None:
                continue
            t = str(item).strip()
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(t)
        return out
    t = str(v).strip()
    return [t] if t else []


def load_theme_catalog_stock_tags() -> dict[str, list[str]]:
    """
    theme.json：{ "題材名": ["2330", ...] } -> { "2330": ["題材A", "題材B"], ... }。
    同一檔出現在多個題材鍵底下會合併為多個標籤（依 JSON 物件鍵順序）。
    """
    if not THEME_CATALOG_JSON.exists():
        return {}
    try:
        raw = THEME_CATALOG_JSON.read_text(encoding="utf-8")
        if raw.startswith("\ufeff"):
            raw = raw[1:]
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, list[str]] = {}
        for theme_name, tickers in data.items():
            tname = str(theme_name).strip()
            if not tname or not isinstance(tickers, list):
                continue
            for tid in tickers:
                if tid is None:
                    continue
                sid = str(tid).strip()
                if not sid.isdigit():
                    continue
                bucket = out.setdefault(sid, [])
                if tname not in bucket:
                    bucket.append(tname)
        return out
    except Exception:
        return {}


def _load_stock_themes_overrides() -> dict[str, list[str]]:
    """data/stock_themes.json 內 themes：代號鍵 -> 題材字串或陣列。"""
    if not THEMES_JSON.exists():
        return {}
    try:
        raw = THEMES_JSON.read_text(encoding="utf-8")
        if raw.startswith("\ufeff"):
            raw = raw[1:]
        data = json.loads(raw) if raw.strip() else {}
        themes = data.get("themes", data) if isinstance(data, dict) else {}
        if not isinstance(themes, dict):
            return {}
        out: dict[str, list[str]] = {}
        for k, v in themes.items():
            ks = str(k).strip()
            if not ks.isdigit():
                continue
            tags = _theme_tags_from_json_value(v)
            if tags:
                out[ks] = tags
        return out
    except Exception:
        return {}


def load_json_theme_micro_lists() -> dict[str, list[str]]:
    """
    stock_id -> 小視野題材標籤（可多個）。
    合併 theme.json 分類表與 data/stock_themes.json；後者若指定某代號則覆寫該檔整組題材。
    """
    catalog = load_theme_catalog_stock_tags()
    overrides = _load_stock_themes_overrides()
    merged = dict(catalog)
    for sid, tags in overrides.items():
        if tags:
            merged[sid] = tags
    return merged


def load_json_theme_micros() -> dict[str, str]:
    """相容：stock_id -> 第一個題材字串（單一鍵僅需一個標籤時可用）。"""
    return {k: v[0] for k, v in load_json_theme_micro_lists().items() if v}
