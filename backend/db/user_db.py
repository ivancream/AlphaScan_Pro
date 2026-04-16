"""
SQLite user.db operations — watchlist and intraday signals.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from .connection import user_db


# ──────────────────────────────────────────────────────────────────────────────
# Watchlist
# ──────────────────────────────────────────────────────────────────────────────

def get_watchlist() -> List[str]:
    """Return list of stock_ids ordered by most-recently added."""
    with user_db() as conn:
        rows = conn.execute(
            "SELECT stock_id FROM watchlist ORDER BY added_at DESC"
        ).fetchall()
    return [r["stock_id"] for r in rows]


def add_to_watchlist(stock_id: str) -> bool:
    """Add stock to watchlist. Returns True if newly added, False if duplicate."""
    try:
        with user_db() as conn:
            changes_before = conn.execute(
                "SELECT COUNT(*) FROM watchlist WHERE stock_id = ?", (stock_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (stock_id, added_at) VALUES (?, ?)",
                (stock_id, datetime.now().isoformat()),
            )
        return changes_before == 0
    except Exception:
        return False


def remove_from_watchlist(stock_id: str) -> None:
    """Remove stock from watchlist."""
    with user_db() as conn:
        conn.execute("DELETE FROM watchlist WHERE stock_id = ?", (stock_id,))


# ──────────────────────────────────────────────────────────────────────────────
# Intraday signals
# ──────────────────────────────────────────────────────────────────────────────

def write_signals(
    scan_id: str,
    scan_time: str,
    results: Dict[str, List[Dict[str, Any]]],
) -> None:
    """Bulk-write scanner results to intraday_signals table."""
    rows = []
    for strategy, items in results.items():
        for item in items:
            rows.append((
                scan_id,
                scan_time,
                strategy,
                str(item.get("代號", "")),
                str(item.get("名稱", "")),
                str(item.get("市場", "")),
                float(item.get("收盤價", 0) or 0),
                float(item.get("今日漲跌幅(%)", 0) or 0),
                int(item.get("成交量(張)", 0) or 0),
                json.dumps(item, ensure_ascii=False, default=str),
            ))

    if not rows:
        return

    with user_db() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO intraday_signals
                (scan_id, scan_time, strategy, stock_id, name, market_type,
                 close, change_pct, volume_k, signal_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        # Prune: keep only the 5 most recent scan_ids per strategy
        conn.execute(
            """
            DELETE FROM intraday_signals
            WHERE scan_id NOT IN (
                SELECT DISTINCT scan_id FROM intraday_signals
                ORDER BY scan_time DESC LIMIT 5
            )
            """
        )


def get_latest_signals(strategy: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Return the most recent scan's results for a given strategy."""
    with user_db() as conn:
        rows = conn.execute(
            """
            SELECT signal_json FROM intraday_signals
            WHERE strategy = ?
              AND scan_time = (
                  SELECT MAX(scan_time) FROM intraday_signals WHERE strategy = ?
              )
            LIMIT ?
            """,
            (strategy, strategy, limit),
        ).fetchall()
    return [json.loads(r["signal_json"]) for r in rows]


def get_scan_status() -> Dict[str, Any]:
    """Return the latest scan_id and scan_time across all strategies."""
    with user_db() as conn:
        row = conn.execute(
            "SELECT scan_id, scan_time FROM intraday_signals ORDER BY scan_time DESC LIMIT 1"
        ).fetchone()
    if row:
        return {"scan_id": row["scan_id"], "last_scan_time": row["scan_time"]}
    return {"scan_id": None, "last_scan_time": None}
