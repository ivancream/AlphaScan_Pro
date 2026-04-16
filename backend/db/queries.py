"""
Centralized read queries for AlphaScan Pro.
All SQL lives here — no ad-hoc query strings scattered in engines/APIs.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from .connection import duck_read, user_db


# ──────────────────────────────────────────────────────────────────────────────
# stock_info
# ──────────────────────────────────────────────────────────────────────────────

def get_stock_name(stock_id: str) -> str:
    """Look up a stock's Chinese name. Returns stock_id if not found."""
    try:
        with duck_read() as conn:
            row = conn.execute(
                "SELECT name FROM stock_info WHERE stock_id = ?", [stock_id]
            ).fetchone()
            return row[0] if row else stock_id
    except Exception:
        return stock_id


def get_stock_market(stock_id: str) -> str:
    """Return market code: 'TSE', 'OTC', or '' if unknown."""
    try:
        with duck_read() as conn:
            row = conn.execute(
                "SELECT market FROM stock_info WHERE stock_id = ?", [stock_id]
            ).fetchone()
            return row[0] if row else ""
    except Exception:
        return ""


def get_stock_info_df() -> pd.DataFrame:
    """Return full stock_info as DataFrame (stock_id, name, market, is_active)."""
    with duck_read() as conn:
        return conn.execute(
            "SELECT stock_id, name, market, is_active FROM stock_info"
        ).df()


def get_active_stocks() -> pd.DataFrame:
    """Return only active stocks."""
    with duck_read() as conn:
        return conn.execute(
            "SELECT stock_id, name, market FROM stock_info WHERE is_active = TRUE"
        ).df()


def resolve_stock_id(query: str) -> Optional[str]:
    """
    Resolve user input (code or partial name) to a pure stock_id.
    Returns None if no match found.
    """
    q = query.strip()
    if not q:
        return None
    with duck_read() as conn:
        # Exact code
        row = conn.execute(
            "SELECT stock_id FROM stock_info WHERE stock_id = ?", [q]
        ).fetchone()
        if row:
            return row[0]
        # Exact name
        row = conn.execute(
            "SELECT stock_id FROM stock_info WHERE name = ?", [q]
        ).fetchone()
        if row:
            return row[0]
        # Partial name
        row = conn.execute(
            "SELECT stock_id FROM stock_info WHERE name LIKE ? "
            "ORDER BY LENGTH(name) ASC LIMIT 1",
            [f"%{q}%"],
        ).fetchone()
        if row:
            return row[0]
    return None


# ──────────────────────────────────────────────────────────────────────────────
# daily_prices
# ──────────────────────────────────────────────────────────────────────────────

