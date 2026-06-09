"""
Symbol pool engine.

Builds the set of stock symbols that real-time engines should subscribe to:
  1. Everything on the user's watchlist (from SQLite user.db)
  2. Top-N by volume from the latest trading day (from DuckDB daily_prices)

Returns a list of SymbolProfile dicts ready for consumption by the live-quote
and all-around engines.
"""
from __future__ import annotations

import html
import re
import urllib.request
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Dict, List, Optional

from backend.db.connection import duck_read, user_db

TAIFEX_STOCK_LISTS_URL = "https://www.taifex.com.tw/cht/2/stockLists"

ALL_AROUND_MARKET_CAP_SYMBOLS: tuple[str, ...] = (
    "2330", "2454", "2308", "2317", "3711", "2383", "2303", "2881", "2327", "2382",
    "3037", "2882", "2345", "2891", "7769", "2408", "2412", "2360", "6669", "3017",
    "2885", "1303", "2344", "2887", "2368", "2357", "5274", "2886", "3443", "6223",
    "8046", "3231", "8299", "4958", "2884", "2059", "2301", "3653", "6505", "2603",
    "2880", "3008", "2890", "6274", "2883", "3045", "2395", "3665", "3481", "2892",
    "6488", "2376", "5347", "1301", "2609", "2002", "3529", "3324", "1326", "1101",
    "2356", "3131", "6187", "2615", "2801", "2421", "2834", "4966", "2474", "6472",
    "4919", "9904", "4938", "2379", "3034", "6415", "1402", "5871", "5876", "2912",
    "1216", "2618", "2610", "2409", "2809", "2812", "3702", "2347", "6510", "3044",
    "2377", "2353", "6239", "2449", "5483", "6147", "3035", "3661", "8069", "9910",
    "1504", "1513", "1519", "1605", "2006", "2105", "2201", "2207", "2324", "2352",
    "2354", "2355", "2371", "2393", "2439", "2455", "2458", "2492", "2606", "2633",
    "2707", "2845", "2851", "2888", "2897", "2903", "3023", "3406", "3454", "3532",
    "3596", "3704", "3706", "4147", "4739", "4904", "5269", "5388", "5880", "6116",
    "6205", "6269", "6409", "6414", "6531", "6719", "8454", "8936", "9921", "9945",
    "1102", "1227", "1304", "1305", "1314", "1434", "1476", "1477", "1704", "1717",
    "1722", "1723", "1802", "1907", "2014", "2027", "2106", "2313", "2328", "2362",
    "2385", "2404", "2481", "2542", "2548", "2617", "2838", "2855", "2915", "3026",
    "3042", "3105", "3189", "3264", "3545", "3583", "3673", "4174", "5471", "5534",
    "6005", "6176", "6213", "6271", "6446", "6533", "8039", "8215", "9914", "9933",
    "3680", "6182", "3376", "6206", "8021", "3211", "3016", "3588", "2485", "3013",
    "1795", "4162", "6462", "2314", "2401", "2436", "2457", "3022", "3030", "4977",
    "5285", "6243", "6412", "6416", "6541", "8044", "8050", "8150", "8261", "1104",
    "1308", "1309", "1312", "1440", "1444", "1455", "1708", "1710", "1712", "1718",
    "1720", "1725", "1904", "1909", "2010", "2020", "2031", "2103", "2108", "2204",
    "2206", "2323", "2340", "2349", "2380", "2388", "2426", "2459", "2484", "2489",
    "3004", "3005", "3027", "3029", "3033", "3055", "3257", "3305", "3311", "3450",
    "3504", "3533", "3563", "3617", "3624", "4532", "4934", "4952", "5425", "6115",
    "6153", "6202", "6251", "6278", "6422", "6435", "6451", "6552", "6579", "8016",
    "8028", "8070", "8081", "8112", "8163", "9907", "9917", "9925", "9938", "9942",
)

