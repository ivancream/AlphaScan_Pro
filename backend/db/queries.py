"""
Centralized read queries for AlphaScan Pro.
All SQL lives here — no ad-hoc query strings scattered in engines/APIs.
"""
from __future__ import annotations

import math
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


def get_stock_names(symbol_list: List[str]) -> Dict[str, str]:
    """Batch look up stock names. Missing symbols fallback to symbol itself."""
    out: Dict[str, str] = {}
    if not symbol_list:
        return out
    uniq = list(dict.fromkeys([str(s).strip() for s in symbol_list if str(s).strip()]))
    placeholders = ", ".join(["?"] * len(uniq))
    try:
        with duck_read() as conn:
            rows = conn.execute(
                f"SELECT stock_id, name FROM stock_info WHERE stock_id IN ({placeholders})",
                uniq,
            ).fetchall()
        out = {str(r[0]): str(r[1]) for r in rows if r and r[0]}
    except Exception:
        out = {}
    for sid in uniq:
        if sid not in out:
            out[sid] = sid
    return out


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


def get_stock_sector_rows() -> Dict[str, Dict[str, Any]]:
    """
    證交所 stock_sectors 全欄：代號 -> {macro, meso, industry_raw}。
    與資金流向熱力圖板塊來源相同；解析規則見 backend.engines.sector_labels。
    """
    out: Dict[str, Dict[str, Any]] = {}
    try:
        with duck_read() as conn:
            rows = conn.execute(
                "SELECT stock_id, macro, meso, industry_raw FROM stock_sectors"
            ).fetchall()
        for r in rows:
            sid = str(r[0]).strip() if r[0] is not None else ""
            if not sid:
                continue
            out[sid] = {
                "macro": r[1],
                "meso": r[2],
                "industry_raw": r[3],
            }
    except Exception:
        return {}
    return out


def resolve_industry_label(
    stock_id: Any,
    sector_rows: Dict[str, Dict[str, Any]],
    tw_codes: Any,
    *,
    market: Optional[str] = None,
    use_yfinance: bool = False,
) -> str:
    """選股／自選「產業」：與熱力圖板塊一致；macro 為「其他」時改走 twstock／yfinance。"""
    from backend.engines.sector_labels import resolve_industry_for_ui

    return resolve_industry_for_ui(
        stock_id,
        sector_rows,
        tw_codes,
        market=market,
        use_yfinance=use_yfinance,
    )


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


