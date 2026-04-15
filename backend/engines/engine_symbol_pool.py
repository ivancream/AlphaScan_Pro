from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
DB_PATH = PROJECT_ROOT / "databases" / "db_technical_prices.db"


@dataclass
class SymbolProfile:
    stock_id: str
    ticker: str
    name: str
    reference_close: float | None


def _build_ticker(stock_id: str, market_type: str | None) -> str:
    if market_type == "上櫃":
        return f"{stock_id}.TWO"
    return f"{stock_id}.TW"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _load_watchlist_symbols(conn: sqlite3.Connection) -> List[str]:
    if not _table_exists(conn, "watchlist"):
        return []

    rows = conn.execute(
        """
        SELECT stock_id
        FROM watchlist
        ORDER BY added_at DESC
        """
    ).fetchall()
    return [str(row[0]) for row in rows if row and row[0]]


def _load_top_n_symbols(conn: sqlite3.Connection, top_n: int) -> List[str]:
    if top_n <= 0:
        return []

    latest_date_row = conn.execute("SELECT MAX(date) FROM daily_price").fetchone()
    if not latest_date_row or not latest_date_row[0]:
        return []

    latest_date = latest_date_row[0]
    rows = conn.execute(
        """
        SELECT stock_id
        FROM daily_price
        WHERE date = ?
        ORDER BY volume DESC
        LIMIT ?
        """,
        (latest_date, top_n),
    ).fetchall()
    return [str(row[0]) for row in rows if row and row[0]]


def _load_symbol_metadata(conn: sqlite3.Connection, symbols: List[str]) -> Dict[str, SymbolProfile]:
    if not symbols:
        return {}

    placeholders = ",".join("?" for _ in symbols)
    rows = conn.execute(
        f"""
        WITH latest AS (
            SELECT stock_id, close
            FROM daily_price
            WHERE (stock_id, date) IN (
                SELECT stock_id, MAX(date)
                FROM daily_price
                GROUP BY stock_id
            )
        )
        SELECT si.stock_id, COALESCE(si.name, si.stock_id), si.market_type, latest.close
        FROM stock_info si
        LEFT JOIN latest ON latest.stock_id = si.stock_id
        WHERE si.stock_id IN ({placeholders})
        """,
        symbols,
    ).fetchall()

    profile_map: Dict[str, SymbolProfile] = {}
    for stock_id, name, market_type, close in rows:
        profile_map[str(stock_id)] = SymbolProfile(
            stock_id=str(stock_id),
            ticker=_build_ticker(str(stock_id), market_type),
            name=str(name),
            reference_close=float(close) if close is not None else None,
        )

    # 若 stock_info 缺漏，至少建立保底 profile
    for symbol in symbols:
        if symbol in profile_map:
            continue
        profile_map[symbol] = SymbolProfile(
            stock_id=symbol,
            ticker=_build_ticker(symbol, None),
            name=symbol,
            reference_close=None,
        )

    return profile_map


def get_symbol_profile(stock_id: str) -> dict | None:
    """
    取得單一股票的 metadata，供即時引擎動態把個股頁標的加入訂閱池。
    """
    if not DB_PATH.exists():
        return None

    sid = str(stock_id).strip()
    if not sid:
        return None

    conn = sqlite3.connect(DB_PATH)
    try:
        profiles = _load_symbol_metadata(conn, [sid])
        profile = profiles.get(sid)
        return asdict(profile) if profile else None
    finally:
        conn.close()


def get_symbol_pool(top_n: int = 50) -> List[dict]:
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    try:
        watchlist_symbols = _load_watchlist_symbols(conn)
        top_symbols = _load_top_n_symbols(conn, top_n=top_n)

        merged_symbols: List[str] = []
        seen = set()
        for symbol in watchlist_symbols + top_symbols:
            if symbol in seen:
                continue
            seen.add(symbol)
            merged_symbols.append(symbol)

        profiles = _load_symbol_metadata(conn, merged_symbols)
        return [asdict(profiles[symbol]) for symbol in merged_symbols if symbol in profiles]
    finally:
        conn.close()