# Fallback covers the largest names in the fixed all-around universe. The
# official TAIFEX stockLists page is used first when reachable.
TAIFEX_STOCK_FUTURE_FALLBACK: Dict[str, str] = {
    "2330": "CD",
    "1101": "DF",
    "1102": "DY",
    "1216": "CD",
    "1301": "CA",
    "1303": "CB",
    "1326": "DG",
    "1402": "CM",
    "1504": "EM",
    "2002": "CF",
    "2059": "FG",
    "2301": "FQ",
    "2303": "CC",
    "2308": "FR",
    "2317": "DH",
    "2324": "CQ",
    "2344": "FZ",
    "2345": "OP",
    "2347": "GA",
    "2353": "DS",
    "2354": "GC",
    "2357": "DJ",
    "2376": "GH",
    "2377": "GI",
    "2379": "GJ",
    "2382": "DK",
    "2408": "CY",
    "2412": "DL",
    "2449": "GR",
    "2454": "DV",
    "2474": "GX",
    "2603": "CZ",
    "2609": "DA",
    "2610": "DB",
    "2618": "HS",
    "2801": "DC",
    "2884": "DN",
    "2885": "DO",
    "2890": "DE",
    "2892": "DP",
    "2915": "DW",
    "3008": "IJ",
    "3034": "IO",
    "3035": "IP",
    "3037": "IR",
    "3231": "DX",
    "3443": "JB",
    "3481": "DQ",
    "3653": "JM",
    "3673": "JN",
    "3702": "JP",
    "3711": "OZ",
    "4938": "JS",
    "5534": "JW",
    "6116": "OE",
    "6176": "KA",
    "6213": "KB",
    "6239": "KC",
    "6271": "KD",
    "6274": "OV",
    "6278": "KE",
    "6414": "OQ",
    "6488": "OW",
    "6510": "OX",
    "8039": "KI",
}


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


