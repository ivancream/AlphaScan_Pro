"""
Batch upsert utilities for DuckDB market data.

All writes go through duck_write() (process-wide DuckDB connection;
serialized with RLock) and auto-commits on success / rolls back on failure.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from .connection import duck_write


# ──────────────────────────────────────────────────────────────────────────────
# stock_info
# ──────────────────────────────────────────────────────────────────────────────

def upsert_stock_info(rows: List[Tuple[str, str, str, bool]]) -> int:
    """
    Upsert stock_info.
    rows: [(stock_id, name, market, is_active), ...]
    """
    if not rows:
        return 0
    with duck_write() as conn:
        conn.executemany(
            """
            INSERT INTO stock_info (stock_id, name, market, is_active, updated_at)
            VALUES (?, ?, ?, ?, now())
            ON CONFLICT (stock_id) DO UPDATE SET
                name       = excluded.name,
                market     = excluded.market,
                is_active  = excluded.is_active,
                updated_at = now()
            """,
            rows,
        )
    _log_update("stock_info", len(rows))
    return len(rows)


# ──────────────────────────────────────────────────────────────────────────────
# stock_sectors (TWSE industry + theme micro)
# ──────────────────────────────────────────────────────────────────────────────

def upsert_stock_sectors(
    rows: List[Tuple[str, str, str, Optional[str], Optional[str]]],
) -> int:
    """
    Upsert stock_sectors.
    rows: [(stock_id, macro, meso, micro, industry_raw), ...]
    """
    if not rows:
        return 0
    with duck_write() as conn:
        conn.executemany(
            """
            INSERT INTO stock_sectors
                (stock_id, macro, meso, micro, industry_raw, updated_at)
            VALUES (?, ?, ?, ?, ?, now())
            ON CONFLICT (stock_id) DO UPDATE SET
                macro        = excluded.macro,
                meso         = excluded.meso,
                micro        = excluded.micro,
                industry_raw = excluded.industry_raw,
                updated_at   = now()
            """,
            rows,
        )
    _log_update("stock_sectors", len(rows))
    return len(rows)


def update_stock_sectors_micro_only(rows: List[Tuple[str, Optional[str]]]) -> int:
    """
    只更新 stock_sectors.micro（不動 macro／meso／industry_raw）。
    rows: [(stock_id, micro), ...]，micro 可為 None 表示清空題材欄。
    """
    if not rows:
        return 0
    with duck_write() as conn:
        conn.executemany(
            """
            UPDATE stock_sectors
            SET micro = ?, updated_at = now()
            WHERE stock_id = ?
            """,
            [(micro, sid) for sid, micro in rows],
        )
    _log_update("stock_sectors_micro", len(rows))
    return len(rows)


# ──────────────────────────────────────────────────────────────────────────────
# daily_prices
# ──────────────────────────────────────────────────────────────────────────────

def upsert_daily_prices(df: pd.DataFrame) -> int:
    """
    Upsert OHLCV rows.
    df must have: stock_id, date, open, high, low, close, volume
    Optional: disposition_mins (defaults to 0)
    """
    if df is None or df.empty:
        return 0

    df = df.copy()
    if "disposition_mins" not in df.columns:
        df["disposition_mins"] = 0

    cols = ["stock_id", "date", "open", "high", "low", "close", "volume", "disposition_mins"]
    df = df[cols]

    with duck_write() as conn:
        conn.execute(
            """
            INSERT INTO daily_prices
                (stock_id, date, open, high, low, close, volume, disposition_mins)
            SELECT stock_id, date::DATE, open, high, low, close, volume, disposition_mins
            FROM df
            ON CONFLICT (stock_id, date) DO UPDATE SET
                open             = excluded.open,
                high             = excluded.high,
                low              = excluded.low,
                close            = excluded.close,
                volume           = excluded.volume,
                disposition_mins = excluded.disposition_mins
            """
        )
    _log_update("daily_prices", len(df))
    return len(df)


def set_disposition_mins(stock_id: str, date_str: str, minutes: int) -> None:
    """Update disposition_mins for a specific stock+date."""
    with duck_write() as conn:
        conn.execute(
            """
            UPDATE daily_prices
            SET disposition_mins = ?
            WHERE stock_id = ? AND date = ?::DATE
            """,
            [minutes, stock_id, date_str],
        )


# ──────────────────────────────────────────────────────────────────────────────
# dividends
# ──────────────────────────────────────────────────────────────────────────────

def upsert_dividends(rows: List[Tuple[str, str, float]]) -> int:
    """
    Upsert dividend records.
    rows: [(stock_id, ex_date_str, amount), ...]
    """
    if not rows:
        return 0
    with duck_write() as conn:
        conn.executemany(
            """
            INSERT INTO dividends (stock_id, ex_date, amount)
            VALUES (?, ?::DATE, ?)
            ON CONFLICT (stock_id, ex_date) DO UPDATE SET
                amount = excluded.amount
            """,
            rows,
        )
    _log_update("dividends", len(rows))
    return len(rows)


# ──────────────────────────────────────────────────────────────────────────────
# tdcc_distribution
# ──────────────────────────────────────────────────────────────────────────────

def upsert_tdcc(df: pd.DataFrame) -> int:
    """
    Upsert TDCC distribution rows.
    df must have: stock_id, date, total_holders, retail_pct, whale_400_pct, whale_1000_pct
    """
    if df is None or df.empty:
        return 0
    with duck_write() as conn:
        conn.execute(
            """
            INSERT INTO tdcc_distribution
                (stock_id, date, total_holders, retail_pct, whale_400_pct, whale_1000_pct)
            SELECT stock_id, date::DATE, total_holders, retail_pct, whale_400_pct, whale_1000_pct
            FROM df
            ON CONFLICT (stock_id, date) DO UPDATE SET
                total_holders  = excluded.total_holders,
                retail_pct     = excluded.retail_pct,
                whale_400_pct  = excluded.whale_400_pct,
                whale_1000_pct = excluded.whale_1000_pct
            """
        )
    _log_update("tdcc_distribution", len(df))
    return len(df)


# ──────────────────────────────────────────────────────────────────────────────
# correlations
# ──────────────────────────────────────────────────────────────────────────────

def upsert_correlations(df: pd.DataFrame, calc_date: str) -> int:
    """
    Full replace of correlations table.
    df must have: stock_id, peer_id, correlation（可為空 DataFrame，仍會清空舊表並更新 meta）
    Optional: adf_p_value, eg_p_value, half_life, ratio_mean, ratio_std,
    zero_crossings, hedge_ratio, composite_score
    （舊遷移腳本未帶欄位時自動補 NULL / 0）
    """
    if df is None:
        return 0
    with duck_write() as conn:
        conn.execute("DELETE FROM correlations")
        if not df.empty:
            df = df.copy()
            df["calc_date"] = calc_date
            if "adf_p_value" not in df.columns:
                df["adf_p_value"] = np.nan
            if "eg_p_value" not in df.columns:
                df["eg_p_value"] = np.nan
            if "half_life" not in df.columns:
                df["half_life"] = np.nan
            if "ratio_mean" not in df.columns:
                df["ratio_mean"] = np.nan
            if "ratio_std" not in df.columns:
                df["ratio_std"] = np.nan
            if "zero_crossings" not in df.columns:
                df["zero_crossings"] = 0
            if "hedge_ratio" not in df.columns:
                df["hedge_ratio"] = np.nan
            if "composite_score" not in df.columns:
                df["composite_score"] = np.nan
            conn.execute(
                """
                INSERT INTO correlations
                    (stock_id, peer_id, correlation, adf_p_value, eg_p_value, half_life,
                     ratio_mean, ratio_std, zero_crossings, hedge_ratio, composite_score, calc_date)
                SELECT stock_id, peer_id, correlation, adf_p_value, eg_p_value, half_life,
                       ratio_mean, ratio_std, zero_crossings, hedge_ratio, composite_score, calc_date::DATE
                FROM df
                """
            )
        conn.execute(
            """
            INSERT INTO correlation_meta (key, value) VALUES ('last_calc_date', ?)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value
            """,
            [calc_date],
        )
        count_row = conn.execute(
            "SELECT COUNT(DISTINCT stock_id)::VARCHAR FROM correlations"
        ).fetchone()
        conn.execute(
            """
            INSERT INTO correlation_meta (key, value) VALUES ('stock_count', ?)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value
            """,
            [count_row[0] if count_row else "0"],
        )
    n = 0 if df.empty else len(df)
    _log_update("correlations", n)
    return n


# ──────────────────────────────────────────────────────────────────────────────
# disposition_events
# ──────────────────────────────────────────────────────────────────────────────

def upsert_disposition_events(rows: List[Tuple]) -> int:
    """
    Upsert disposition events.
    rows: [(stock_id, disp_start, disp_end_or_None, reason, minutes), ...]
    """
    if not rows:
        return 0
    with duck_write() as conn:
        conn.executemany(
            """
            INSERT INTO disposition_events (stock_id, disp_start, disp_end, reason, minutes)
            VALUES (?, ?::DATE, ?::DATE, ?, ?)
            ON CONFLICT (stock_id, disp_start) DO UPDATE SET
                disp_end = excluded.disp_end,
                reason   = excluded.reason,
                minutes  = excluded.minutes
            """,
            rows,
        )
    _log_update("disposition_events", len(rows))
    return len(rows)


# ──────────────────────────────────────────────────────────────────────────────
# warrant_master (TWSE MOPS 公開資料)
# ──────────────────────────────────────────────────────────────────────────────

def upsert_warrant_master(
    rows: List[
        Tuple[str, str, str, Optional[str], str, float, float, date, str]
    ],
) -> int:
    """
    Upsert warrant_master.
    rows: [(warrant_code, warrant_name, underlying_symbol, underlying_name,
            cp, strike, exercise_ratio, expiry_date, board), ...]
    board: 'TSE' | 'OTC'
    """
    if not rows:
        return 0
    with duck_write() as conn:
        conn.executemany(
            """
            INSERT INTO warrant_master (
                warrant_code, warrant_name, underlying_symbol, underlying_name,
                cp, strike, exercise_ratio, expiry_date, board, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (warrant_code) DO UPDATE SET
                warrant_name       = excluded.warrant_name,
                underlying_symbol  = excluded.underlying_symbol,
                underlying_name    = excluded.underlying_name,
                cp                 = excluded.cp,
                strike             = excluded.strike,
                exercise_ratio     = excluded.exercise_ratio,
                expiry_date        = excluded.expiry_date,
                board              = excluded.board,
                updated_at         = now()
            """,
            rows,
        )
    _log_update("warrant_master", len(rows))
    return len(rows)


# warrant_positions / branch_trading
# ──────────────────────────────────────────────────────────────────────────────

def upsert_warrant_positions(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    with duck_write() as conn:
        conn.execute(
            """
            INSERT INTO warrant_positions
                (snapshot_date, stock_id, stock_name, branch_name,
                 position_shares, est_pnl, est_pnl_pct, amount_k, type)
            SELECT snapshot_date::DATE, stock_id, stock_name, branch_name,
                   position_shares, est_pnl, est_pnl_pct, amount_k, type
            FROM df
            ON CONFLICT (snapshot_date, stock_id, branch_name, type) DO UPDATE SET
                position_shares = excluded.position_shares,
                est_pnl         = excluded.est_pnl,
                est_pnl_pct     = excluded.est_pnl_pct,
                amount_k        = excluded.amount_k
            """
        )
    return len(df)


def upsert_branch_trading(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    with duck_write() as conn:
        conn.execute(
            """
            INSERT INTO branch_trading
                (trade_date, stock_id, stock_name, branch_name,
                 buy_shares, sell_shares, net_shares, side)
            SELECT trade_date::DATE, stock_id, stock_name, branch_name,
                   buy_shares, sell_shares, net_shares, side
            FROM df
            ON CONFLICT (trade_date, stock_id, branch_name) DO UPDATE SET
                buy_shares  = excluded.buy_shares,
                sell_shares = excluded.sell_shares,
                net_shares  = excluded.net_shares,
                side        = excluded.side
            """
        )
    return len(df)


# ──────────────────────────────────────────────────────────────────────────────
# update_log helper
# ──────────────────────────────────────────────────────────────────────────────

def _log_update(
    table_name: str,
    row_count: int,
    status: str = "success",
    message: str = "",
) -> None:
    try:
        with duck_write() as conn:
            conn.execute(
                """
                INSERT INTO update_log (table_name, last_update, row_count, status, message)
                VALUES (?, now(), ?, ?, ?)
                ON CONFLICT (table_name) DO UPDATE SET
                    last_update = now(),
                    row_count   = excluded.row_count,
                    status      = excluded.status,
                    message     = excluded.message
                """,
                [table_name, row_count, status, message],
            )
    except Exception as e:
        print(f"[Writer] update_log failed for {table_name}: {e}")


def log_update_error(table_name: str, message: str) -> None:
    """Record a failed update in update_log."""
    _log_update(table_name, 0, "failed", message)