def get_volume_history_for_stocks(stock_ids: List[str], days: int = 60) -> pd.DataFrame:
    """
    批次讀取多檔股票的日成交量（股數），依日期升序。
    用於舊掃描列補算 5MA／20MA 量比。
    """
    if not stock_ids:
        return pd.DataFrame()
    seen: set[str] = set()
    unique: List[str] = []
    for raw in stock_ids:
        sid = str(raw).strip()
        if sid and sid not in seen:
            seen.add(sid)
            unique.append(sid)
    if not unique:
        return pd.DataFrame()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    placeholders = ", ".join(["?"] * len(unique))
    with duck_read() as conn:
        return conn.execute(
            f"""
            SELECT stock_id, date, volume
            FROM daily_prices
            WHERE stock_id IN ({placeholders})
              AND date >= ?
              AND volume IS NOT NULL
            ORDER BY stock_id, date ASC
            """,
            unique + [cutoff],
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
            SELECT peer_id, correlation, adf_p_value, eg_p_value, half_life,
                   ratio_mean, ratio_std, zero_crossings, hedge_ratio, composite_score, calc_date::VARCHAR
            FROM correlations
            WHERE stock_id = ?
            ORDER BY composite_score DESC NULLS LAST, correlation DESC
            LIMIT ?
            """,
            [stock_id, top_n],
        ).fetchall()
    return [
        {
            "peer_id": r[0],
            "correlation": r[1],
            "adf_p_value": r[2],
            "eg_p_value": r[3],
            "half_life": r[4],
            "ratio_mean": r[5],
            "ratio_std": r[6],
            "zero_crossings": r[7],
            "hedge_ratio": r[8],
            "composite_score": r[9],
            "calc_date": r[10],
        }
        for r in rows
    ]


def get_pearson_peers_live(
    stock_id: str,
    top_n: int = 10,
    *,
    min_overlap: int = 60,
    calendar_days: int = 320,
) -> List[Dict]:
    """
    即時以「對數報酬」計算與全體股票的 Pearson 相關（僅需 daily_prices），
    用於 correlations 表尚無該主股（未過 ADF/EG 或未進建置宇宙）時的備援。

    與 build_correlations 的嚴格雙刀篩選無關；回傳列欄位形狀與 get_top_correlations 相容，
    未適用之量化欄位為 NULL／0。
    """
    sid = str(stock_id).strip().upper()
    if not sid:
        return []
    cd = int(max(120, min(calendar_days, 800)))
    mo = int(max(20, min(min_overlap, 250)))
    tn = int(max(1, min(top_n, 100)))
    start_d = (date.today() - timedelta(days=cd)).isoformat()
    try:
        with duck_read() as conn:
            raw = conn.execute(
                f"""
                WITH rets AS (
                    SELECT
                        stock_id,
                        date,
                        LN(close / NULLIF(
                            LAG(close) OVER (PARTITION BY stock_id ORDER BY date ASC),
                            0
                        )) AS r
                    FROM daily_prices
                    WHERE date >= ?::DATE
                ),
                base AS (
                    SELECT date, r
                    FROM rets
                    WHERE stock_id = ? AND r IS NOT NULL
                )
                SELECT
                    o.stock_id AS peer_id,
                    corr(b.r, o.r) AS correlation,
                    COUNT(*)::BIGINT AS n_obs
                FROM base AS b
                INNER JOIN rets AS o
                    ON o.date = b.date
                    AND o.stock_id <> ?
                    AND o.r IS NOT NULL
                GROUP BY o.stock_id
                HAVING COUNT(*) >= {mo}
                ORDER BY correlation DESC NULLS LAST
                LIMIT {tn}
                """,
                [start_d, sid, sid],
            ).fetchall()
    except Exception:
        return []

    out: List[Dict] = []
    for r in raw:
        try:
            c = float(r[1])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(c):
            continue
        out.append(
            {
                "peer_id": str(r[0]).strip(),
                "correlation": c,
                "adf_p_value": None,
                "eg_p_value": None,
                "half_life": None,
                "ratio_mean": None,
                "ratio_std": None,
                "zero_crossings": 0,
                "hedge_ratio": None,
                "composite_score": None,
                "calc_date": None,
            }
        )
    return out


def get_correlation_pair(stock_a: str, stock_b: str) -> Optional[Dict[str, Any]]:
    """
    Return a single correlation pair record.
    Tries (stock_a, stock_b) first, then reverse direction for usability.
    """
    with duck_read() as conn:
        row = conn.execute(
            """
            SELECT stock_id, peer_id, correlation, adf_p_value, eg_p_value,
                   half_life, ratio_mean, ratio_std, zero_crossings,
                   hedge_ratio, composite_score, calc_date::VARCHAR
            FROM correlations
            WHERE stock_id = ? AND peer_id = ?
            LIMIT 1
            """,
            [stock_a, stock_b],
        ).fetchone()
        if row is None:
            row = conn.execute(
                """
                SELECT stock_id, peer_id, correlation, adf_p_value, eg_p_value,
                       half_life, ratio_mean, ratio_std, zero_crossings,
                       hedge_ratio, composite_score, calc_date::VARCHAR
                FROM correlations
                WHERE stock_id = ? AND peer_id = ?
                LIMIT 1
                """,
                [stock_b, stock_a],
            ).fetchone()
    if row is None:
        return None
    return {
        "stock_id": row[0],
        "peer_id": row[1],
        "correlation": row[2],
        "adf_p_value": row[3],
        "eg_p_value": row[4],
        "half_life": row[5],
        "ratio_mean": row[6],
        "ratio_std": row[7],
        "zero_crossings": row[8],
        "hedge_ratio": row[9],
        "composite_score": row[10],
        "calc_date": row[11],
    }


def get_sector_theme_map(stock_ids: List[str]) -> Dict[str, Dict[str, Optional[str]]]:
    """
    Batch fetch sector/theme labels for stock_ids.
    Returns {stock_id: {"meso": str|None, "micro": str|None}}
    """
    if not stock_ids:
        return {}
    placeholders = ", ".join(["?"] * len(stock_ids))
    with duck_read() as conn:
        rows = conn.execute(
            f"""
            SELECT stock_id, meso, micro
            FROM stock_sectors
            WHERE stock_id IN ({placeholders})
            """,
            stock_ids,
        ).fetchall()
    return {
        str(r[0]): {"meso": r[1], "micro": r[2]}
        for r in rows
    }


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
# warrant_master
# ──────────────────────────────────────────────────────────────────────────────

def list_warrant_master_by_underlying(underlying_symbol: str) -> List[Dict[str, Any]]:
    """
    以標的代號（純數字，如 2330）查詢權證主檔列。
    若表不存在或查詢失敗，回傳空陣列。
    """
    sid = (underlying_symbol or "").strip()
    if not sid:
        return []
    cols = (
        "warrant_code",
        "warrant_name",
        "underlying_symbol",
        "underlying_name",
        "cp",
        "strike",
        "exercise_ratio",
        "expiry_date",
        "board",
    )
    try:
        with duck_read() as conn:
            rows = conn.execute(
                f"""
                SELECT {", ".join(cols)}
                FROM warrant_master
                WHERE trim(cast(underlying_symbol AS VARCHAR)) = ?
                ORDER BY warrant_code
                """,
                [sid],
            ).fetchall()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not r or not r[0]:
            continue
        out.append(dict(zip(cols, r)))
    return out


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
