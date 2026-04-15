"""
盤中技術面掃描引擎 (Intraday Technical Scanner)

設計架構：雙層快取 + 30 分鐘排程
─────────────────────────────────────────────────────────────
Layer-1  歷史層：db_technical_prices.db / daily_price 表
         提供截至昨日的穩定日 K 資料。

Layer-2  即時層：永豐 Shioaji snapshots API（批次一次取全市場）
         補入今日盤中最新 OHLCV，再丟給 BollingerStrategy 計算。

掃描流程：
  1. 從 DB 讀取全市場股票清單
  2. 一次性批次呼叫 fetch_sinopac_ohlcv_map() 取得所有快照
  3. 逐股合併歷史 K + 今日快照 → 執行三種策略分析
  4. 符合條件者寫入記憶體快取 _SCAN_CACHE
  5. 同步將本次掃描結果寫入 intraday_signals 表（可供重啟後查詢）

前端 API 只需讀取 _SCAN_CACHE，不需在 Request 時當場計算。
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import sqlite3
import time
import uuid
import zoneinfo
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from .sinopac_session import sinopac_session
from .engine_technical import BollingerStrategy

# notifier 使用 lazy import，避免啟動時循環依賴
_notifier = None

def _get_notifier():
    global _notifier
    if _notifier is None:
        from . import notifier as _n
        _notifier = _n
    return _notifier

# ── 路徑常數 ────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DB_PATH = _PROJECT_ROOT / "databases" / "db_technical_prices.db"
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

# ── 輔助函式 ─────────────────────────────────────────────────────────────────

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


def _ensure_signals_table(conn: sqlite3.Connection) -> None:
    """建立 intraday_signals 表（若不存在）。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS intraday_signals (
            scan_id     TEXT    NOT NULL,
            scan_time   TEXT    NOT NULL,
            strategy    TEXT    NOT NULL,
            stock_id    TEXT    NOT NULL,
            name        TEXT,
            market_type TEXT,
            close       REAL,
            change_pct  REAL,
            volume_k    INTEGER,
            signal_json TEXT,
            PRIMARY KEY (scan_time, strategy, stock_id)
        )
    """)
    # 保留最近 5 次掃描，避免無限成長
    conn.execute("""
        DELETE FROM intraday_signals
        WHERE scan_id NOT IN (
            SELECT DISTINCT scan_id FROM intraday_signals
            ORDER BY scan_time DESC
            LIMIT 5
        )
    """)
    conn.commit()


def _write_signals_to_db(
    scan_id: str,
    scan_time: str,
    results: Dict[str, List[Dict]],
    conn: sqlite3.Connection,
) -> None:
    """將掃描結果批次寫入 intraday_signals 表。"""
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


def _build_df(
    conn: sqlite3.Connection,
    stock_id: str,
    ohlcv_map: Dict[str, Dict],
    with_disposition: bool = True,
) -> Optional[pd.DataFrame]:
    """
    從 DB 讀取歷史 K 線，並 append 今日盤中快照（若存在且尚未入庫）。
    回傳欄位：Date, Open, High, Low, Close, Volume[, Disposition_Mins]
    """
    select_cols = (
        "date, open, high, low, close, volume, IFNULL(disposition_mins,0) as disposition_mins"
        if with_disposition
        else "date, open, high, low, close, volume"
    )
    df = pd.read_sql(
        f"SELECT {select_cols} FROM daily_price WHERE stock_id=? ORDER BY date ASC",
        conn,
        params=[stock_id],
    )
    if df.empty:
        return None

    col_names = (
        ["Date", "Open", "High", "Low", "Close", "Volume", "Disposition_Mins"]
        if with_disposition
        else ["Date", "Open", "High", "Low", "Close", "Volume"]
    )
    df.columns = col_names
    df["Date"] = pd.to_datetime(df["Date"])

    # 注入今日盤中快照
    snap = ohlcv_map.get(stock_id)
    today_ts = pd.Timestamp(datetime.date.today())
    if snap and snap.get("Close", 0) > 0 and today_ts not in df["Date"].values:
        today_row: Dict = {
            "Date":  today_ts,
            "Open":  snap["Open"],
            "High":  snap["High"],
            "Low":   snap["Low"],
            "Close": snap["Close"],
            "Volume": snap["Volume"],
        }
        if with_disposition:
            today_row["Disposition_Mins"] = 0
        df = pd.concat([df, pd.DataFrame([today_row])], ignore_index=True)

    return df


# ── 核心掃描函式（同步，在 executor 中執行） ─────────────────────────────────

def _run_scan() -> None:
    """
    全市場技術面掃描主函式。
    執行三種策略：多方布林 / 空方布林 / 浪子回頭。
    結果寫入記憶體快取 _SCAN_CACHE 及 intraday_signals 表。
    """
    global _SCAN_CACHE

    scan_id   = str(uuid.uuid4())[:8]
    scan_time = datetime.datetime.now(_TZ).isoformat()
    start_t   = time.time()

    _SCAN_CACHE.update({
        "status":  "running",
        "message": "初始化掃描...",
        "scan_id": scan_id,
    })
    print(f"[Scanner #{scan_id}] 啟動掃描 at {scan_time}")

    try:
        if not _DB_PATH.exists():
            raise FileNotFoundError(f"找不到資料庫: {_DB_PATH}")

        conn = sqlite3.connect(str(_DB_PATH))
        _ensure_signals_table(conn)

        # ── 1. 讀取股票清單 ─────────────────────────────────────────────────
        stock_info = pd.read_sql(
            "SELECT stock_id, name, market_type FROM stock_info", conn
        )
        stock_info = stock_info[
            stock_info.apply(
                lambda r: _is_eligible(r["stock_id"], r["name"] or ""), axis=1
            )
        ]
        all_ids = stock_info["stock_id"].tolist()
        total   = len(all_ids)
        _SCAN_CACHE["message"] = f"正在批次取得 {total} 檔快照..."
        print(f"[Scanner #{scan_id}] 共 {total} 檔待掃描")

        # ── 2. 批次取得 Sinopac OHLCV 快照（共享 Session，效能最佳） ──────────
        ohlcv_map = sinopac_session.get_ohlcv_map(all_ids)
        snap_count = len(ohlcv_map)
        print(f"[Scanner #{scan_id}] Sinopac 回傳 {snap_count} 檔快照")
        _SCAN_CACHE["message"] = f"快照取得 {snap_count} 檔，開始策略計算..."

        # ── 3. 取全局最新日期，過濾過時股票 ─────────────────────────────────
        max_date_row = pd.read_sql(
            "SELECT MAX(date) FROM daily_price", conn
        ).iloc[0, 0]
        max_date_limit = (
            pd.to_datetime(max_date_row) - pd.Timedelta(days=5)
            if max_date_row else None
        )

        # ── 4. 嘗試引入 twstock 做產業分類 ───────────────────────────────────
        try:
            import twstock
            tw_codes = twstock.codes
        except Exception:
            tw_codes = {}

        results_long     : List[Dict] = []
        results_short    : List[Dict] = []
        results_wanderer : List[Dict] = []

        for _, row in stock_info.iterrows():
            stock_id = row["stock_id"]
            name     = row["name"] or ""
            market   = row.get("market_type", "")

            # 讀取歷史 + 注入快照
            df = _build_df(conn, stock_id, ohlcv_map, with_disposition=True)
            if df is None or len(df) < 60:
                continue

            if max_date_limit is not None:
                last_date = df["Date"].iloc[-1] if "Date" in df.columns else None
                if last_date is not None and pd.Timestamp(last_date) < max_date_limit:
                    continue

            suffix      = ".TW" if market == "上市" else ".TWO"
            real_ticker = f"{stock_id}{suffix}"

            snap        = ohlcv_map.get(stock_id, {})
            change_pct  = round(snap.get("ChangeRate", 0), 2)
            if change_pct == 0 and len(df) >= 2:
                today_c = df.iloc[-1]["Close"]
                prev_c  = df.iloc[-2]["Close"]
                change_pct = round((today_c - prev_c) / prev_c * 100, 2) if prev_c > 0 else 0

            volume_k = int(df.iloc[-1]["Volume"] / 1000)
            close    = round(df.iloc[-1]["Close"], 2)
            amount_b = round((close * df.iloc[-1]["Volume"]) / 1e8, 2)

            try:
                industry = (
                    getattr(tw_codes.get(stock_id), "group", "其他")
                    if tw_codes.get(stock_id) else "其他"
                )
            except Exception:
                industry = "其他"

            base_row = {
                "代號":         stock_id,
                "名稱":         name,
                "產業":         industry,
                "收盤價":       close,
                "今日漲跌幅(%)": change_pct,
                "成交量(張)":   volume_k,
                "成交額(億)":   amount_b,
                "資料日期":     df.iloc[-1]["Date"].strftime("%Y-%m-%d") if hasattr(df.iloc[-1]["Date"], "strftime") else str(df.iloc[-1]["Date"])[:10],
                "market_type":  market,
                "_ticker":      real_ticker,
                "_name":        name,
            }

            # ── 多方策略 ────────────────────────────────────────────────────
            if len(df) >= 60:
                try:
                    _, q_long, _ = BollingerStrategy.analyze(df)
                    if q_long.get("Details", {}).get("cond_a"):  # 核心：通道擴張
                        results_long.append({
                            **base_row,
                            "均線多排":     "V" if q_long["Details"]["cond_d"] else "-",
                            "爆量表態":     "V" if q_long["Details"]["cond_c"] else "-",
                            "月線斜率":     q_long.get("MA20_Slope_Pct", 0),
                            "上軌斜率":     q_long.get("Upper_Slope_Pct", 0),
                            "帶寬增長(%)":  q_long.get("Bandwidth_Chg", 0),
                            "量比":         q_long.get("Vol_Ratio", 0),
                            "上軌乖離(%)":  q_long.get("Pos_Upper", 0),
                            "_q_data":      q_long,
                        })
                except Exception:
                    pass

            # ── 空方策略 ────────────────────────────────────────────────────
            if len(df) >= 120:
                try:
                    _, q_short, _ = BollingerStrategy.analyze_short(df)
                    det = q_short.get("Details", {})
                    if det.get("cond_trend_bearish") and det.get("cond_ma20_slope_down"):
                        results_short.append({
                            **base_row,
                            "空頭排列":      "V" if det["cond_trend_bearish"] else "-",
                            "月線下彎":      "V" if det["cond_ma20_slope_down"] else "-",
                            "沿下軌":        "V" if det.get("cond_near_lower_band") else "-",
                            "月線斜率":      q_short.get("MA20_Slope", 0),
                            "布林位置":      q_short.get("BB_Position_Ratio"),
                            "季線乖離":      q_short.get("MA60_Bias", 0),
                            "半年線乖離":    q_short.get("MA120_Bias", 0),
                            "_q_data":       q_short,
                        })
                except Exception:
                    pass

            # ── 浪子回頭策略 ─────────────────────────────────────────────────
            if len(df) >= 60:
                try:
                    _, q_wand, _ = BollingerStrategy.analyze_wanderer(df)
                    det = q_wand.get("Details", {})
                    if det.get("cond_slope") and det.get("cond_bb_level"):
                        disp_val = df.iloc[-1].get("Disposition_Mins", 0) or 0
                        results_wanderer.append({
                            **base_row,
                            "月線斜率(%)":  round(q_wand.get("MA20_Slope_Pct", 0), 4),
                            "布林位階":      round(q_wand.get("BB_Position", 0), 2),
                            "布林上軌":      round(q_wand.get("BB_Upper", 0), 2),
                            "布林中軌":      round(q_wand.get("BB_Middle", 0), 2),
                            "布林下軌":      round(q_wand.get("BB_Lower", 0), 2),
                            "處置狀態":      f"每 {int(disp_val)} 分鐘撮合" if disp_val > 0 else "-",
                            "is_disposition": bool(disp_val > 0),
                            "_q_data":       q_wand,
                        })
                except Exception:
                    pass

        conn_write = sqlite3.connect(str(_DB_PATH))
        _ensure_signals_table(conn_write)
        _write_signals_to_db(
            scan_id, scan_time,
            {"long": results_long, "short": results_short, "wanderer": results_wanderer},
            conn_write,
        )
        conn_write.close()
        conn.close()

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

        # ── Discord 通知（只在 DISCORD_NOTIFY_ON_SCAN=true 時觸發） ──────────
        _SCAN_CACHE["_pending_notify"] = {
            "scan_id":   scan_id,
            "scan_time": scan_time,
            "long":      results_long,
            "short":     results_short,
        }

    except Exception as exc:
        _SCAN_CACHE.update({
            "status":  "error",
            "message": f"掃描失敗: {exc}",
        })
        print(f"[Scanner #{scan_id}] 掃描失敗: {exc}")


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
                pending = _SCAN_CACHE.pop("_pending_notify", None)
                if pending:
                    try:
                        n = _get_notifier()
                        await n.notify_scan_results(
                            results_long  = pending["long"],
                            results_short = pending["short"],
                            scan_id       = pending["scan_id"],
                            scan_time     = pending["scan_time"],
                        )
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
    return {
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


def get_scan_results(strategy: str = "long") -> List[Dict]:
    """
    取得指定策略的掃描結果（移除內部私有欄位後回傳）。
    strategy: 'long' | 'short' | 'wanderer'
    """
    items = _SCAN_CACHE.get(strategy, [])
    return [
        {k: v for k, v in item.items() if not k.startswith("_")}
        for item in items
    ]


def get_last_signals_from_db(strategy: str = "long", limit: int = 200) -> List[Dict]:
    """
    從 intraday_signals 表讀取最近一次掃描的結果（記憶體快取為空時的備援）。
    """
    if not _DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(_DB_PATH))
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
        conn.close()
        if df.empty:
            return []
        records = df.to_dict(orient="records")
        # 解析 JSON blob
        for r in records:
            try:
                r.update(json.loads(r.pop("signal_json", "{}")))
            except Exception:
                pass
        return records
    except Exception as exc:
        print(f"[Scanner DB fallback] {exc}")
        return []
