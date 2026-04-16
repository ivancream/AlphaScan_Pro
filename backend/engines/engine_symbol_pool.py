"""
Symbol pool engine.

Builds the set of stock symbols that real-time engines should subscribe to:
  1. Everything on the user's watchlist (from SQLite user.db)
  2. Top-N by volume from the latest trading day (from DuckDB daily_prices)

Returns a list of SymbolProfile dicts ready for consumption by the live-quote
and all-around engines.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from backend.db.connection import duck_read, user_db


@dataclass
class SymbolProfile:
    stock_id: str
    ticker: str
    name: str
    reference_close: Optional[float]


def _build_ticker(stock_id: str, market: Optional[str]) -> str:
    if market == "OTC":
        return f"{stock_id}.TWO"
    return f"{stock_id}.TW"


def _load_watchlist_symbols() -> List[str]:
    """Return stock_ids from the user watchlist (SQLite user.db)."""
    try:
        with user_db() as conn:
            rows = conn.execute(
                "SELECT stock_id FROM watchlist ORDER BY added_at DESC"
            ).fetchall()
        return [str(r["stock_id"]) for r in rows if r and r["stock_id"]]
    except Exception:
        return []


def _load_top_n_symbols(top_n: int) -> List[str]:
    """Return stock_ids of top-N by volume on the latest available date."""
    if top_n <= 0:
        return []
    try:
        with duck_read() as conn:
            latest_date = conn.execute(
                "SELECT MAX(date) FROM daily_prices"
            ).fetchone()
            if not latest_date or not latest_date[0]:
                return []
            rows = conn.execute(
                """
                SELECT stock_id FROM daily_prices
                WHERE date = ?
                ORDER BY volume DESC
                LIMIT ?
                """,
                [latest_date[0], top_n],
            ).fetchall()
        return [str(r[0]) for r in rows if r and r[0]]
    except Exception:
        return []


def _load_symbol_metadata(symbols: List[str]) -> Dict[str, SymbolProfile]:
    """Fetch name, market and latest close for a list of stock_ids."""
    if not symbols:
        return {}

    marks = ",".join(["?" for _ in symbols])
    try:
        with duck_read() as conn:
            rows = conn.execute(
                f"""
                WITH latest AS (
                    SELECT stock_id, close
                    FROM daily_prices
                    WHERE (stock_id, date) IN (
                        SELECT stock_id, MAX(date)
                        FROM daily_prices
                        GROUP BY stock_id
                    )
                )
                SELECT si.stock_id,
                       COALESCE(si.name, si.stock_id) AS name,
                       si.market,
                       latest.close
                FROM stock_info si
                LEFT JOIN latest ON latest.stock_id = si.stock_id
                WHERE si.stock_id IN ({marks})
                """,
                symbols,
            ).fetchall()
    except Exception:
        rows = []

    profile_map: Dict[str, SymbolProfile] = {}
    for stock_id, name, market, close in rows:
        profile_map[str(stock_id)] = SymbolProfile(
            stock_id=str(stock_id),
            ticker=_build_ticker(str(stock_id), market),
            name=str(name),
            reference_close=float(close) if close is not None else None,
        )

    # Fall-back profile for any symbol missing from stock_info
    for symbol in symbols:
        if symbol not in profile_map:
            profile_map[symbol] = SymbolProfile(
                stock_id=symbol,
                ticker=_build_ticker(symbol, None),
                name=symbol,
                reference_close=None,
            )

    return profile_map


def get_symbol_profile(stock_id: str) -> dict | None:
    """Return metadata for a single stock (used by live-quote engine)."""
    sid = str(stock_id).strip()
    if not sid:
        return None
    profiles = _load_symbol_metadata([sid])
    profile = profiles.get(sid)
    return asdict(profile) if profile else None


def get_symbol_pool(top_n: int = 50) -> List[dict]:
    """
    Build the merged symbol pool:
      watchlist symbols first, then top-N by volume, de-duplicated.
    """
    watchlist_symbols = _load_watchlist_symbols()
    top_symbols = _load_top_n_symbols(top_n=top_n)

    merged: List[str] = []
    seen: set = set()
    for symbol in watchlist_symbols + top_symbols:
        if symbol not in seen:
            seen.add(symbol)
            merged.append(symbol)

    profiles = _load_symbol_metadata(merged)
    return [asdict(profiles[s]) for s in merged if s in profiles]
