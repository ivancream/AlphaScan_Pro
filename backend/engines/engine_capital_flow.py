"""
盤中資金流入監控（方法 A）：5 分鐘快照差分 × theme.json 族群聚合。

【資料來源】
  sinopac_snapshots.fetch_sinopac_ohlcv_map：Volume 為當日累積成交量（股）= 永豐 total_volume（張）× 1000；
  Close 為快照成交價；ChangeRate 為漲跌幅%。無需另行拉歷史 K 線。

【估算金額】
  本輪 5 分鐘內成交量（股）= Vol(T) − Vol(T−5)；
  估算成交金額（元）= max(Δ股, 0) × Close（僅將「增量」視為正向換手，避免還原修正造成負量洗訊號）。

【狀態】
  模組內記憶體保留上一輪每檔累積量與上一輪各族群「流入金額」合計，供 Delta 與條件 A 比較。
"""

from __future__ import annotations

import datetime
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

import zoneinfo

from backend.engines.sinopac_session import sinopac_session
from backend.engines.sinopac_snapshots import fetch_sinopac_ohlcv_map
from backend.engines.theme_loader import load_theme_catalog_theme_to_stocks

_TZ = zoneinfo.ZoneInfo("Asia/Taipei")

_lock = threading.Lock()
_prev_cum_shares: Dict[str, float] = {}
_prev_theme_flow_twd: Dict[str, float] = {}
_last_session_date: Optional[str] = None


def _today_iso() -> str:
    return datetime.datetime.now(_TZ).date().isoformat()


def _reset_if_new_trading_session() -> None:
    global _last_session_date, _prev_cum_shares, _prev_theme_flow_twd
    d = _today_iso()
    if _last_session_date != d:
        _last_session_date = d
        _prev_cum_shares.clear()
        _prev_theme_flow_twd.clear()


def _parse_snap(row: Dict[str, Any]) -> Optional[Tuple[float, float, float]]:
    """回傳 (cum_shares, close, change_pct) 或 None。"""
    try:
        vol = float(row.get("Volume") or 0)
        cl = float(row.get("Close") or 0)
        chg = float(row.get("ChangeRate") or 0)
    except (TypeError, ValueError):
        return None
    if cl <= 0 or vol < 0:
        return None
    return vol, cl, chg


def _is_market_hours() -> bool:
    now = datetime.datetime.now(_TZ)
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=9, minute=0, second=0, microsecond=0)
    c = now.replace(hour=13, minute=35, second=0, microsecond=0)
    return o <= now <= c


def run_capital_flow_tick() -> List[Dict[str, Any]]:
    """
    取快照、與上一輪累積量比對，回傳應發送 Discord 的族群警報列。

    觸發條件（同時滿足）：
      A) 本輪族群「正向增量金額」合計 > 上一輪同族群合計 × 2，且上一輪合計 > 0
      B) 族群內「當下有快照」的成分股中，漲幅 > 0 的比例 ≥ 80%

    平均漲跌幅：同上，對有快照的成分股之 ChangeRate 取平均。
    """
    global _prev_cum_shares, _prev_theme_flow_twd

    if not _is_market_hours():
        return []

    _reset_if_new_trading_session()

    theme_map = load_theme_catalog_theme_to_stocks()
    if not theme_map:
        return []

    all_ids: List[str] = []
    for ids in theme_map.values():
        all_ids.extend(ids)
    unique_ids = list(dict.fromkeys(all_ids))

    if not sinopac_session.is_connected:
        sinopac_session.connect()

    curr_map = fetch_sinopac_ohlcv_map(unique_ids)
    if not curr_map:
        return []

    alerts: List[Dict[str, Any]] = []

    with _lock:
        is_warmup = len(_prev_cum_shares) == 0

        # 本輪每檔：Δ股、估算金額、漲跌幅
        per_sid: Dict[str, Dict[str, float]] = {}
        for sid, snap in curr_map.items():
            parsed = _parse_snap(snap)
            if not parsed:
                continue
            cum, close, chg = parsed
            prev = _prev_cum_shares.get(sid)
            if prev is None:
                delta_sh = 0.0
            else:
                delta_sh = max(0.0, cum - prev)
            notional_twd = delta_sh * close
            per_sid[sid] = {
                "delta_sh": delta_sh,
                "notional_twd": notional_twd,
                "chg": chg,
                "has_delta_basis": prev is not None,
            }

        # 更新上一輪累積量（本輪結束後作為下一輪 T−5）
        next_prev: Dict[str, float] = dict(_prev_cum_shares)
        for sid, snap in curr_map.items():
            parsed = _parse_snap(snap)
            if parsed:
                next_prev[sid] = parsed[0]
        _prev_cum_shares = next_prev

        if is_warmup:
            # 第一輪僅建立基準，不觸發警報；仍寫入族群金額供下一輪條件 A
            theme_flow_now: Dict[str, float] = {}
            for theme, sids in theme_map.items():
                s = 0.0
                for sid in sids:
                    rec = per_sid.get(sid)
                    if rec:
                        s += rec["notional_twd"]
                theme_flow_now[theme] = s
            _prev_theme_flow_twd = theme_flow_now
            return []

        for theme, sids in theme_map.items():
            flow_sum = 0.0
            chg_vals: List[float] = []
            for sid in sids:
                snap = curr_map.get(sid)
                if not snap:
                    continue
                parsed = _parse_snap(snap)
                if not parsed:
                    continue
                chg_vals.append(parsed[2])
                rec = per_sid.get(sid)
                if rec and rec["has_delta_basis"]:
                    flow_sum += rec["notional_twd"]

            prev_flow = float(_prev_theme_flow_twd.get(theme, 0.0))

            if not chg_vals:
                _prev_theme_flow_twd[theme] = flow_sum
                continue

            red_ratio = sum(1 for c in chg_vals if c > 0) / len(chg_vals)
            cond_a = prev_flow > 0 and flow_sum > 2.0 * prev_flow
            cond_b = red_ratio >= 0.8
            try:
                min_n = max(2, int(os.getenv("CAPITAL_FLOW_MIN_STOCKS", "2")))
            except ValueError:
                min_n = 2
            cond_n = len(chg_vals) >= min_n

            _prev_theme_flow_twd[theme] = flow_sum

            if cond_a and cond_b and cond_n:
                alerts.append({
                    "theme": theme,
                    "flow_twd": flow_sum,
                    "flow_yi": round(flow_sum / 1e8, 2),
                    "avg_pct": round(sum(chg_vals) / len(chg_vals), 2),
                    "prev_flow_yi": round(prev_flow / 1e8, 2),
                    "red_ratio": round(red_ratio * 100, 1),
                    "sample_n": len(chg_vals),
                })

    return alerts


def get_capital_flow_state() -> Dict[str, Any]:
    """除錯：目前快取筆數與交易日鍵。"""
    with _lock:
        return {
            "session_date": _last_session_date,
            "prev_sid_count": len(_prev_cum_shares),
            "prev_theme_count": len(_prev_theme_flow_twd),
        }