def _strip_tags(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_taifex_stock_future_map(page_html: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, flags=re.I | re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.I | re.S)
        if len(cells) < 4:
            continue

        values = [_strip_tags(cell) for cell in cells]
        product_code = values[0].strip().upper()
        stock_id = values[2].strip()
        stock_future_flag = values[4] if len(values) > 4 else "是股票期貨標的"
        if (
            re.fullmatch(r"[A-Z0-9]{2,4}", product_code)
            and re.fullmatch(r"\d{4,6}", stock_id)
            and "股票期貨" in " ".join(values)
            and ("是股票期貨標的" in stock_future_flag or "股票期貨" in stock_future_flag)
        ):
            out[stock_id] = product_code
    return out


@lru_cache(maxsize=1)
def load_taifex_stock_future_code_map() -> Dict[str, str]:
    """Load stock-id to TAIFEX stock-futures product-code mapping."""
    try:
        req = urllib.request.Request(
            TAIFEX_STOCK_LISTS_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        parsed = _parse_taifex_stock_future_map(body)
        if parsed:
            return parsed
    except Exception:
        pass
    return dict(TAIFEX_STOCK_FUTURE_FALLBACK)


def get_taifex_stock_future_codes_for_symbols(symbols: List[str]) -> Dict[str, str]:
    code_map = load_taifex_stock_future_code_map()
    out: Dict[str, str] = {}
    for raw in symbols:
        sid = str(raw or "").strip().upper().replace(".TW", "").replace(".TWO", "")
        code = code_map.get(sid)
        if sid and code:
            out[sid] = code
    return out


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


def _quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _find_column(conn, table_name: str, candidates: tuple[str, ...]) -> Optional[str]:
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'main'
          AND table_name = ?
        """,
        [table_name],
    ).fetchall()
    available = {str(row[0]).lower(): str(row[0]) for row in rows}
    for candidate in candidates:
        found = available.get(candidate.lower())
        if found:
            return found
    return None


def _load_top_market_value_symbols(top_n: int) -> List[str]:
    """
    Return stock_ids for the all-around tape universe.

    The all-around monitor uses the user-maintained market-cap universe above.
    Prefer an explicit market-cap column if the local DB has one. The current
    base schema does not, so fall back to latest traded value as a stable proxy
    until a true market-cap source is added.
    """
    if top_n <= 0:
        return []
    if ALL_AROUND_MARKET_CAP_SYMBOLS:
        return list(ALL_AROUND_MARKET_CAP_SYMBOLS[:top_n])
    try:
        with duck_read() as conn:
            cap_col = _find_column(
                conn,
                "stock_info",
                ("market_cap", "market_value", "capitalization", "mkt_cap"),
            )
            if cap_col:
                q_cap = _quote_ident(cap_col)
                rows = conn.execute(
                    f"""
                    SELECT stock_id
                    FROM stock_info
                    WHERE COALESCE(is_active, TRUE)
                      AND TRY_CAST({q_cap} AS DOUBLE) IS NOT NULL
                    ORDER BY TRY_CAST({q_cap} AS DOUBLE) DESC
                    LIMIT ?
                    """,
                    [top_n],
                ).fetchall()
                return [str(r[0]) for r in rows if r and r[0]]

            shares_col = _find_column(
                conn,
                "stock_info",
                ("shares_outstanding", "issued_shares", "shares"),
            )
            if shares_col:
                q_shares = _quote_ident(shares_col)
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
                    SELECT si.stock_id
                    FROM stock_info si
                    JOIN latest ON latest.stock_id = si.stock_id
                    WHERE COALESCE(si.is_active, TRUE)
                      AND latest.close > 0
                      AND TRY_CAST(si.{q_shares} AS DOUBLE) IS NOT NULL
                    ORDER BY latest.close * TRY_CAST(si.{q_shares} AS DOUBLE) DESC
                    LIMIT ?
                    """,
                    [top_n],
                ).fetchall()
                return [str(r[0]) for r in rows if r and r[0]]

            rows = conn.execute(
                """
                WITH latest AS (
                    SELECT stock_id, close, volume
                    FROM daily_prices
                    WHERE (stock_id, date) IN (
                        SELECT stock_id, MAX(date)
                        FROM daily_prices
                        GROUP BY stock_id
                    )
                )
                SELECT si.stock_id
                FROM stock_info si
                JOIN latest ON latest.stock_id = si.stock_id
                WHERE COALESCE(si.is_active, TRUE)
                  AND latest.close > 0
                  AND latest.volume > 0
                ORDER BY latest.close * latest.volume DESC
                LIMIT ?
                """,
                [top_n],
            ).fetchall()
        return [str(r[0]) for r in rows if r and r[0]]
    except Exception:
        return _load_top_n_symbols(top_n)


def load_related_warrant_codes(
    underlying_symbols: List[str],
    *,
    max_per_underlying: int = 80,
) -> List[str]:
    """Return warrant codes linked to the supplied underlying stock ids."""
    symbols = [str(s or "").strip().upper() for s in underlying_symbols]
    symbols = [s for s in dict.fromkeys(symbols) if s]
    if not symbols or max_per_underlying <= 0:
        return []

    out: List[str] = []
    try:
        with duck_read() as conn:
            for sid in symbols:
                rows = conn.execute(
                    """
                    SELECT warrant_code
                    FROM warrant_master
                    WHERE trim(cast(underlying_symbol AS VARCHAR)) = ?
                    ORDER BY expiry_date ASC, warrant_code ASC
                    LIMIT ?
                    """,
                    [sid, max_per_underlying],
                ).fetchall()
                out.extend(str(r[0]).strip().upper() for r in rows if r and r[0])
    except Exception:
        return []

    return [code for code in dict.fromkeys(out) if code]


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


def get_all_around_symbol_pool(top_n: int = 300) -> List[dict]:
    """Return the stock universe for the all-around tape."""
    symbols = _load_top_market_value_symbols(top_n=top_n)
    profiles = _load_symbol_metadata(symbols)
    return [asdict(profiles[s]) for s in symbols if s in profiles]


def get_all_around_subscription_symbols(
    top_n: int = 300,
    *,
    max_warrants_per_stock: int = 80,
) -> List[str]:
    """Return stock-side subscription symbols: top underlyings plus warrants."""
    underlyings = _load_top_market_value_symbols(top_n=top_n)
    warrants = load_related_warrant_codes(
        underlyings,
        max_per_underlying=max_warrants_per_stock,
    )
    return [s for s in dict.fromkeys([*underlyings, *warrants]) if s]
