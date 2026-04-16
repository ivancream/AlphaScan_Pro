"""
除權息分析 API — 改用 DuckDB 統一資料源。
"""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import pandas as pd

from backend.engines.cache_store import StaticCache, TTL_12H
from backend.db import queries
from backend.db.symbol_utils import strip_suffix

router = APIRouter()
_CACHE_CONTROL = f"public, max-age={TTL_12H}, stale-while-revalidate=600"


class DividendStatsResponse(BaseModel):
    summary: Dict[str, Dict[str, Any]]
    details: List[Dict[str, Any]]
    yearly: List[Dict[str, Any]]


def _get_price_df(stock_code: str) -> pd.DataFrame:
    """Fetch price history from DuckDB daily_prices."""
    sid = strip_suffix(stock_code)
    df = queries.get_price_df(sid, period="max")
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df


def _get_dividends(stock_code: str) -> pd.DataFrame:
    """Fetch dividend history from DuckDB dividends table."""
    sid = strip_suffix(stock_code)
    df = queries.get_dividends(sid)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def _backfill_dividends(stock_code: str) -> int:
    """Fetch dividends from yfinance and store in DuckDB."""
    import yfinance as yf
    from backend.db import writer
    from backend.db.symbol_utils import to_yf_ticker
    from backend.db.queries import get_stock_market

    sid = strip_suffix(stock_code)
    market = get_stock_market(sid)
    rows = []
    for suffix in ([".TWO"] if market == "OTC" else [".TW", ".TWO"]):
        try:
            t = yf.Ticker(f"{sid}{suffix}")
            divs = t.dividends
            if divs.empty:
                continue
            rows = [(sid, d.strftime("%Y-%m-%d"), float(v)) for d, v in divs.items()]
            break
        except Exception:
            continue
    return writer.upsert_dividends(rows)


def get_dividend_window(price_df: pd.DataFrame, div_date: pd.Timestamp, window: int = 3):
    idx = price_df.index.searchsorted(div_date)
    if idx >= len(price_df):
        return None
    found_date = price_df.index[idx]
    if abs((found_date - div_date).days) > 5:
        return None
    rows = {}
    for offset in range(-(window + 1), window + 1):
        pos = idx + offset
        rows[offset] = price_df.iloc[pos] if 0 <= pos < len(price_df) else None
    return rows


