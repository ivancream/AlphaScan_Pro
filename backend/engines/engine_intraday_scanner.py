"""
盤中技術面掃描引擎 (Intraday Technical Scanner)

設計架構：雙層快取 + 30 分鐘排程
─────────────────────────────────────────────────────────────
Layer-1  歷史層：db_technical_prices.db / daily_price 表
         提供截至昨日的穩定日 K 資料。
         掃描時一次性批次讀取全市場歷史 K 線（單一 SQL 查詢）。

Layer-2  即時層：永豐 Shioaji snapshots API（批次一次取全市場）
         補入今日盤中最新 OHLCV，再丟給 BollingerStrategy 計算。

掃描流程（效能優化版）：
  1. 從 DB 讀取全市場股票清單（向量化過濾）
  2. 一次性批次呼叫 get_ohlcv_map() 取得所有快照
  3. 一次性批次讀取所有歷史 K 線（_load_all_history）
  4. 以 ProcessPoolExecutor 平行計算：
     - 每股只呼叫一次 calculate_indicators()
     - 同一組指標共用三種策略判斷
  5. 符合條件者寫入記憶體快取 _SCAN_CACHE
  6. 同步將本次掃描結果寫入 intraday_signals 表

前端 API 只需讀取 _SCAN_CACHE，不需在 Request 時當場計算。
"""
from __future__ import annotations

import asyncio
import datetime
import json
import math
import os
import threading
import time
import uuid
import zoneinfo
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from .cache_store import IntradayAlertCounter
from .sinopac_session import sinopac_session
from .engine_technical import BollingerStrategy
from .disposition_overlay import compute_event_disposition_map, enrich_scan_rows_disposition
from backend.db import queries as _db_queries
from backend.db.user_db import write_signals, get_latest_signals

# notifier lazy import
_notifier = None

def _get_notifier():
    global _notifier
    if _notifier is None:
        from . import notifier as _n
        _notifier = _n
    return _notifier

_TZ = zoneinfo.ZoneInfo("Asia/Taipei")

# ── 記憶體快取（進程共享，重啟後清空） ────────────────────────────────────
_SCAN_CACHE: Dict = {
    "long":     [],     # 多方布林突破候選
    "short":    [],     # 空方布林跌破候選
    "wanderer": [],     # 浪子回頭候選
    "last_run": None,   # ISO 8601 timestamp
    "status":   "idle", # idle | running | done | error
    "message":  "尚未執行掃描",
    "elapsed_sec": 0,
    "scan_id":  None,
}

_scanner_task: Optional[asyncio.Task] = None
_scan_lock = threading.Lock()

# ── 狀態式掃描：記住「上一次成功掃描」的多/空命中代號，供 Discord 只推「新觸發」──
# None = 尚無任何一次成功掃描（第一次成功掃描僅建立基準線，不發通知）
_prev_hit_ids_long: Optional[Set[str]] = None
_prev_hit_ids_short: Optional[Set[str]] = None
_prev_hit_ids_wanderer: Optional[Set[str]] = None


def _row_stock_id(row: Dict) -> str:
    return str(row.get("代號") or row.get("stock_id") or "").strip()


def _only_new_trigger_notify() -> bool:
    """true：只對本次新進榜的標的發 Discord；false：每次掃描推播完整清單（舊行為）。"""
    return os.getenv("DISCORD_NOTIFY_ONLY_NEW_TRIGGERS", "true").lower() in ("1", "true", "yes")


def pop_pending_scan_notify() -> Optional[Dict]:
    """
    由 APScheduler / 掃描迴圈在 _run_scan() 結束後呼叫，取出並清除待推播的 Discord 負載。
    若本輪無需推播則回傳 None。
    """
    return _SCAN_CACHE.pop("_pending_notify", None)


def get_scan_notify_state() -> Dict:
    """除錯用：多/空上一輪命中集合是否已建立基準線。"""
    return {
        "only_new_triggers": _only_new_trigger_notify(),
        "baseline_seeded_long":  _prev_hit_ids_long is not None,
        "baseline_seeded_short": _prev_hit_ids_short is not None,
        "baseline_seeded_wanderer": _prev_hit_ids_wanderer is not None,
        "prev_count_long":  len(_prev_hit_ids_long) if _prev_hit_ids_long is not None else None,
        "prev_count_short": len(_prev_hit_ids_short) if _prev_hit_ids_short is not None else None,
        "prev_count_wanderer": len(_prev_hit_ids_wanderer) if _prev_hit_ids_wanderer is not None else None,
        "intraday_alert_counter": IntradayAlertCounter.snapshot_stats(),
    }


