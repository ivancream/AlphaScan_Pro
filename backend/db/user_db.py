"""
SQLite user.db operations — watchlist and intraday signals.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

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


def get_latest_scan_time_for_strategy(strategy: str) -> Optional[str]:
    """最近一次寫入 intraday_signals 的 scan_time（ISO 字串），供 API 在記憶體為空時對齊 last_run。"""
    with user_db() as conn:
        row = conn.execute(
            "SELECT MAX(scan_time) AS t FROM intraday_signals WHERE strategy = ?",
            (strategy,),
        ).fetchone()
    if row and row["t"]:
        return str(row["t"])
    return None


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


# ─────────────────────────────────────────────────────────────────────────────
# Intraday monitor event replay
# ─────────────────────────────────────────────────────────────────────────────

def write_monitor_event(event: Dict[str, Any], source: str = "shioaji") -> None:
    """Persist one intraday monitor signal for replay and after-hours review."""
    event_id = str(event.get("id") or "")
    if not event_id:
        return
    now = datetime.now().isoformat()
    with user_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO intraday_monitor_events
                (id, event_time, symbol, related_symbol, event_type, side,
                 price, volume, source, signal_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                str(event.get("time") or now),
                str(event.get("symbol") or ""),
                str(event.get("related_symbol") or event.get("symbol") or ""),
                str(event.get("event_type") or ""),
                str(event.get("side") or ""),
                float(event.get("price") or 0),
                int(event.get("volume") or 0),
                source,
                json.dumps(event, ensure_ascii=False, default=str),
                now,
            ),
        )


def get_recent_monitor_events(
    *,
    symbol: Optional[str] = None,
    limit: int = 300,
) -> List[Dict[str, Any]]:
    """Read recent intraday monitor events from user.db."""
    lim = max(1, min(int(limit or 300), 2000))
    with user_db() as conn:
        if symbol:
            rows = conn.execute(
                """
                SELECT signal_json
                FROM intraday_monitor_events
                WHERE related_symbol = ? OR symbol = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (symbol, symbol, lim),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT signal_json
                FROM intraday_monitor_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (lim,),
            ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        try:
            out.append(json.loads(row["signal_json"]))
        except Exception:
            continue
    return out
