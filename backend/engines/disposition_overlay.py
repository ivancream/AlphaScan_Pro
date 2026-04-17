"""
以 disposition_events（TWSE/TPEx 同步）補齊掃描結果的處置分鐘數。

daily_prices.disposition_mins 常未回填，導致「處置狀態」一律為「-」。
此模組在掃描／讀取快取時以交易所事件表覆寫顯示欄位。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from backend.db import queries as _db_queries
from backend.engines.engine_disposition import refresh_disposition_openapi_best_effort


def _disposition_sid_variants(sid: str) -> set[str]:
    """
    對齊 TWSE Code（可能為 033441）與 stock_info／K 線代號（可能為 33441）。
    不對 4 位以下代號做 int() 壓縮，避免 0050 變成 50。
    """
    s = str(sid or "").strip()
    if not s or not s.isdigit():
        return {s} if s else set()
    out: set[str] = {s, s.zfill(4), s.zfill(6)}
    if len(s) >= 5 and s.startswith("0"):
        out.add(str(int(s)))
    return {x for x in out if x}


def _to_date(val) -> Optional[date]:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    ts = pd.to_datetime(val, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def _event_end_date(raw) -> date:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return date(2099, 12, 31)
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return date(2099, 12, 31)
    ts = pd.to_datetime(raw, errors="coerce")
    if pd.isna(ts):
        return date(2099, 12, 31)
    return ts.date()


def compute_event_disposition_map(
    hist_map: Dict[str, pd.DataFrame],
) -> Tuple[Dict[str, int], frozenset[str]]:
    """
    依每檔最後一根 K 的日期查 disposition_events。

    回傳:
        (known_mins, active_unknown)
        - known_mins: 落在處置區間且 minutes>0 → {stock_id: 分鐘數}
        - active_unknown: 落在處置區間但 minutes 未知／為 0 的 stock_id（顯示「處置中」用）
    """
    if not hist_map:
        return {}, frozenset()

    last_dates: List[date] = []
    for df in hist_map.values():
        if df is None or df.empty or "Date" not in df.columns:
            continue
        last_dates.append(pd.Timestamp(df["Date"].iloc[-1]).date())
    if not last_dates:
        return {}, frozenset()

    d_min, d_max = min(last_dates), max(last_dates)
    ev = _db_queries.get_disposition_events_overlapping(d_min, d_max)
    if ev.empty:
        return {}, frozenset()

    out: Dict[str, int] = {}
    unknown_active: set[str] = set()
    for sid, df in hist_map.items():
        if df is None or df.empty or "Date" not in df.columns:
            continue
        d = pd.Timestamp(df["Date"].iloc[-1]).date()
        variants = _disposition_sid_variants(sid)
        sub = ev[ev["stock_id"].astype(str).isin(variants)]
        if sub.empty:
            continue
        best = 0
        in_window = False
        for _, row in sub.iterrows():
            start_d = _to_date(row.get("disp_start"))
            if start_d is None:
                continue
            end_d = _event_end_date(row.get("disp_end"))
            if start_d <= d <= end_d:
                in_window = True
                best = max(best, int(row.get("minutes") or 0))
        sid_s = str(sid)
        if best > 0:
            out[sid_s] = best
        elif in_window:
            unknown_active.add(sid_s)
    return out, frozenset(unknown_active)


def enrich_scan_rows_disposition(rows: List[dict]) -> None:
    """
    就地更新掃描列：若列上已有「處置狀態」鍵，則依 disposition_events 與「資料日期」重算。
    """
    if not rows:
        return
    refresh_disposition_openapi_best_effort(force=False)
    dated: List[Tuple[dict, str, date]] = []
    for r in rows:
        if "處置狀態" not in r:
            continue
        sid = str(r.get("代號", "")).strip()
        d = _to_date(r.get("資料日期"))
        if sid and d:
            dated.append((r, sid, d))
    if not dated:
        return

    d_min = min(t[2] for t in dated)
    d_max = max(t[2] for t in dated)
    ev = _db_queries.get_disposition_events_overlapping(d_min, d_max)
    if ev.empty:
        return

    for r, sid, d in dated:
        sub = ev[ev["stock_id"].astype(str).isin(_disposition_sid_variants(sid))]
        best = 0
        in_window = False
        for _, row in sub.iterrows():
            start_d = _to_date(row.get("disp_start"))
            if start_d is None:
                continue
            end_d = _event_end_date(row.get("disp_end"))
            if start_d <= d <= end_d:
                in_window = True
                best = max(best, int(row.get("minutes") or 0))
        if best > 0:
            r["處置狀態"] = f"每 {best} 分鐘撮合"
            r["is_disposition"] = True
        elif in_window:
            r["處置狀態"] = "處置中"
            r["is_disposition"] = True
        else:
            cur = str(r.get("處置狀態", "") or "")
            if cur.startswith("每 ") and "分鐘撮合" in cur:
                r["is_disposition"] = True
                continue
            r["處置狀態"] = "-"
            r["is_disposition"] = False
