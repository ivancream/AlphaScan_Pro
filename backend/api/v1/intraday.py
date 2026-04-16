"""
盤中資料補齊 API

設計：
- 優先使用永豐 Shioaji **批次** snapshot（sinopac_session.get_ohlcv_map → api.snapshots）
- Shioaji 不可用時 fallback **批次** yfinance download（非逐檔）
- 所有資料寫入統一的 DuckDB daily_prices 表
- 排程由 backend/scheduler.py 統一管理（每 5 分鐘盤中、14:05 盤後）
- 本模組提供 _run_intraday_update 函式供 scheduler 呼叫，
  以及手動觸發的 API endpoint
"""

import datetime
import time
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from fastapi import APIRouter, BackgroundTasks

from backend.engines.sinopac_session import sinopac_session
from backend.db import queries, writer
from backend.db.symbol_utils import to_yf_ticker

router = APIRouter()

_TZ = ZoneInfo("Asia/Taipei")

_update_state = {
    "status": "idle",
    "last_updated": None,
    "stocks_updated": 0,
    "total_stocks": 0,
    "message": "",
    "elapsed_sec": 0,
}


def _is_market_hours() -> bool:
    now = datetime.datetime.now(_TZ)
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=9,  minute=0,  second=0, microsecond=0)
    c = now.replace(hour=13, minute=35, second=0, microsecond=0)
    return o <= now <= c


def _update_via_sinopac(stock_df: pd.DataFrame) -> int:
    """Batch-update today's OHLCV via Shioaji snapshots → DuckDB."""
    all_ids = stock_df["stock_id"].astype(str).tolist()
    ohlcv_map = sinopac_session.get_ohlcv_map(all_ids)
    if not ohlcv_map:
        return 0

    today = datetime.date.today().isoformat()
    rows = []
    for sid in all_ids:
        snap = ohlcv_map.get(sid)
        if not snap:
            continue
        close = float(snap.get("Close") or 0)
        if close <= 0:
            continue
        rows.append({
            "stock_id": sid,
            "date": today,
            "open": float(snap.get("Open") or close),
            "high": float(snap.get("High") or close),
            "low": float(snap.get("Low") or close),
            "close": close,
            "volume": float(snap.get("Volume") or 0),
        })

    if not rows:
        return 0

    df = pd.DataFrame(rows)
    writer.upsert_daily_prices(df)
    return len(rows)


def _update_via_yfinance(stock_df: pd.DataFrame) -> int:
    """Fallback: batch download via yfinance → DuckDB."""
    if stock_df.empty:
        return 0

    # Build {yf_ticker: stock_id} map
    ticker_map: dict[str, str] = {}
    for _, row in stock_df.iterrows():
        sid = str(row["stock_id"])
        market = str(row.get("market", "TSE"))
        ticker_map[to_yf_ticker(sid, market)] = sid

    all_tickers = list(ticker_map.keys())
    batch_size = 100
    all_rows = []

    for start in range(0, len(all_tickers), batch_size):
        batch = all_tickers[start: start + batch_size]
        try:
            raw = yf.download(
                " ".join(batch), period="5d", progress=False,
                group_by="ticker", threads=True,
            )
            if raw is None or raw.empty:
                continue

            if len(batch) == 1:
                sid = ticker_map[batch[0]]
                df_s = raw.copy()
                if isinstance(df_s.columns, pd.MultiIndex):
                    df_s.columns = [c[0] for c in df_s.columns]
                df_s = df_s.dropna(subset=["Close"]).reset_index()
                if not df_s.empty:
                    r = df_s.iloc[-1]
                    all_rows.append({
                        "stock_id": sid,
                        "date": pd.to_datetime(r.iloc[0]).strftime("%Y-%m-%d"),
                        "open": float(r["Open"]),
                        "high": float(r["High"]),
                        "low": float(r["Low"]),
                        "close": float(r["Close"]),
                        "volume": float(r["Volume"]),
                    })
            else:
                available = raw.columns.get_level_values(0).unique()
                for yf_t in batch:
                    if yf_t not in available:
                        continue
                    sid = ticker_map[yf_t]
                    try:
                        sub = raw[yf_t].dropna(subset=["Close"]).reset_index()
                        if sub.empty:
                            continue
                        r = sub.iloc[-1]
                        all_rows.append({
                            "stock_id": sid,
                            "date": pd.to_datetime(r.iloc[0]).strftime("%Y-%m-%d"),
                            "open": float(r["Open"]),
                            "high": float(r["High"]),
                            "low": float(r["Low"]),
                            "close": float(r["Close"]),
                            "volume": float(r["Volume"]),
                        })
                    except Exception:
                        continue
        except Exception:
            continue

    if not all_rows:
        return 0

    df = pd.DataFrame(all_rows)
    writer.upsert_daily_prices(df)
    return len(all_rows)


