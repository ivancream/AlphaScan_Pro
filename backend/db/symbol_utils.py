"""
symbol_utils.py — centralized symbol normalization.

Internal DB storage always uses PURE numeric IDs (e.g., '2330').
The .TW / .TWO suffix is only added at the yfinance API boundary.
"""

import re

_SUFFIX_RE = re.compile(r"\.(TW|TWO)$", re.IGNORECASE)


def strip_suffix(symbol: str) -> str:
    """
    '2330.TW'  → '2330'
    '6669.TWO' → '6669'
    '2330'     → '2330'
    """
    return _SUFFIX_RE.sub("", symbol.strip())


def to_yf_ticker(stock_id: str, market: str = "TSE") -> str:
    """
    '2330', 'TSE' → '2330.TW'
    '6669', 'OTC' → '6669.TWO'
    If market unknown, defaults to '.TW'.
    """
    pure = strip_suffix(stock_id)
    suffix = ".TWO" if market == "OTC" else ".TW"
    return f"{pure}{suffix}"


def to_yf_ticker_from_db(stock_id: str) -> str:
    """
    Look up market from DB and build the correct yfinance ticker.
    Falls back to '.TW' if not found.
    """
    from backend.db.queries import get_stock_market
    market = get_stock_market(strip_suffix(stock_id))
    return to_yf_ticker(stock_id, market)


def batch_to_yf(stock_ids: list[str], market_map: dict[str, str] | None = None) -> dict[str, str]:
    """
    Convert a list of pure stock_ids to {stock_id: yf_ticker} dict.
    market_map: optional {stock_id: 'TSE'|'OTC'} for offline use.
    """
    result = {}
    for sid in stock_ids:
        pure = strip_suffix(sid)
        market = (market_map or {}).get(pure, "TSE")
        result[pure] = to_yf_ticker(pure, market)
    return result
