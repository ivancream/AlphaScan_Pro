import sqlite3
from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime
from backend.engines.engine_symbol_pool import get_symbol_pool

router = APIRouter()

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.absolute()
DB_PATH = PROJECT_ROOT / "databases" / "db_technical_prices.db"

class WatchlistAddRequest(BaseModel):
    stock_id: str

@router.get("/api/v1/watchlist")
async def get_watchlist():
    """取得自選股清單與其最新行情狀態"""
    if not DB_PATH.exists():
        return []
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # 取出自選股，並透過 subquery 拿到最新的收盤價與漲跌幅
    query = """
    WITH latest_prices AS (
        SELECT stock_id, date, close, volume,
               LAG(close) OVER (PARTITION BY stock_id ORDER BY date ASC) as prev_close
        FROM daily_price
    ),
    current_prices AS (
        SELECT stock_id, close, volume, prev_close, date
        FROM latest_prices
        GROUP BY stock_id
        HAVING date = MAX(date)
    )
    SELECT 
        w.stock_id as "代號",
        s.name as "名稱",
        p.close as "收盤價",
        ROUND(((p.close - p.prev_close) / p.prev_close) * 100, 2) as "今日漲跌幅(%)",
        p.volume as "成交量",
        p.date as "資料日期",
        w.added_at
    FROM watchlist w
    LEFT JOIN stock_info s ON w.stock_id = s.stock_id
    LEFT JOIN current_prices p ON w.stock_id = p.stock_id
    ORDER BY w.added_at DESC
    """
    
    rows = conn.execute(query).fetchall()
    conn.close()
    
    # 預先取得 twstock.codes 以優化效能
    try:
        import twstock
        tw_codes = twstock.codes
    except:
        tw_codes = {}

    results = []
    for r in rows:
        d = dict(r)
        stock_id = d['代號']
        d["_ticker"] = f"{stock_id}.TW" # 預設，後續可改良為區分上櫃
        
        # 取得產業分類
        d["產業"] = getattr(tw_codes.get(stock_id), "group", "其他") if tw_codes.get(stock_id) else "其他"
        
        # 計算量能相關欄位
        vol = d.get("成交量", 0) or 0
        close = d.get("收盤價", 0) or 0
        d["成交量(張)"] = int(vol / 1000)
        d["成交額(億)"] = round((close * vol) / 1e8, 2)
        
        # Fix missing prev_close edge cases
        if d["今日漲跌幅(%)"] is None:
            d["今日漲跌幅(%)"] = 0
            
        results.append(d)
        
    return results

@router.post("/api/v1/watchlist")
async def add_to_watchlist(req: WatchlistAddRequest):
    """加入自選股"""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (stock_id, added_at) VALUES (?, ?)", 
            (req.stock_id, datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()
    return {"message": f"{req.stock_id} 已加入自選股"}

@router.delete("/api/v1/watchlist/{stock_id}")
async def remove_from_watchlist(stock_id: str):
    """移除自選股"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM watchlist WHERE stock_id = ?", (stock_id,))
    conn.commit()
    conn.close()
    return {"message": f"{stock_id} 已從自選股移除"}


@router.get("/api/v1/watchlist/symbol-pool")
async def get_watchlist_symbol_pool(top_n: int = 50):
    """
    回傳第一階段即時報價訂閱池:
    - 自選股 watchlist
    - 加上成交量 Top N
    """
    return {
        "top_n": top_n,
        "symbols": get_symbol_pool(top_n=top_n),
    }
