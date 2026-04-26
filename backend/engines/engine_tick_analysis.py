from __future__ import annotations

from typing import Any, Dict, List

import duckdb
import pandas as pd


def _clamp_percentile(pr: float) -> float:
    """PR 為百分位整數時先除以 100；允許 0.5–0.999 的小數分位。"""
    p = float(pr)
    if p > 1.0:
        p = p / 100.0
    return max(0.5, min(0.999, p))


def analyze_large_players(
    rows: List[Dict[str, Any]],
    symbol: str,
    *,
    percentile: float = 0.97,
) -> Dict[str, Any]:
    """
    Analyze large player flow using amount-based percentile threshold (default PR97).

    amount = close * volume * 1000（張 × 千元 × 1000 → 元）
    - q_pr = quantile_cont(amount, percentile)
    - 動態下限（避免低價股被硬卡 100 萬）：floor = min(450_000, max(30_000, median(amount) * 2))
    - final_threshold = max(q_pr, floor)
    """
    pct = _clamp_percentile(percentile)
    pr_display = int(round(pct * 100)) if pct <= 1.0 else int(percentile)
    normalized = str(symbol or "").strip().upper()
    empty_payload: Dict[str, Any] = {
        "symbol": normalized,
        "threshold": None,
        "threshold_quantile": None,
        "min_amount_floor": None,
        "buy_lots": 0,
        "sell_lots": 0,
        "net_lots": 0,
        "details": [],
        "pr": pr_display,
        "percentile": pct,
    }
    if not rows:
        return empty_payload

    normalized_rows: List[Dict[str, Any]] = []
    for r in rows:
        price = float(r.get("price") or 0)
        volume = int(r.get("volume") or 0)
        tick_dir = str(r.get("tick_dir") or "NONE").upper()
        tick_type = 0
        if tick_dir == "OUTER":
            tick_type = 1
        elif tick_dir == "INNER":
            tick_type = 2
        normalized_rows.append(
            {
                "ts": r.get("ts") or "",
                "price": price,
                "volume": volume,
                "tick_dir": tick_dir,
                "tick_type": tick_type,
            }
        )

    df = pd.DataFrame(normalized_rows)
    if df.empty:
        return empty_payload

    conn = duckdb.connect(":memory:")
    try:
        conn.register("ticks_df", df)
        # Keep all amount-related math in DOUBLE to avoid integer overflow.
        threshold_row = conn.execute(
            """
            WITH base AS (
                SELECT
                    ts,
                    CAST(price AS DOUBLE) AS close,
                    CAST(volume AS BIGINT) AS volume,
                    CAST(tick_type AS INTEGER) AS tick_type,
                    tick_dir,
                    CAST(price AS DOUBLE) * CAST(volume AS DOUBLE) * 1000.0 AS amount
                FROM ticks_df
                WHERE CAST(price AS DOUBLE) > 0
                  AND CAST(volume AS BIGINT) > 0
            ),
            stats AS (
                SELECT
                    quantile_cont(amount, ?)::DOUBLE AS q_pr,
                    quantile_cont(amount, 0.5)::DOUBLE AS med_amt
                FROM base
            )
            SELECT
                GREATEST(
                    COALESCE(q_pr, 0.0),
                    LEAST(
                        450000.0,
                        GREATEST(30000.0, COALESCE(med_amt, 0.0) * 2.0)
                    )
                )::DOUBLE AS final_threshold,
                COALESCE(q_pr, 0.0)::DOUBLE AS threshold_quantile,
                LEAST(
                    450000.0,
                    GREATEST(30000.0, COALESCE(med_amt, 0.0) * 2.0)
                )::DOUBLE AS min_amount_floor
            FROM stats
            """,
            [pct],
        ).fetchone()
        if threshold_row and threshold_row[0] is not None:
            final_threshold = float(threshold_row[0])
            threshold_quantile = float(threshold_row[1] or 0.0)
            min_amount_floor = float(threshold_row[2] or 0.0)
        else:
            final_threshold = 30_000.0
            threshold_quantile = 0.0
            min_amount_floor = 30_000.0

        agg_row = conn.execute(
            """
            WITH base AS (
                SELECT
                    ts,
                    CAST(price AS DOUBLE) AS close,
                    CAST(volume AS BIGINT) AS volume,
                    CAST(tick_type AS INTEGER) AS tick_type,
                    tick_dir,
                    CAST(price AS DOUBLE) * CAST(volume AS DOUBLE) * 1000.0 AS amount
                FROM ticks_df
                WHERE CAST(price AS DOUBLE) > 0
                  AND CAST(volume AS BIGINT) > 0
            ),
            large AS (
                SELECT *
                FROM base
                WHERE amount >= ?
            )
            SELECT
                COALESCE(SUM(CASE WHEN tick_type = 1 THEN amount ELSE 0 END), 0.0) AS buy_amount,
                COALESCE(SUM(CASE WHEN tick_type = 2 THEN amount ELSE 0 END), 0.0) AS sell_amount,
                COALESCE(SUM(CASE WHEN tick_type = 1 THEN volume ELSE 0 END), 0) AS buy_lots,
                COALESCE(SUM(CASE WHEN tick_type = 2 THEN volume ELSE 0 END), 0) AS sell_lots
            FROM large
            """,
            [final_threshold],
        ).fetchone()

        details_rows = conn.execute(
            """
            WITH base AS (
                SELECT
                    ts,
                    CAST(price AS DOUBLE) AS close,
                    CAST(volume AS BIGINT) AS volume,
                    CAST(tick_type AS INTEGER) AS tick_type,
                    tick_dir,
                    CAST(price AS DOUBLE) * CAST(volume AS DOUBLE) * 1000.0 AS amount
                FROM ticks_df
                WHERE CAST(price AS DOUBLE) > 0
                  AND CAST(volume AS BIGINT) > 0
            )
            SELECT
                ts,
                close AS price,
                volume,
                tick_dir,
                CASE
                    WHEN tick_type = 1 THEN 'BUY'
                    WHEN tick_type = 2 THEN 'SELL'
                    ELSE 'UNKNOWN'
                END AS side,
                amount
            FROM base
            WHERE amount >= ?
            ORDER BY amount DESC, ts DESC
            """,
            [final_threshold],
        ).fetchall()

        buy_lots = int(agg_row[2] or 0) if agg_row else 0
        sell_lots = int(agg_row[3] or 0) if agg_row else 0

        details = [
            {
                "ts": row[0],
                "price": float(row[1]) if row[1] is not None else None,
                "volume": int(row[2]) if row[2] is not None else 0,
                "tick_dir": row[3],
                "side": row[4],
                "amount": float(row[5]) if row[5] is not None else 0.0,
            }
            for row in details_rows
        ]

        return {
            "symbol": normalized,
            "threshold": float(final_threshold),
            "threshold_quantile": float(threshold_quantile),
            "min_amount_floor": float(min_amount_floor),
            "buy_lots": buy_lots,
            "sell_lots": sell_lots,
            "net_lots": buy_lots - sell_lots,
            "details": details,
            "pr": pr_display,
            "percentile": pct,
        }
    finally:
        conn.close()