def get_price_df(stock_id: str, period: str = "1y") -> pd.DataFrame:
    """
    Fetch OHLCV history for one stock up to yesterday.
    Returns DataFrame with columns: date, open, high, low, close, volume, disposition_mins
    """
    _MAP = {
        "1mo": 30, "3mo": 90, "6mo": 180,
        "1y": 365, "2y": 730, "5y": 1825, "max": 3650,
    }
    days = _MAP.get(period.lower(), 365)
    start = (date.today() - timedelta(days=days)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    with duck_read() as conn:
        return conn.execute(
            """
            SELECT date, open, high, low, close, volume,
                   COALESCE(disposition_mins, 0) AS disposition_mins
            FROM daily_prices
            WHERE stock_id = ? AND date >= ? AND date <= ?
            ORDER BY date ASC
            """,
            [stock_id, start, yesterday],
        ).df()


def get_price_df_all(cutoff_days: int = 500) -> pd.DataFrame:
    """
    Batch-fetch history for ALL stocks (used by scanner).
    Columns: stock_id, date, open, high, low, close, volume, disposition_mins
    """
    cutoff = (date.today() - timedelta(days=cutoff_days)).isoformat()
    with duck_read() as conn:
        return conn.execute(
            """
            SELECT stock_id, date, open, high, low, close, volume,
                   COALESCE(disposition_mins, 0) AS disposition_mins
            FROM daily_prices
            WHERE date >= ?
            ORDER BY stock_id, date ASC
            """,
            [cutoff],
        ).df()


def get_latest_price_date() -> Optional[str]:
    """Return the most recent date in daily_prices as ISO string."""
    with duck_read() as conn:
        row = conn.execute(
            "SELECT MAX(date)::VARCHAR FROM daily_prices"
        ).fetchone()
        return row[0] if row and row[0] else None


def get_prev_close(stock_id: str, before_date: str) -> Optional[float]:
    """Return close price of the trading day immediately before before_date."""
    with duck_read() as conn:
        row = conn.execute(
            """
            SELECT close FROM daily_prices
            WHERE stock_id = ? AND date < ?
            ORDER BY date DESC LIMIT 1
            """,
            [stock_id, before_date],
        ).fetchone()
        return float(row[0]) if row else None


def get_price_for_symbols(
    symbols: List[str], days: int = 180
) -> pd.DataFrame:
    """
    Fetch OHLCV for a list of stock_ids (for spread / correlation calcs).
    Returns DataFrame with columns: stock_id, date, close
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    placeholders = ", ".join(["?"] * len(symbols))
    with duck_read() as conn:
        return conn.execute(
            f"""
            SELECT stock_id, date, close
            FROM daily_prices
            WHERE stock_id IN ({placeholders})
              AND date >= ?
              AND close IS NOT NULL
            ORDER BY date ASC
            """,
            symbols + [cutoff],
        ).df()


# ──────────────────────────────────────────────────────────────────────────────
# dividends
# ──────────────────────────────────────────────────────────────────────────────

def get_dividends(stock_id: str) -> pd.DataFrame:
    """Return dividend history. Columns: date (ex_date), dividend (amount)."""
    with duck_read() as conn:
        return conn.execute(
            """
            SELECT ex_date AS date, amount AS dividend
            FROM dividends
            WHERE stock_id = ?
            ORDER BY ex_date DESC
            """,
            [stock_id],
        ).df()


# ──────────────────────────────────────────────────────────────────────────────
# tdcc_distribution (chips)
# ──────────────────────────────────────────────────────────────────────────────

def get_chip_metrics(stock_id: str) -> Optional[Dict[str, Any]]:
    """
    Return the latest two weeks of TDCC data and compute week-on-week change.
    Returns None if insufficient data.
    """
    try:
        with duck_read() as conn:
            df = conn.execute(
                """
                SELECT date, retail_pct, whale_1000_pct
                FROM tdcc_distribution
                WHERE stock_id = ?
                ORDER BY date DESC LIMIT 2
                """,
                [stock_id],
            ).df()
        if len(df) < 2:
            return None
        latest, prev = df.iloc[0], df.iloc[1]
        retail_diff = float(latest["retail_pct"]) - float(prev["retail_pct"])
        whale_diff = float(latest["whale_1000_pct"]) - float(prev["whale_1000_pct"])
        return {
            "retail_chg": round(retail_diff, 2),
            "whale_chg": round(whale_diff, 2),
            "is_retail_up": retail_diff > 0,
            "is_whale_down": whale_diff < 0,
        }
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# correlations
# ──────────────────────────────────────────────────────────────────────────────

def get_top_correlations(stock_id: str, top_n: int = 10) -> List[Dict]:
    """Return top-N correlated peer stocks."""
    with duck_read() as conn:
        rows = conn.execute(
            """
            SELECT peer_id, correlation, calc_date::VARCHAR
            FROM correlations
            WHERE stock_id = ?
            ORDER BY correlation DESC LIMIT ?
            """,
            [stock_id, top_n],
        ).fetchall()
    return [{"peer_id": r[0], "correlation": r[1], "calc_date": r[2]} for r in rows]


def get_correlation_meta() -> Dict[str, str]:
    """Return correlation_meta as a plain dict."""
    with duck_read() as conn:
        rows = conn.execute(
            "SELECT key, value FROM correlation_meta"
        ).fetchall()
    return {r[0]: r[1] for r in rows}


# ──────────────────────────────────────────────────────────────────────────────
# disposition_events
# ──────────────────────────────────────────────────────────────────────────────

def get_disposition_events(stock_id: str) -> List[Dict]:
    """Return all historical disposition events for a stock."""
    with duck_read() as conn:
        rows = conn.execute(
            """
            SELECT stock_id, disp_start::VARCHAR, disp_end::VARCHAR,
                   reason, minutes
            FROM disposition_events
            WHERE stock_id = ?
            ORDER BY disp_start DESC
            """,
            [stock_id],
        ).fetchall()
    return [
        {
            "stock_id": r[0],
            "disp_start": r[1],
            "disp_end": r[2],
            "reason": r[3],
            "minutes": r[4],
        }
        for r in rows
    ]


def get_current_disposition_stocks() -> pd.DataFrame:
    """Return currently active disposition events (disp_end is NULL or future)."""
    today = date.today().isoformat()
    with duck_read() as conn:
        return conn.execute(
            """
            SELECT stock_id, disp_start::VARCHAR, disp_end::VARCHAR,
                   reason, minutes
            FROM disposition_events
            WHERE disp_end IS NULL OR disp_end::VARCHAR >= ?
            ORDER BY disp_start DESC
            """,
            [today],
        ).df()


def get_disposition_events_overlapping(d_start: date, d_end: date) -> pd.DataFrame:
    """
    取出與日期區間 [d_start, d_end] 有交集的處置事件（含 disp_end 為 NULL 視為尚未結束）。
    用於掃描結果依「資料日期」對照處置狀態。
    """
    with duck_read() as conn:
        return conn.execute(
            """
            SELECT stock_id,
                   disp_start::VARCHAR AS disp_start,
                   disp_end::VARCHAR AS disp_end,
                   COALESCE(minutes, 0) AS minutes
            FROM disposition_events
            WHERE disp_start <= ?::DATE
              AND COALESCE(disp_end, DATE '2099-12-31') >= ?::DATE
            """,
            [d_end.isoformat(), d_start.isoformat()],
        ).df()


# ──────────────────────────────────────────────────────────────────────────────
# update_log
# ──────────────────────────────────────────────────────────────────────────────

def get_update_log() -> pd.DataFrame:
    """Return the full update_log table."""
    with duck_read() as conn:
        return conn.execute(
            """
            SELECT table_name,
                   last_update::VARCHAR AS last_update,
                   row_count,
                   status,
                   message
            FROM update_log
            ORDER BY table_name
            """
        ).df()


# ──────────────────────────────────────────────────────────────────────────────
# watchlist (SQLite user.db)
# ──────────────────────────────────────────────────────────────────────────────

def get_watchlist_ids() -> List[str]:
    """Return stock_ids from user watchlist."""
    with user_db() as conn:
        rows = conn.execute(
            "SELECT stock_id FROM watchlist ORDER BY added_at DESC"
        ).fetchall()
    return [r["stock_id"] for r in rows]