def _compute_new_triggers_vs_prev(
    results_long: List[Dict],
    results_short: List[Dict],
) -> Tuple[List[Dict], List[Dict], bool]:
    """
    依上一輪命中集合計算「新觸發」列；並回傳本輪是否應視為「僅新觸發」模式（供 Embed 文案）。
    第一次成功掃描：回傳 ([], [])，並將本輪全集寫入 prev。
    """
    global _prev_hit_ids_long, _prev_hit_ids_short

    curr_long = {_row_stock_id(r) for r in results_long if _row_stock_id(r)}
    curr_short = {_row_stock_id(r) for r in results_short if _row_stock_id(r)}

    use_diff = _only_new_trigger_notify()

    if not use_diff:
        _prev_hit_ids_long = curr_long
        _prev_hit_ids_short = curr_short
        return results_long, results_short, False

    new_long: List[Dict] = []
    new_short: List[Dict] = []
    if _prev_hit_ids_long is not None:
        new_long = [r for r in results_long if _row_stock_id(r) not in _prev_hit_ids_long]
    if _prev_hit_ids_short is not None:
        new_short = [r for r in results_short if _row_stock_id(r) not in _prev_hit_ids_short]

    _prev_hit_ids_long = curr_long
    _prev_hit_ids_short = curr_short
    return new_long, new_short, True


def _compute_new_triggers_wanderer(
    results_wanderer: List[Dict],
) -> Tuple[List[Dict], bool]:
    """
    浪子回頭：與多/空相同的「新觸發」差集邏輯（受 DISCORD_NOTIFY_ONLY_NEW_TRIGGERS 控制）。
    回傳 (待推送列, 是否使用新觸發 Embed 文案)。
    """
    global _prev_hit_ids_wanderer

    curr = {_row_stock_id(r) for r in results_wanderer if _row_stock_id(r)}
    use_diff = _only_new_trigger_notify()

    if not use_diff:
        _prev_hit_ids_wanderer = curr
        return results_wanderer, False

    new_w: List[Dict] = []
    if _prev_hit_ids_wanderer is not None:
        new_w = [r for r in results_wanderer if _row_stock_id(r) not in _prev_hit_ids_wanderer]

    _prev_hit_ids_wanderer = curr
    return new_w, True


# ── 輔助函式 ─────────────────────────────────────────────────────────────────

def _long_row_needs_volume_ma_enrich(row: Dict) -> bool:
    """舊快取／舊 DB 列可能缺 20MA 量比或為無法解析的值。"""
    v = row.get("20MA量比")
    if v is None or v == "":
        return True
    try:
        float(v)
        return False
    except (TypeError, ValueError):
        return True


def enrich_long_rows_volume_ma_ratios(rows: List[Dict]) -> None:
    """
    以 DuckDB 日量補算 5MA／20MA 量比（就地修改列）。
    不覆寫已存在且為有限數值的 20MA量比。
    """
    if not rows:
        return
    targets = [r for r in rows if _long_row_needs_volume_ma_enrich(r)]
    if not targets:
        return
    ids: List[str] = []
    seen: Set[str] = set()
    for r in targets:
        sid = str(r.get("代號", "")).strip()
        if sid and sid not in seen:
            seen.add(sid)
            ids.append(sid)
    if not ids:
        return
    try:
        vol_df = _db_queries.get_volume_history_for_stocks(ids, days=120)
    except Exception as exc:  # noqa: BLE001
        print(f"[Scanner] enrich_long_rows_volume_ma_ratios: {exc}")
        return
    if vol_df is None or vol_df.empty:
        return
    by_sid: Dict[str, List[float]] = {}
    for sid, grp in vol_df.groupby("stock_id"):
        vals = pd.to_numeric(grp["volume"], errors="coerce").dropna().tolist()
        by_sid[str(sid).strip()] = [float(x) for x in vals]
    for r in targets:
        sid = str(r.get("代號", "")).strip()
        s2 = by_sid.get(sid)
        if not s2 or len(s2) < 1:
            continue
        last_v = float(s2[-1])
        w5 = s2[-5:] if len(s2) >= 5 else s2
        w20 = s2[-20:] if len(s2) >= 20 else s2
        m5 = sum(w5) / len(w5)
        m20 = sum(w20) / len(w20)
        r5 = (last_v / m5) if m5 > 0 else 0.0
        r20 = (last_v / m20) if m20 > 0 else 0.0
        if math.isfinite(r5):
            r["5MA量比"] = round(r5, 1)
        if math.isfinite(r20):
            r["20MA量比"] = round(r20, 2)


