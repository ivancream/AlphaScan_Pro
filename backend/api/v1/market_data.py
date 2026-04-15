from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import pandas as pd
import os
import numpy as np
from pathlib import Path
import datetime as dt
from zoneinfo import ZoneInfo

from backend.engines.engine_live_quotes import live_quote_engine

# 將路徑鎖定在專案根目錄的 data 資料夾
root_path = Path(__file__).parent.parent.parent.parent.absolute()
DB_FILE = root_path / "data" / "taiwan_stock.db"
# 選股／技術分析使用之股票主檔（名稱搜尋優先，資料較完整）
TECH_STOCK_DB = root_path / "databases" / "db_technical_prices.db"

router = APIRouter()

class CandleData(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    # 主圖指標
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    # 副圖指標
    k: Optional[float] = None
    d: Optional[float] = None
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    bias: Optional[float] = None
    obv: Optional[float] = None
    rs: Optional[float] = None
    rs_ma: Optional[float] = None

class MarketDataResponse(BaseModel):
    symbol: str
    data: List[CandleData]
    snapshot: Optional[dict] = None
    session: str = "after_hours"


def _is_market_hours() -> bool:
    now = dt.datetime.now(ZoneInfo("Asia/Taipei"))
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_close = now.replace(hour=13, minute=35, second=0, microsecond=0)
    return market_open <= now <= market_close


def _build_snapshot(clean_id: str, df: pd.DataFrame) -> tuple[str, Optional[dict]]:
    latest_quote = next(
        (item for item in live_quote_engine.get_latest_quotes() if item.get("stock_id") == clean_id),
        None,
    )

    last_row = df.iloc[-1] if not df.empty else None
    last_close = float(last_row["close"]) if last_row is not None else None
    last_volume = int(last_row["volume"]) if last_row is not None else None
    bb_upper = float(last_row["bb_upper"]) if last_row is not None and pd.notna(last_row.get("bb_upper")) else None
    bb_lower = float(last_row["bb_lower"]) if last_row is not None and pd.notna(last_row.get("bb_lower")) else None

    if latest_quote and _is_market_hours():
        last_price = float(latest_quote.get("last_price") or 0)
        session = "intraday"
        snapshot = {
            "last_price": round(last_price, 2),
            "change_pct": float(latest_quote.get("change_pct") or 0),
            "volume": int(latest_quote.get("volume") or 0),
            "vwap": round(last_price, 2),
            "provider": latest_quote.get("provider"),
            "ts": latest_quote.get("ts"),
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
        }
        return session, snapshot

    if last_row is None:
        return "after_hours", None

    prev_close = float(df.iloc[-2]["close"]) if len(df) > 1 else last_close
    change_pct = 0.0
    if prev_close and prev_close != 0:
        change_pct = round(((last_close - prev_close) / prev_close) * 100.0, 2)

    typical_price = np.mean([float(last_row["high"]), float(last_row["low"]), float(last_row["close"])])
    snapshot = {
        "last_price": round(last_close, 2) if last_close is not None else None,
        "change_pct": change_pct,
        "volume": last_volume,
        "vwap": round(float(typical_price), 2),
        "provider": "daily_price",
        "ts": str(last_row["time"]),
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
    }
    return "after_hours", snapshot

@router.get("/api/v1/market-data/{symbol}", response_model=MarketDataResponse)
async def get_market_data(symbol: str, limit: int = Query(5000, description="最大回傳筆數")):
    """
    獲取指定標地的歷史 K 線與全套專業指標數據
    """
    clean_id = symbol.split('.')[0].strip().upper()
    fetch_limit = limit + 120 # 多抓些歷史資料以計算 OBV, MA60 等
    
    query = f"""
        SELECT date as time, 
               open, high, low, close, volume 
        FROM daily_price 
        WHERE stock_id = ? 
        ORDER BY date ASC 
    """
    
    try:
        if not os.path.exists(str(DB_FILE)):
             return MarketDataResponse(symbol=symbol, data=[])

        with sqlite3.connect(str(DB_FILE)) as conn:
            df = pd.read_sql(query, conn, params=[clean_id])
            
            if df.empty:
                return MarketDataResponse(symbol=symbol, data=[])
            
            # --- 主圖指標 ---
            df['ma5'] = df['close'].rolling(window=5).mean()
            df['ma10'] = df['close'].rolling(window=10).mean()
            df['ma20'] = df['close'].rolling(window=20).mean()
            df['ma60'] = df['close'].rolling(window=60).mean()
            
            std20 = df['close'].rolling(window=20).std()
            df['bb_upper'] = df['ma20'] + (std20 * 2)
            df['bb_lower'] = df['ma20'] - (std20 * 2)
            
            # --- KD (9,3,3) ---
            low_9 = df['low'].rolling(window=9).min()
            high_9 = df['high'].rolling(window=9).max()
            rsv = ((df['close'] - low_9) / (high_9 - low_9)) * 100
            k_list, d_list = [], []
            curr_k, curr_d = 50.0, 50.0
            for val in rsv:
                if pd.isna(val):
                    k_list.append(None); d_list.append(None)
                else:
                    curr_k = (2/3) * curr_k + (1/3) * val
                    curr_d = (2/3) * curr_d + (1/3) * curr_k
                    k_list.append(curr_k); d_list.append(curr_d)
            df['k'], df['d'] = k_list, d_list

            # --- RSI (14) ---
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))

            # --- MACD (12,26,9) ---
            exp12 = df['close'].ewm(span=12, adjust=False).mean()
            exp26 = df['close'].ewm(span=26, adjust=False).mean()
            df['macd'] = exp12 - exp26
            df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
            df['macd_hist'] = df['macd'] - df['macd_signal']

            # --- Bias (20) ---
            df['bias'] = ((df['close'] - df['ma20']) / df['ma20']) * 100

            # --- OBV (能量潮) ---
            direction = np.where(df['close'].diff() > 0, 1, np.where(df['close'].diff() < 0, -1, 0))
            df['obv'] = (df['volume'] * direction).cumsum()
            
            # --- RS (Relative Strength) vs ^TWII ---
            try:
                import yfinance as yf
                # yf download uses index as datetime, let's convert df['time'] to datetime for alignment
                temp_time = pd.to_datetime(df['time'])
                idx_df = yf.download("^TWII", start=temp_time.iloc[0], end=temp_time.iloc[-1] + pd.Timedelta(days=1), progress=False)
                if isinstance(idx_df.columns, pd.MultiIndex):
                     idx_df.columns = idx_df.columns.get_level_values(0)
                
                # Align using reindex
                idx_close = idx_df['Close'].reindex(temp_time).ffill().values
                
                # Calculate ratio and normalize to 100 on the first day
                ratio = df['close'].values / idx_close
                # Find first non-nan ratio
                mask = ~np.isnan(ratio)
                if mask.any():
                    first_ratio = ratio[mask][0]
                    df['rs'] = (ratio / first_ratio) * 100
                    df['rs_ma'] = df['rs'].rolling(window=20).mean()
                else:
                    df['rs'] = None
                    df['rs_ma'] = None
            except Exception as e:
                print(f"RS API Error: {e}")
                df['rs'] = None
                df['rs_ma'] = None
            
            # 格式化輸出
            df['time'] = pd.to_datetime(df['time']).dt.strftime('%Y-%m-%d')
            df_final = df.tail(limit).copy()
            df_final = df_final.where(pd.notnull(df_final), None)
            session, snapshot = _build_snapshot(clean_id, df)
            
            data = df_final.to_dict(orient='records')
            return MarketDataResponse(symbol=symbol, data=data, snapshot=snapshot, session=session)
            
    except Exception as e:
        print(f"[!] market_data API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def _resolve_stock_id_from_dbs(stock_id: str) -> str | None:
    """若資料庫有該代號則回傳 stock_id，否則 None。"""
    for db_path in (TECH_STOCK_DB, DB_FILE):
        if not db_path.exists():
            continue
        try:
            with sqlite3.connect(str(db_path)) as conn:
                res = conn.execute(
                    "SELECT stock_id FROM stock_info WHERE stock_id = ? LIMIT 1",
                    [stock_id],
                ).fetchone()
                if res:
                    return str(res[0])
        except Exception:
            continue
    return None


def _resolve_name_from_dbs(name_query: str) -> str | None:
    """依名稱完整或模糊比對，回傳第一筆 stock_id。"""
    q = name_query.strip()
    if not q:
        return None
    for db_path in (TECH_STOCK_DB, DB_FILE):
        if not db_path.exists():
            continue
        try:
            with sqlite3.connect(str(db_path)) as conn:
                res = conn.execute(
                    "SELECT stock_id FROM stock_info WHERE name = ? LIMIT 1",
                    [q],
                ).fetchone()
                if res:
                    return str(res[0])
                res = conn.execute(
                    "SELECT stock_id FROM stock_info WHERE name LIKE ? ORDER BY LENGTH(name) ASC LIMIT 1",
                    [f"%{q}%"],
                ).fetchone()
                if res:
                    return str(res[0])
        except Exception:
            continue
    return None


@router.get("/api/v1/market-data/resolve/{query}")
async def resolve_symbol(query: str):
    """
    解析使用者輸入為可餵給前端的 symbol（例 2330.TW）。
    支援：代號、含 .TW/.TWO 後綴、以及 stock_info 內的中文名稱（完整或部分）。
    """
    raw = query.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="empty query")

    upper = raw.upper()
    if upper.endswith(".TW") or upper.endswith(".TWO"):
        return {"symbol": upper}

    # 純數字代號（上市櫃 4 碼、ETF 等 5 碼）
    if raw.isdigit() and len(raw) in (4, 5):
        sid = _resolve_stock_id_from_dbs(raw)
        if sid:
            return {"symbol": f"{sid}.TW"}
        return {"symbol": f"{raw}.TW"}

    # 中文或英文簡稱：先當名稱搜尋
    sid = _resolve_name_from_dbs(raw)
    if sid:
        return {"symbol": f"{sid}.TW"}

    # 最後嘗試把整段當代號（部分權證格式等）
    sid = _resolve_stock_id_from_dbs(raw.upper())
    if sid:
        return {"symbol": f"{sid}.TW"}

    raise HTTPException(
        status_code=404,
        detail=f"找不到與「{raw}」相符的股票，請改輸入正確代號或公司名稱關鍵字。",
    )