@router.get("/api/v1/dividend/{stock_code}/scan")
async def get_dividend_analysis(stock_code: str, response: Response):
    """取得個股歷年除權息前後漲跌行為統計分析。結果快取 12 小時。"""
    key = StaticCache.make_key("dividend:scan", stock_code=stock_code.upper())
    cached = StaticCache.get(key)
    if cached is not None:
        response.headers["Cache-Control"] = _CACHE_CONTROL
        response.headers["X-Cache"] = "HIT"
        return cached

    try:
        div_df = _get_dividends(stock_code)
        if div_df.empty:
            _backfill_dividends(stock_code)
            div_df = _get_dividends(stock_code)

        if div_df.empty:
            return {
                "summary": {}, "details": [], "yearly": [],
                "message": f"No dividend data found for {stock_code}",
            }

        cutoff = pd.Timestamp.now() - pd.DateOffset(years=10)
        div_df = div_df[div_df["date"] >= cutoff].reset_index(drop=True)

        price_df = _get_price_df(stock_code)
        if price_df.empty:
            raise HTTPException(status_code=404, detail="Stock price history not found")

        price_df.index = pd.to_datetime(price_df.index).normalize()

        records = []
        for _, row in div_df.iterrows():
            div_date = pd.Timestamp(row["date"]).normalize()
            cash_div = round(float(row["dividend"]), 2)

            window = get_dividend_window(price_df, div_date, window=3)
            if not window:
                continue
            day0 = window.get(0)
            if day0 is None:
                continue
            prev1 = window.get(-1)

            yield_pct = None
            if prev1 is not None and prev1["close"] > 0:
                yield_pct = cash_div / prev1["close"] * 100

            def calc_pct(c, p):
                return (c - p) / p * 100 if pd.notna(c) and pd.notna(p) and p else None

            open_gap = calc_pct(
                day0["open"] if day0 is not None else None,
                prev1["close"] if prev1 is not None else None,
            )
            intraday = calc_pct(
                day0["close"] if day0 is not None else None,
                day0["open"] if day0 is not None else None,
            )

            rec: Dict[str, Any] = {
                "date": div_date.strftime("%Y/%m/%d"),
                "dividend": cash_div,
                "yieldPct": round(yield_pct, 2) if yield_pct is not None else None,
            }
            for offset in range(-3, 4):
                curr = window.get(offset)
                prev = window.get(offset - 1)
                chg = calc_pct(
                    curr["close"] if curr is not None else None,
                    prev["close"] if prev is not None else None,
                )
                label = f"d{offset}" if offset < 0 else (
                    f"d_plus_{offset}" if offset > 0 else "d0"
                )
                rec[label] = round(chg, 2) if chg is not None else None

            rec["intraday"] = round(intraday, 2) if intraday is not None else None
            rec["openGap"] = round(open_gap, 2) if open_gap is not None else None
            records.append(rec)

        if not records:
            return {
                "summary": {}, "details": [], "yearly": [],
                "message": "Could not map dividend dates to market history",
            }

        detail_df = pd.DataFrame(records)

        cols_map = {
            "d-3": "3天前", "d-2": "2天前", "d-1": "1天前", "d0": "當日",
            "d_plus_1": "1天後", "d_plus_2": "2天後", "d_plus_3": "3天後",
            "intraday": "當日開_閉", "openGap": "開盤跳空",
        }
        summary_rows: Dict[str, Any] = {}
        for k, name in cols_map.items():
            if k not in detail_df.columns:
                continue
            vals = detail_df[k].dropna()
            if len(vals) == 0:
                summary_rows[name] = {"upProb": None, "upAvg": None, "dnAvg": None, "avg": None}
                continue
            up_vals = vals[vals > 0]
            dn_vals = vals[vals < 0]
            summary_rows[name] = {
                "upProb": round(len(up_vals) / len(vals) * 100, 1),
                "upAvg": round(up_vals.mean(), 2) if len(up_vals) > 0 else None,
                "dnAvg": round(dn_vals.mean(), 2) if len(dn_vals) > 0 else None,
                "avg": round(vals.mean(), 2),
            }

        detail_df["year"] = detail_df["date"].str[:4]
        yearly_df = (
            detail_df.groupby("year")
            .agg(totalDividend=("dividend", "sum"), avgYield=("yieldPct", "mean"))
            .reset_index()
            .sort_values("year", ascending=False)
        )
        yearly_df["totalDividend"] = yearly_df["totalDividend"].round(2)
        yearly_df["avgYield"] = yearly_df["avgYield"].round(2)

        result = {
            "summary": summary_rows,
            "details": records,
            "yearly": yearly_df.to_dict(orient="records"),
            "total_count": len(records),
        }
        StaticCache.set(key, result, ttl=TTL_12H)
        response.headers["Cache-Control"] = _CACHE_CONTROL
        response.headers["X-Cache"] = "MISS"
        return result

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/api/v1/dividend/cache")
async def clear_dividend_cache():
    n = StaticCache.invalidate_prefix("dividend:")
    return {"message": f"已清除 {n} 筆除權息快取"}


@router.get("/api/v1/dividend/search")
async def search_stock(q: str):
    """查詢股票名稱或代號"""
    try:
        sid = queries.resolve_stock_id(q.strip())
        if sid:
            name = queries.get_stock_name(sid)
            return [{"id": sid, "name": name}]
        # Fallback: search by prefix
        from backend.db.connection import duck_read
        with duck_read() as conn:
            rows = conn.execute(
                """
                SELECT stock_id, name FROM stock_info
                WHERE stock_id LIKE ? OR name LIKE ?
                LIMIT 20
                """,
                [f"%{q}%", f"%{q}%"],
            ).fetchall()
        return [{"id": r[0], "name": r[1]} for r in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