def _is_market_hours() -> bool:
    """判斷現在是否在台股盤中時段（09:00～13:35，不含六日）。"""
    now = datetime.datetime.now(_TZ)
    if now.weekday() >= 5:
        return False
    open_t  = now.replace(hour=9,  minute=0,  second=0, microsecond=0)
    close_t = now.replace(hour=13, minute=35, second=0, microsecond=0)
    return open_t <= now <= close_t


def _is_eligible(sid: str, sname: str) -> bool:
    """過濾槓桿/反向/DR 等不適合技術分析的股票。"""
    if any(c.isalpha() for c in sid):
        if not (len(sid) == 6 and sid.endswith("A") and sid[:-1].isdigit()):
            return False
    if sname:
        if "正2" in sname or "反1" in sname:
            return False
        if "-DR" in sname:
            return False
    return True


def _filter_eligible(stock_info: pd.DataFrame) -> pd.DataFrame:
    """向量化版本的股票過濾，取代逐列 DataFrame.apply()。"""
    sid = stock_info["stock_id"]
    name = stock_info["name"].fillna("")

    has_alpha = sid.str.contains(r"[a-zA-Z]", regex=True)
    is_valid_a_share = (
        (sid.str.len() == 6) & sid.str.endswith("A") & sid.str[:-1].str.isdigit()
    )
    alpha_ok = ~has_alpha | is_valid_a_share

    name_ok = ~(
        name.str.contains("正2", regex=False)
        | name.str.contains("反1", regex=False)
        | name.str.contains("-DR", regex=False)
    )
    return stock_info[alpha_ok & name_ok].reset_index(drop=True)


def _load_twstock_codes() -> dict:
    """載入 twstock 產業分類（每次掃描只做一次）。"""
    try:
        import twstock
        return twstock.codes
    except Exception:
        return {}


def _load_all_history() -> Dict[str, pd.DataFrame]:
    """
    一次性批次讀取所有股票近 500 天的歷史 K 線（DuckDB 版）。
    回傳 {stock_id: DataFrame}，每個 DataFrame 含
    Date, Open, High, Low, Close, Volume, Disposition_Mins。
    """
    all_df = _db_queries.get_price_df_all(cutoff_days=500)
    if all_df.empty:
        return {}

    # Rename columns to match BollingerStrategy expectations
    all_df = all_df.rename(columns={
        "date": "Date", "open": "Open", "high": "High",
        "low": "Low", "close": "Close", "volume": "Volume",
        "disposition_mins": "Disposition_Mins",
    })
    all_df["Date"] = pd.to_datetime(all_df["Date"])

    return {
        str(sid).strip(): grp.drop(columns=["stock_id"]).reset_index(drop=True)
        for sid, grp in all_df.groupby("stock_id")
    }


def _write_signals_to_db_new(
    scan_id: str,
    scan_time: str,
    results: Dict[str, List[Dict]],
) -> None:
    """將掃描結果寫入 user.db intraday_signals 表。"""
    write_signals(scan_id, scan_time, results)


def _write_signals_to_db(
    scan_id: str,
    scan_time: str,
    results: Dict[str, List[Dict]],
    conn=None,  # kept for backward compat but ignored
) -> None:
    """將掃描結果批次寫入 intraday_signals 表。(wrapper)"""
    _write_signals_to_db_new(scan_id, scan_time, results)


