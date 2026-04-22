from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any, List
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

router = APIRouter()

class ScanFloorBounceResponse(BaseModel):
    results: List[Dict[str, Any]]

from backend.db import queries as _db_queries
from backend.db.symbol_utils import strip_suffix as _strip_suffix


def fetch_stock_data(stock_code: str) -> pd.DataFrame:
    """從 DuckDB daily_prices 取得歷史 K 線數據。"""
    try:
        sid = _strip_suffix(str(stock_code).strip().upper())
        df = _db_queries.get_price_df(sid, period="max")
        if df.empty:
            return None
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        return df
    except Exception as exc:
        print(f"[FloorBounce] fetch error: {exc}")
        return None


def get_stock_name(stock_code: str) -> str:
    """查詢股票名稱。"""
    return _db_queries.get_stock_name(_strip_suffix(str(stock_code).strip()))

@router.get("/api/v1/floor-bounce/scan", response_model=ScanFloorBounceResponse)
async def scan_floor_bounce(
    show_mode: str = Query("all", description="all, ceiling, floor, signals"), 
    require_vol: bool = Query(True), 
    filter_inactive: bool = Query(True)
):
    """
    掃描全台股乖離率通道，找出靠近「統計地板」或「天花板」的股票
    """
    try:
        if filter_inactive:
            info_df = _db_queries.get_active_stocks()
        else:
            info_df = _db_queries.get_stock_info_df()
        stocks = info_df["stock_id"].tolist() if not info_df.empty else []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read stock list: {exc}")

    results = []

    sector_rows = _db_queries.get_stock_sector_rows()
    try:
        import twstock
        _tw_codes_fb = twstock.codes
    except Exception:
        _tw_codes_fb = {}

    mkt_by_sid: Dict[str, str] = {}
    if not info_df.empty and "market" in info_df.columns:
        for _, r in info_df.iterrows():
            mkt_by_sid[str(r["stock_id"]).strip()] = str(r.get("market") or "")

    # 限制掃描數量以避免 API time out (正式環境可用背景任務)
    for stock_id in stocks:
        df = fetch_stock_data(stock_id)
        if df is None or len(df) < 200:
            continue

        last_date = df.index[-1]
        days_old = (pd.Timestamp.now() - pd.Timestamp(last_date)).days
        if days_old > 40:  # 超過 40 天未更新才跳過
            continue

        df['MA20'] = df['close'].rolling(20).mean()
        df['Bias'] = (df['close'] - df['MA20']) / df['MA20']

        history_bias = df['Bias'].dropna()
        pos_bias = history_bias[history_bias > 0]
        neg_bias = history_bias[history_bias < 0]

        ceil_th = np.percentile(pos_bias, 95) if len(pos_bias) > 0 else 0.1
        floor_th = np.percentile(neg_bias, 5) if len(neg_bias) > 0 else -0.1

        last_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2] if len(df) > 1 else last_close
        daily_ret = (last_close - prev_close) / prev_close * 100 if prev_close else 0

        last_ma = df['MA20'].iloc[-1]
        last_bias = df['Bias'].iloc[-1]

        # 計算 20 日均量與今日量比
        vol_ma20 = df['volume'].rolling(20).mean().iloc[-1]
        last_vol = df['volume'].iloc[-1]
        vol_ratio = last_vol / vol_ma20 if vol_ma20 and pd.notna(vol_ma20) else 0

        floor_price = last_ma * (1 + floor_th)
        ceil_price = last_ma * (1 + ceil_th)

        status = "normal"
        if last_close <= floor_price:
            status = "floor"
        elif last_close >= ceil_price:
            status = "ceiling"
            
        # UI 濾網套用
        if show_mode == "ceiling" and status != "ceiling": continue
        if show_mode == "floor" and status != "floor": continue
        if show_mode == "signals" and status == "normal": continue
        
        if require_vol:
             if daily_ret < 0 and vol_ratio < 2.0: continue

        industry = _db_queries.resolve_industry_label(
            stock_id,
            sector_rows,
            _tw_codes_fb,
            market=mkt_by_sid.get(str(stock_id).strip()),
        )

        results.append({
            "id": stock_id,
            "name": get_stock_name(stock_id),
            "industry": industry,
            "close": round(last_close, 2),
            "daily_ret_pct": round(daily_ret, 2),
            "成交量(張)": int(last_vol / 1000),
            "成交額(億)": round((last_close * last_vol) / 1e8, 2),
            "bias_pct": round(last_bias * 100, 2),
            "floor_th_pct": round(floor_th * 100, 2),
            "ceil_th_pct": round(ceil_th * 100, 2),
            "vol_ratio": round(vol_ratio, 2),
            "status": status,
        })
        
    # 根據距離地板多遠預設反向排序，讓最嚴重的在最上面 (如果是地板模式)
    is_asc = (show_mode == "floor")
    results.sort(key=lambda x: x["bias_pct"], reverse=not is_asc)

    return {"results": results}

@router.get("/api/v1/floor-bounce/chart/{stock_code}")
async def get_floor_bounce_chart_data(stock_code: str):
    """取得特定股票繪製地板圖(Plotly)所需的資料序列"""
    try:
        df = fetch_stock_data(stock_code)
        if df is None or len(df) < 200:
            raise HTTPException(status_code=404, detail="Data insufficient")
            
        df['MA20'] = df['close'].rolling(20).mean()
        df['Bias'] = (df['close'] - df['MA20']) / df['MA20']
        history_bias = df['Bias'].dropna()
        pos_bias = history_bias[history_bias > 0]
        neg_bias = history_bias[history_bias < 0]
        ceil_th  = np.percentile(pos_bias, 95) if len(pos_bias) > 0 else 0.1
        floor_th = np.percentile(neg_bias, 5)  if len(neg_bias) > 0 else -0.1
        
        df['Floor']   = df['MA20'] * (1 + floor_th)
        df['Ceiling'] = df['MA20'] * (1 + ceil_th)
        
        # 只傳最後 600 筆給前端繪圖
        plot_df = df.tail(600).copy()
        
        # Format for lightweight charts or plotly (we use lightweight charts in UI normally, but need MA/Floor/Ceiling bands)
        data = []
        for index, row in plot_df.iterrows():
             data.append({
                 "time": index.strftime('%Y-%m-%d'),
                 "open": row["open"] if pd.notna(row["open"]) else 0,
                 "high": row["high"] if pd.notna(row["high"]) else 0,
                 "low": row["low"] if pd.notna(row["low"]) else 0,
                 "close": row["close"] if pd.notna(row["close"]) else 0,
                 "value": row["volume"] if pd.notna(row["volume"]) else 0, # for volume
                 "ma20": row.get("MA20", None),
                 "floor": row.get("Floor", None),
                 "ceiling": row.get("Ceiling", None),
             })
             
        # Clean nulls for JSON
        for item in data:
            if pd.isna(item['ma20']): item['ma20'] = None
            if pd.isna(item['floor']): item['floor'] = None
            if pd.isna(item['ceiling']): item['ceiling'] = None
             
        return {
            "symbol": stock_code,
            "name": get_stock_name(stock_code),
            "floor_th_pct": round(floor_th * 100, 2),
            "ceil_th_pct": round(ceil_th * 100, 2),
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
