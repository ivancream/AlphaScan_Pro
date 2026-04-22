"""
選股／自選「產業」欄與資金流向「板塊（macro）」對齊的解析邏輯。

熱力圖 engine_heatmap._resolve_labels 以 stock_sectors + twstock 推導 macro；
此處抽出同等優先順序，並將資料庫中字面上的「其他」視為無效，改走 twstock／yfinance。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, Optional


def _is_placeholder(s: Optional[str]) -> bool:
    if s is None:
        return True
    t = str(s).strip()
    return t == "" or t == "其他"


@lru_cache(maxsize=4096)
def _yfinance_sector_cached(sid: str, suffix: str) -> Optional[str]:
    """單檔快取；失敗回傳 None。"""
    try:
        import yfinance as yf

        info = yf.Ticker(f"{sid}{suffix}").info or {}
        for key in ("sector", "category", "industry"):
            v = info.get(key)
            if v and str(v).strip() and str(v).strip() != "其他":
                return str(v).strip()
    except Exception:
        pass
    return None


def resolve_industry_for_ui(
    stock_id: Any,
    sector_rows: Dict[str, Dict[str, Any]],
    tw_codes: Any,
    *,
    market: Optional[str] = None,
    use_yfinance: bool = False,
) -> str:
    """
    與熱力圖板塊一致：證交所 macro → twstock.group → meso（若非占位）→ twstock.type → 可選 yfinance。
    """
    sid = str(stock_id).strip()
    if not sid:
        return "其他"

    sector = sector_rows.get(sid)
    tw = tw_codes.get(sid) if tw_codes else None
    tw_group = None
    if tw is not None:
        g = getattr(tw, "group", None)
        tw_group = (str(g).strip() if g is not None else "") or None
        if tw_group == "":
            tw_group = None

    # ── 對齊 heatmap：有 macro 先用（但跳過占位「其他」）────────────────
    if sector:
        raw_m = sector.get("macro")
        if not _is_placeholder(raw_m):
            return str(raw_m).strip()

    if tw_group:
        return tw_group

    if sector:
        raw_me = sector.get("meso")
        if not _is_placeholder(raw_me):
            return str(raw_me).strip()

    if tw is not None:
        t = getattr(tw, "type", None)
        if t is not None and str(t).strip():
            return str(t).strip()

    if use_yfinance:
        suf = ".TWO" if market in ("OTC", "上櫃") else ".TW"
        yf_lab = _yfinance_sector_cached(sid, suf)
        if yf_lab:
            return yf_lab

    return "其他"