# ── Keep old signature for any existing callers ────────────────────────────
def _write_signals_rows_compat(
    scan_id: str,
    scan_time: str,
    results: Dict[str, List[Dict]],
    conn=None,
) -> None:
    rows = []
    for strategy, items in results.items():
        for item in items:
            signal_json = json.dumps(
                {k: v for k, v in item.items() if not k.startswith("_")},
                ensure_ascii=False,
                default=str,
            )
            rows.append((
                scan_id,
                scan_time,
                strategy,
                item.get("代號", ""),
                item.get("名稱", ""),
                item.get("market_type", ""),
                item.get("收盤價"),
                item.get("今日漲跌幅(%)"),
                item.get("成交量(張)"),
                signal_json,
            ))
    if rows:
        conn.executemany("""
            INSERT OR REPLACE INTO intraday_signals
                (scan_id, scan_time, strategy, stock_id, name, market_type,
                 close, change_pct, volume_k, signal_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        conn.commit()


# ── Per-stock worker (top-level function for ProcessPoolExecutor pickling) ──

def _analyze_single_stock(payload: Dict) -> Optional[Dict]:
    """
    ProcessPoolExecutor worker：對單一股票執行指標計算 + 三策略判斷。
    指標只計算一次，三策略共用，避免 3x 重複運算。
    必須是 module-level function 才能被 pickle 序列化到子進程。
    """
    stock_id = payload["stock_id"]
    df = payload["df"]
    snap = payload["snap"]
    name = payload["name"]
    market = payload["market"]
    industry = payload["industry"]
    max_date_limit = payload["max_date_limit"]
    event_disp_mins = int(payload.get("event_disp_mins") or 0)
    event_disp_active_unknown = bool(payload.get("event_disp_active_unknown"))

    # 注入今日盤中快照
    # 若尚未寫入今日處置資料，沿用最後一筆已知處置分鐘數，避免把處置狀態覆蓋成 0。
    last_disp_mins = int(df.iloc[-1].get("Disposition_Mins", 0) or 0)
    today_ts = pd.Timestamp(datetime.date.today())
    if snap and snap.get("Close", 0) > 0 and today_ts not in df["Date"].values:
        today_row = pd.DataFrame([{
            "Date": today_ts,
            "Open": snap["Open"],
            "High": snap["High"],
            "Low": snap["Low"],
            "Close": snap["Close"],
            "Volume": snap["Volume"],
            "Disposition_Mins": last_disp_mins,
        }])
        df = pd.concat([df, today_row], ignore_index=True)

    if len(df) < 60:
        return None

    # 過濾過時資料
    if max_date_limit is not None:
        last_date = df["Date"].iloc[-1]
        if pd.Timestamp(last_date) < max_date_limit:
            return None

    # 計算指標 — 只做一次，三策略共用
    df = BollingerStrategy.calculate_indicators(df)
    if df is None:
        return None

    # 共用欄位
    suffix = ".TWO" if market in ("OTC", "上櫃") else ".TW"
    real_ticker = f"{stock_id}{suffix}"

    change_pct = round(snap.get("ChangeRate", 0), 2) if snap else 0
    if change_pct == 0 and len(df) >= 2:
        today_c = df.iloc[-1]["Close"]
        prev_c = df.iloc[-2]["Close"]
        if prev_c > 0:
            raw_pct = (today_c - prev_c) / prev_c * 100
            change_pct = round(max(-10.0, min(10.0, raw_pct)), 2)

    volume_k = int(df.iloc[-1]["Volume"] / 1000)
    close = round(float(df.iloc[-1]["Close"]), 2)
    amount_b = round((close * df.iloc[-1]["Volume"]) / 1e8, 2)
    last_date_val = df.iloc[-1]["Date"]
    data_date = (
        last_date_val.strftime("%Y-%m-%d")
        if hasattr(last_date_val, "strftime")
        else str(last_date_val)[:10]
    )

    base_row = {
        "代號":         stock_id,
        "名稱":         name,
        "產業":         industry,
        "收盤價":       close,
        "今日漲跌幅(%)": change_pct,
        "成交量(張)":   volume_k,
        "成交額(億)":   amount_b,
        "資料日期":     data_date,
        "market_type":  market,
        "_ticker":      real_ticker,
        "_name":        name,
    }

    result: Dict = {"stock_id": stock_id, "long": None, "short": None, "wanderer": None}

    # ── 多方策略 ──────────────────────────────────────────────────────────
    if len(df) >= 60:
        try:
            _, q_long, _ = BollingerStrategy.analyze_from_computed(df)
            if q_long.get("Details", {}).get("cond_a"):
                result["long"] = {
                    **base_row,
                    "均線多排":     "V" if q_long["Details"]["cond_d"] else "-",
                    "爆量表態":     "V" if q_long["Details"]["cond_c"] else "-",
                    "月線斜率":     q_long.get("MA20_Slope_Pct", 0),
                    "上軌斜率":     q_long.get("Upper_Slope_Pct", 0),
                    "帶寬增長(%)":  q_long.get("Bandwidth_Chg", 0),
                    "5MA量比":      q_long.get("5MA量比", q_long.get("Vol_Ratio", 0)),
                    "20MA量比":     q_long.get("20MA量比", 0),
                    "上軌乖離(%)":  q_long.get("Pos_Upper", 0),
                    "_q_data":      q_long,
                }
        except Exception:
            pass

    # ── 空方策略 ──────────────────────────────────────────────────────────
    if len(df) >= 120:
        try:
            _, q_short, _ = BollingerStrategy.analyze_short_from_computed(df)
            det = q_short.get("Details", {})
            if det.get("cond_trend_bearish") and det.get("cond_ma20_slope_down"):
                result["short"] = {
                    **base_row,
                    "空頭排列":      "V" if det["cond_trend_bearish"] else "-",
                    "月線下彎":      "V" if det["cond_ma20_slope_down"] else "-",
                    "沿下軌":        "V" if det.get("cond_near_lower_band") else "-",
                    "月線斜率":      q_short.get("MA20_Slope", 0),
                    "布林位置":      q_short.get("BB_Position_Ratio"),
                    "季線乖離":      q_short.get("MA60_Bias", 0),
                    "半年線乖離":    q_short.get("MA120_Bias", 0),
                    "_q_data":       q_short,
                }
        except Exception:
            pass

    # ── 浪子回頭策略 ──────────────────────────────────────────────────────
    if len(df) >= 60:
        try:
            _, q_wand, _ = BollingerStrategy.analyze_wanderer_from_computed(df)
            det = q_wand.get("Details", {})
            if det.get("cond_slope") and det.get("cond_bb_level"):
                from_db = int(df.iloc[-1].get("Disposition_Mins", 0) or 0)
                disp_val = event_disp_mins if event_disp_mins > 0 else from_db
                if disp_val > 0:
                    disp_str = f"每 {int(disp_val)} 分鐘撮合"
                    is_disp = True
                elif event_disp_active_unknown:
                    disp_str = "處置中"
                    is_disp = True
                else:
                    disp_str = "-"
                    is_disp = False
                dd_from_high = BollingerStrategy.wanderer_drawdown_from_high_pct(df)
                result["wanderer"] = {
                    **base_row,
                    "月線斜率(%)":  round(q_wand.get("MA20_Slope_Pct", 0), 4),
                    "布林位階":      round(q_wand.get("BB_Position", 0), 2),
                    "自高點下跌(%)": dd_from_high,
                    "布林上軌":      round(q_wand.get("BB_Upper", 0), 2),
                    "布林中軌":      round(q_wand.get("BB_Middle", 0), 2),
                    "布林下軌":      round(q_wand.get("BB_Lower", 0), 2),
                    "處置狀態":      disp_str,
                    "is_disposition": is_disp,
                    "_q_data":       q_wand,
                }
        except Exception:
            pass

    if result["long"] is None and result["short"] is None and result["wanderer"] is None:
        return None
    return result


# ── 核心掃描函式（同步，在 executor 中執行） ─────────────────────────────────

def _run_scan() -> None:
    """
    全市場技術面掃描主函式（效能優化版）。
    - 批次 DB 讀取（單一 SQL 查詢取代 N+1 逐股 Query）
    - 指標只計算一次，三策略共用（消除 3x 重複 calculate_indicators）
    - ProcessPoolExecutor 多核平行計算
    - threading.Lock 防重入（排程 + 手動觸發不會重複執行）
    """
    global _SCAN_CACHE

    if not _scan_lock.acquire(blocking=False):
        print("[Scanner] 掃描已在執行中，跳過本次觸發")
        return

    scan_id = str(uuid.uuid4())[:8]

    try:
        scan_time = datetime.datetime.now(_TZ).isoformat()
        start_t   = time.time()

        _SCAN_CACHE.update({
            "status":  "running",
            "message": "初始化掃描...",
            "scan_id": scan_id,
        })
        print(f"[Scanner #{scan_id}] 啟動掃描 at {scan_time}")

        # ── 1. 讀取股票清單 + 向量化過濾 ─────────────────────────────────────
        stock_info_raw = _db_queries.get_stock_info_df()
        stock_info = stock_info_raw.rename(columns={"market": "market_type"}) if not stock_info_raw.empty else pd.DataFrame()
        stock_info = _filter_eligible(stock_info)
        all_ids = stock_info["stock_id"].tolist()
        total   = len(all_ids)
        _SCAN_CACHE["message"] = f"正在批次取得 {total} 檔快照..."
        print(f"[Scanner #{scan_id}] 共 {total} 檔待掃描")

        # ── 2. 批次取得 Sinopac OHLCV 快照（共享 Session，效能最佳） ──────────
        ohlcv_map = sinopac_session.get_ohlcv_map(all_ids)
        snap_count = len(ohlcv_map)
        print(f"[Scanner #{scan_id}] Sinopac 回傳 {snap_count} 檔快照")
        _SCAN_CACHE["message"] = f"快照 {snap_count} 檔，正在批次讀取歷史 K 線..."

        # ── 3. 一次性批次讀取所有歷史 K 線（DuckDB） ────────────────────────
        t_db = time.time()
        history_cache = _load_all_history()
        db_elapsed = time.time() - t_db
        print(f"[Scanner #{scan_id}] 批次讀取 {len(history_cache)} 檔歷史K線 ({db_elapsed:.1f}s)")

        try:
            from backend.engines.engine_disposition import refresh_disposition_openapi_best_effort

            refresh_disposition_openapi_best_effort(force=True)
        except Exception as disp_exc:  # noqa: BLE001
            print(f"[Scanner #{scan_id}] 處置清單同步失敗（沿用 DuckDB）: {disp_exc}")

        disp_event_by_sid, disp_unknown_active = compute_event_disposition_map(history_cache)

        # ── 4. 取全局最新日期，過濾過時股票 ─────────────────────────────────
        max_date_str = _db_queries.get_latest_price_date()
        max_date_limit = (
            pd.to_datetime(max_date_str) - pd.Timedelta(days=5)
            if max_date_str else None
        )

        # ── 5. 產業：證交所 stock_sectors 優先，其次 twstock（只載入一次） ───────
        tw_codes = _load_twstock_codes()
        sector_rows = _db_queries.get_stock_sector_rows()

        # ── 6. 組裝 worker 工作清單 ──────────────────────────────────────────
        _SCAN_CACHE["message"] = f"開始策略計算（{total} 檔）..."
        work_items: List[Dict] = []
        for _, row in stock_info.iterrows():
            sid = str(row["stock_id"]).strip()
            df = history_cache.get(sid)
            if df is None or len(df) < 60:
                continue

            industry = _db_queries.resolve_industry_label(
                sid,
                sector_rows,
                tw_codes,
                market=str(row.get("market_type", "") or ""),
            )

            work_items.append({
                "stock_id": sid,
                "df": df,
                "snap": ohlcv_map.get(sid),
                "name": row["name"] or "",
                "market": row.get("market_type", ""),
                "industry": industry,
                "max_date_limit": max_date_limit,
                "event_disp_mins": disp_event_by_sid.get(str(sid), 0),
                "event_disp_active_unknown": str(sid) in disp_unknown_active,
            })

        # ── 7. ProcessPoolExecutor 多核平行策略計算 ──────────────────────────
        t_calc = time.time()
        results_long     : List[Dict] = []
        results_short    : List[Dict] = []
        results_wanderer : List[Dict] = []

        try:
            cpu_count = min(os.cpu_count() or 4, 8)
            chunksize = max(1, len(work_items) // (cpu_count * 4))
            with ProcessPoolExecutor(max_workers=cpu_count) as pool:
                all_results = list(
                    pool.map(_analyze_single_stock, work_items, chunksize=chunksize)
                )
        except Exception as mp_exc:
            print(f"[Scanner #{scan_id}] ProcessPool 失敗 ({mp_exc})，改用單執行緒")
            all_results = [_analyze_single_stock(item) for item in work_items]

        for r in all_results:
            if r is None:
                continue
            if r.get("long"):
                results_long.append(r["long"])
            if r.get("short"):
                results_short.append(r["short"])
            if r.get("wanderer"):
                results_wanderer.append(r["wanderer"])

        enrich_scan_rows_disposition(results_wanderer)

        calc_elapsed = time.time() - t_calc
        print(f"[Scanner #{scan_id}] 策略計算完成 ({calc_elapsed:.1f}s)")

        # ── 8. 寫入 user.db intraday_signals ──────────────────────────────
        _write_signals_to_db(
            scan_id, scan_time,
            {"long": results_long, "short": results_short, "wanderer": results_wanderer},
        )

        elapsed = round(time.time() - start_t, 1)
        msg = (
            f"完成！多方 {len(results_long)} / 空方 {len(results_short)} / "
            f"浪子 {len(results_wanderer)} 檔，耗時 {elapsed}s"
        )
        _SCAN_CACHE.update({
            "long":        results_long,
            "short":       results_short,
            "wanderer":    results_wanderer,
            "last_run":    scan_time,
            "status":      "done",
            "message":     msg,
            "elapsed_sec": elapsed,
            "scan_id":     scan_id,
        })
        print(f"[Scanner #{scan_id}] {msg}")

        # ── Discord：新觸發差集 + 盤中防洗版（每檔每策略每日最多 N 次）──────────
        cand_long, cand_short, only_new_triggers = _compute_new_triggers_vs_prev(
            results_long, results_short
        )
        cand_wanderer, only_new_w = _compute_new_triggers_wanderer(results_wanderer)

        max_alerts = IntradayAlertCounter.max_per_strategy_per_day()
        allowed_long = IntradayAlertCounter.filter_rows_under_cap(
            cand_long, "long", max_alerts
        )
        allowed_short = IntradayAlertCounter.filter_rows_under_cap(
            cand_short, "short", max_alerts
        )
        allowed_wanderer = IntradayAlertCounter.filter_rows_under_cap(
            cand_wanderer, "wanderer", max_alerts
        )

        try:
            from . import notifier as _nf
            _notify_on = _nf.is_notify_enabled()
        except Exception:
            _notify_on = False

        only_new_embed = bool(only_new_triggers or only_new_w)

        if _notify_on:
            if allowed_long or allowed_short or allowed_wanderer:
                _SCAN_CACHE["_pending_notify"] = {
                    "scan_id":             scan_id,
                    "scan_time":           scan_time,
                    "long":                allowed_long,
                    "short":               allowed_short,
                    "wanderer":            allowed_wanderer,
                    "only_new_triggers":   only_new_embed,
                }

    except Exception as exc:
        _SCAN_CACHE.update({
            "status":  "error",
            "message": f"掃描失敗: {exc}",
        })
        print(f"[Scanner #{scan_id}] 掃描失敗: {exc}")
    finally:
        _scan_lock.release()


# ── 非同步排程迴圈 ────────────────────────────────────────────────────────────

async def _scanner_loop() -> None:
    """
    背景排程：
    - 盤中（09:00～13:35）每 30 分鐘掃一次
    - 非盤中靜默跳過，30 分鐘後再檢查
    - 首次啟動後若在盤中，立刻執行一次
    """
    first_run = True
    while True:
        try:
            in_market = _is_market_hours()
            if in_market and _SCAN_CACHE["status"] != "running":
                if first_run:
                    print("[Scanner] 首次啟動，延遲 10s 等待其他服務就緒...")
                    await asyncio.sleep(10)
                    first_run = False
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _run_scan)

                # ── 掃描完成後，嘗試推送 Discord 通知（非同步，失敗不影響排程） ──
                pending = pop_pending_scan_notify()
                if pending:
                    try:
                        n = _get_notifier()
                        res = await n.notify_scan_results(
                            results_long=pending["long"],
                            results_short=pending["short"],
                            scan_id=pending["scan_id"],
                            scan_time=pending["scan_time"],
                            only_new_triggers=pending.get("only_new_triggers", False),
                            results_wanderer=pending.get("wanderer"),
                        )
                        IntradayAlertCounter.apply_after_discord_notify(res, pending)
                    except Exception as notify_exc:
                        print(f"[Scanner Notifier] 推送失敗（不影響掃描）: {notify_exc}")
            else:
                first_run = False  # 非盤中也重置
        except Exception as exc:
            print(f"[Scanner Loop] 例外: {exc}")

        await asyncio.sleep(30 * 60)  # 30 分鐘


def start_scanner() -> None:
    """
    啟動盤中掃描排程（由 FastAPI startup event 呼叫）。
    重複呼叫是安全的（已有排程時直接跳過）。
    """
    global _scanner_task
    if _scanner_task is None or _scanner_task.done():
        _scanner_task = asyncio.create_task(_scanner_loop())
        print("[Scanner] 盤中 30 分鐘技術面掃描排程已啟動")


# ── 對外查詢介面（供 API 層呼叫） ────────────────────────────────────────────

def get_scan_status() -> Dict:
    """回傳目前掃描器狀態（不含結果清單）。"""
    out = {
        "status":      _SCAN_CACHE["status"],
        "message":     _SCAN_CACHE["message"],
        "last_run":    _SCAN_CACHE["last_run"],
        "elapsed_sec": _SCAN_CACHE["elapsed_sec"],
        "scan_id":     _SCAN_CACHE["scan_id"],
        "counts": {
            "long":     len(_SCAN_CACHE["long"]),
            "short":    len(_SCAN_CACHE["short"]),
            "wanderer": len(_SCAN_CACHE["wanderer"]),
        },
        "is_market_hours": _is_market_hours(),
    }
    out["discord_scan_state"] = get_scan_notify_state()
    return out


def get_scan_results(strategy: str = "long") -> List[Dict]:
    """
    取得指定策略的掃描結果（移除內部私有欄位後回傳）。
    strategy: 'long' | 'short' | 'wanderer'
    """
    items = _SCAN_CACHE.get(strategy, [])
    out = [
        {k: v for k, v in item.items() if not k.startswith("_")}
        for item in items
    ]
    if strategy == "long":
        enrich_long_rows_volume_ma_ratios(out)
    if strategy == "wanderer":
        enrich_scan_rows_disposition(out)
    return out


def get_last_signals_from_db(strategy: str = "long", limit: int = 200) -> List[Dict]:
    """
    從 user.db intraday_signals 讀取最近一次掃描結果（記憶體快取為空時的備援）。
    """
    out = get_latest_signals(strategy, limit)
    if strategy == "long":
        enrich_long_rows_volume_ma_ratios(out)
    if strategy == "wanderer":
        enrich_scan_rows_disposition(out)
    return out


def _get_last_signals_from_db_old(strategy: str = "long", limit: int = 200) -> List[Dict]:
    """舊實作保留供參考，已廢用。"""
    try:
        import json
        result = get_latest_signals(strategy, limit)
        return result
    except Exception:
        return []


def _get_last_signals_from_db_compat(strategy: str = "long", limit: int = 200) -> List[Dict]:
    """Read latest scan signals from user.db via the centralized user_db context manager."""
    try:
        import json
        from backend.db.connection import user_db
        with user_db() as conn:
            df = pd.read_sql(
                """
                SELECT *
                FROM intraday_signals
                WHERE strategy = ?
                  AND scan_time = (
                      SELECT MAX(scan_time) FROM intraday_signals WHERE strategy = ?
                  )
                ORDER BY close DESC
                LIMIT ?
                """,
                conn,
                params=[strategy, strategy, limit],
            )
        if df.empty:
            return []
        records = df.to_dict(orient="records")
        for r in records:
            try:
                r.update(json.loads(r.pop("signal_json", "{}")))
            except Exception:
                pass
        return records
    except Exception as exc:
        print(f"[Scanner DB] {exc}")
        return []


# ── 供 scheduler 呼叫的公開函式 ──────────────────────────────────────────────

def run_scan() -> None:
    """供 backend/scheduler.py 的 job_scanner 呼叫（同步）。"""
    _run_scan()
