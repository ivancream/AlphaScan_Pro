"""
自選股 API — reads/writes from data/user.db (SQLite) for watchlist,
and enriches with latest price data from DuckDB daily_prices.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime

from backend.db import queries
from backend.db.user_db import get_watchlist, add_to_watchlist, remove_from_watchlist
from backend.engines.engine_symbol_pool import get_symbol_pool

router = APIRouter()


class WatchlistAddRequest(BaseModel):
    stock_id: str


@router.get("/api/v1/watchlist")
async def get_watchlist_api():
    """取得自選股清單與最新行情"""
    stock_ids = get_watchlist()
    if not stock_ids:
        return []

    # Batch-fetch latest prices from DuckDB
    from backend.db.connection import duck_read
    import pandas as pd

    placeholders = ", ".join(["?"] * len(stock_ids))
    try:
        with duck_read() as conn:
            price_df = conn.execute(
                f"""
                WITH latest AS (
                    SELECT stock_id, date, close, volume,
                           LAG(close) OVER (PARTITION BY stock_id ORDER BY date ASC) AS prev_close
                    FROM daily_prices
                    WHERE stock_id IN ({placeholders})
                )
                SELECT stock_id, date::VARCHAR AS date, close, volume, prev_close
                FROM latest
                WHERE date = (SELECT MAX(date) FROM daily_prices WHERE stock_id = latest.stock_id)
                """,
                stock_ids,
            ).df()
    except Exception as exc:
        print(f"[Watchlist] price fetch error: {exc}")
        price_df = pd.DataFrame()

    price_map: dict = {}
    for _, row in price_df.iterrows():
        price_map[row["stock_id"]] = row

    sector_rows = queries.get_stock_sector_rows()
    try:
        import twstock
        tw_codes = twstock.codes
    except Exception:
        tw_codes = {}

    info = queries.get_stock_info_df()
    results = []
    for sid in stock_ids:
        name_row = info[info["stock_id"] == sid] if not info.empty else None
        name = name_row.iloc[0]["name"] if name_row is not None and not name_row.empty else sid
        market = name_row.iloc[0]["market"] if name_row is not None and not name_row.empty else "TSE"

        p = price_map.get(sid)
        close = float(p["close"]) if p is not None and p["close"] else 0
        volume = float(p["volume"]) if p is not None and p["volume"] else 0
        prev_close = float(p["prev_close"]) if p is not None and p["prev_close"] else close
        data_date = str(p["date"]) if p is not None else ""

        change_pct = 0.0
        if prev_close and prev_close != 0:
            change_pct = round(((close - prev_close) / prev_close) * 100, 2)

        suffix = ".TWO" if market == "OTC" else ".TW"
        industry = queries.resolve_industry_label(
            sid,
            sector_rows,
            tw_codes,
            market=market,
            use_yfinance=True,
        )

        results.append({
            "代號": sid,
            "名稱": name,
            "產業": industry,
            "收盤價": round(close, 2),
            "今日漲跌幅(%)": change_pct,
            "成交量(張)": int(volume / 1000),
            "成交額(億)": round((close * volume) / 1e8, 2),
            "資料日期": data_date,
            "_ticker": f"{sid}{suffix}",
            "added_at": "",
        })

    return results


@router.post("/api/v1/watchlist")
async def add_to_watchlist_api(req: WatchlistAddRequest):
    add_to_watchlist(req.stock_id)
    return {"message": f"{req.stock_id} 已加入自選股"}


@router.delete("/api/v1/watchlist/{stock_id}")
async def remove_from_watchlist_api(stock_id: str):
    remove_from_watchlist(stock_id)
    return {"message": f"{stock_id} 已從自選股移除"}


@router.get("/api/v1/watchlist/symbol-pool")
async def get_watchlist_symbol_pool(top_n: int = 50):
    return {
        "top_n": top_n,
        "symbols": get_symbol_pool(top_n=top_n),
    }
