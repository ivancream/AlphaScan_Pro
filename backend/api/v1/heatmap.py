# backend/api/v1/heatmap.py
"""
資金流向熱力圖 API

端點：
- GET  /api/v1/heatmap/data     — 取得熱力圖數據 (含三層產業分類 + 漲跌幅/成交金額)
"""

from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.engines import engine_heatmap

router = APIRouter()

# ==========================================
# Response Models
# ==========================================
class HeatmapStock(BaseModel):
    ticker: str
    name: str
    macro: str
    meso: str
    micro: str
    close: float
    change_pct: Optional[float] = None  # 資料異常時為 None，不列入板塊加權
    turnover: int
    volume: int

class HeatmapDataResponse(BaseModel):
    date: Optional[str]
    stocks: List[Dict[str, Any]]
    message: Optional[str] = None
    as_of_date: Optional[str] = None
    data_freshness: Optional[str] = None
    # duckdb_daily_prices；盤中由排程批次寫入，非本端點即時打 yfinance/Shioaji
    price_source: Optional[str] = None
    ingest_path: Optional[str] = None

# ==========================================
# Endpoints
# ==========================================
@router.get("/api/v1/heatmap/data", response_model=HeatmapDataResponse)
async def get_heatmap_data():
    """
    取得資金流向數據（全市場漲跌幅、成交金額、三層產業標籤）。
    價量僅讀 DuckDB daily_prices（由排程批次 snapshots／yf batch 寫入）；不經 LiveQuote 快取。
    """
    try:
        data = engine_heatmap.get_heatmap_data()
        return data
    except Exception as e:
        print(f"[Heatmap API] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
