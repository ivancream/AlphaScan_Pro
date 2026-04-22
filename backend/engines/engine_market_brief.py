"""
早盤族群動能快報：依 theme.json 次族群分類，搭配永豐快照漲跌幅計算等權重平均。
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from backend.engines.sinopac_session import sinopac_session
from backend.engines.sinopac_snapshots import fetch_sinopac_change_pct_map
from backend.engines.theme_loader import load_theme_catalog_theme_to_stocks

_TZ = ZoneInfo("Asia/Taipei")


def _pick_leaders(
    stock_ids: List[str],
    pct_map: Dict[str, float],
    *,
    n: int = 2,
) -> List[Dict[str, Any]]:
    """同一族群內依漲跌幅由高到低，取前 n 檔領頭羊（僅含快照有報價者）。"""
    scored: List[tuple[str, float]] = []
    for sid in stock_ids:
        if sid in pct_map:
            scored.append((sid, float(pct_map[sid])))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [{"sid": a, "pct": b} for a, b in scored[:n]]


def generate_morning_brief() -> Dict[str, Any]:
    """
    讀取 theme.json 次族群、拉永豐漲跌幅快照，計算各族群等權重平均漲跌幅，
    並排出漲幅 / 跌幅前五名（各附 1～2 檔領頭羊）。

    Returns:
        {
            "ok": bool,
            "reason": str | None,
            "top_themes": [ {"name", "avg_pct", "leaders"}, ... ],
            "bottom_themes": [ ... ],
            "as_of": str (Asia/Taipei),
        }
    """
    now = datetime.datetime.now(_TZ)
    as_of = now.strftime("%Y-%m-%d %H:%M:%S")

    theme_map = load_theme_catalog_theme_to_stocks()
    if not theme_map:
        return {
            "ok": False,
            "reason": "theme.json 無題材或讀取失敗",
            "top_themes": [],
            "bottom_themes": [],
            "as_of": as_of,
        }

    all_ids: List[str] = []
    for ids in theme_map.values():
        all_ids.extend(ids)
    unique_ids = list(dict.fromkeys(all_ids))

    if not sinopac_session.is_connected:
        sinopac_session.connect()

    pct_map = fetch_sinopac_change_pct_map(unique_ids)
    if not pct_map:
        return {
            "ok": False,
            "reason": "未取得任何成分股漲跌幅（永豐未連線或 snapshot 為空）",
            "top_themes": [],
            "bottom_themes": [],
            "as_of": as_of,
        }

    rows: List[Dict[str, Any]] = []
    for theme_name, sids in theme_map.items():
        vals = [float(pct_map[sid]) for sid in sids if sid in pct_map]
        if not vals:
            continue
        avg_pct = sum(vals) / len(vals)
        leaders = _pick_leaders(sids, pct_map, n=2)
        rows.append({
            "name": theme_name,
            "avg_pct": round(avg_pct, 2),
            "leaders": leaders,
        })

    if not rows:
        return {
            "ok": False,
            "reason": "所有族群均無有效報價",
            "top_themes": [],
            "bottom_themes": [],
            "as_of": as_of,
        }

    rows_sorted = sorted(rows, key=lambda r: r["avg_pct"], reverse=True)
    top5 = rows_sorted[:5]
    bottom5 = sorted(rows, key=lambda r: r["avg_pct"])[:5]

    return {
        "ok": True,
        "reason": None,
        "top_themes": top5,
        "bottom_themes": bottom5,
        "as_of": as_of,
    }