def _backfill_via_yfinance(stock_df: pd.DataFrame, period: str = "1mo") -> int:
    """
    Full backfill: download *all* rows for the period (not just latest)
    and upsert into DuckDB.  Used at startup to fill data gaps.
    """
    if stock_df.empty:
        return 0

    ticker_map: dict[str, str] = {}
    for _, row in stock_df.iterrows():
        sid = str(row["stock_id"])
        market = str(row.get("market", "TSE"))
        ticker_map[to_yf_ticker(sid, market)] = sid

    all_tickers = list(ticker_map.keys())
    batch_size = 100
    total_written = 0

    for start in range(0, len(all_tickers), batch_size):
        batch = all_tickers[start: start + batch_size]
        try:
            raw = yf.download(
                " ".join(batch), period=period, progress=False,
                group_by="ticker", threads=True,
            )
            if raw is None or raw.empty:
                continue

            all_rows = []
            if len(batch) == 1:
                sid = ticker_map[batch[0]]
                df_s = raw.copy()
                if isinstance(df_s.columns, pd.MultiIndex):
                    df_s.columns = [c[0] for c in df_s.columns]
                df_s = df_s.dropna(subset=["Close"]).reset_index()
                for _, r in df_s.iterrows():
                    all_rows.append({
                        "stock_id": sid,
                        "date": pd.to_datetime(r.iloc[0]).strftime("%Y-%m-%d"),
                        "open": float(r["Open"]),
                        "high": float(r["High"]),
                        "low": float(r["Low"]),
                        "close": float(r["Close"]),
                        "volume": float(r["Volume"]),
                    })
            else:
                available = raw.columns.get_level_values(0).unique()
                for yf_t in batch:
                    if yf_t not in available:
                        continue
                    sid = ticker_map[yf_t]
                    try:
                        sub = raw[yf_t].dropna(subset=["Close"]).reset_index()
                        for _, r in sub.iterrows():
                            all_rows.append({
                                "stock_id": sid,
                                "date": pd.to_datetime(r.iloc[0]).strftime("%Y-%m-%d"),
                                "open": float(r["Open"]),
                                "high": float(r["High"]),
                                "low": float(r["Low"]),
                                "close": float(r["Close"]),
                                "volume": float(r["Volume"]),
                            })
                    except Exception:
                        continue

            if all_rows:
                df_out = pd.DataFrame(all_rows)
                writer.upsert_daily_prices(df_out)
                total_written += len(all_rows)
        except Exception as exc:
            print(f"[Backfill] batch error: {exc}")
            continue

        if (start // batch_size) % 5 == 4:
            print(f"[Backfill] progress: {start + batch_size}/{len(all_tickers)}, wrote {total_written} rows")

    print(f"[Backfill] done: {total_written} rows written")
    return total_written


def run_startup_catchup() -> None:
    """
    Startup catch-up: if today's data is sparse, run a full yfinance backfill.
    Called from main.py after Shioaji login.
    """
    from backend.db.connection import duck_read

    today_str = datetime.date.today().isoformat()
    with duck_read() as conn:
        total_stocks = conn.execute("SELECT COUNT(*) FROM stock_info WHERE is_active").fetchone()[0]
        today_count = conn.execute(
            "SELECT COUNT(DISTINCT stock_id) FROM daily_prices WHERE date = ?::DATE",
            [today_str],
        ).fetchone()[0]

    coverage = today_count / total_stocks if total_stocks > 0 else 0
    print(f"[StartupCatchup] today={today_str}: {today_count}/{total_stocks} stocks ({coverage:.0%})")

    if coverage < 0.8:
        print(f"[StartupCatchup] Coverage < 80%, running yfinance backfill (1mo)...")
        stock_df = queries.get_active_stocks()
        written = _backfill_via_yfinance(stock_df, period="1mo")
        print(f"[StartupCatchup] Backfill complete: {written} rows")
    else:
        print(f"[StartupCatchup] Coverage OK, no backfill needed")


def _run_intraday_update() -> None:
    """
    Core intraday update: fetch all active stocks' latest OHLCV and write to DuckDB.
    Called by scheduler every 5 min during market hours, and once post-close at 14:05.
    """
    global _update_state
    _update_state["status"] = "running"
    _update_state["message"] = "初始化中…"
    _update_state["stocks_updated"] = 0
    start_time = time.time()

    try:
        stock_df = queries.get_active_stocks()
        if stock_df.empty:
            _update_state["status"] = "error"
            _update_state["message"] = "stock_info 表為空，無法更新"
            return

        total = len(stock_df)
        _update_state["total_stocks"] = total
        _update_state["message"] = "正在用永豐快照批次更新…"

        updated = _update_via_sinopac(stock_df)
        if updated <= 0:
            _update_state["message"] = "永豐快照不可用，改用 yfinance…"
            updated = _update_via_yfinance(stock_df)

        elapsed = time.time() - start_time
        _update_state.update({
            "status": "done",
            "stocks_updated": updated,
            "elapsed_sec": round(elapsed, 1),
            "last_updated": datetime.datetime.now().isoformat(),
            "message": f"完成！{updated} 檔 / {elapsed:.0f}s",
        })
        print(f"[IntradayUpdate] Done: {updated} stocks in {elapsed:.1f}s")

    except Exception as exc:
        _update_state["status"] = "error"
        _update_state["message"] = f"更新失敗: {exc}"
        print(f"[IntradayUpdate] Error: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
# API endpoints
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/api/v1/intraday/status")
async def get_intraday_status():
    return {**_update_state, "is_market_hours": _is_market_hours()}


@router.post("/api/v1/intraday/refresh")
async def trigger_intraday_refresh(background_tasks: BackgroundTasks):
    if _update_state["status"] == "running":
        return {"message": "更新進行中，請稍後", "status": "running"}
    background_tasks.add_task(_run_intraday_update)
    return {"message": "已觸發盤中更新", "status": "started"}
