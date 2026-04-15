# backend/api/v1/heatmap.py
"""
資金流向熱力圖 API

端點：
- GET  /api/v1/heatmap/data     — 取得熱力圖數據 (含三層產業分類 + 漲跌幅/成交金額)
"""

import os
import sys
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engines import engine_heatmap

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
    change_pct: float
    turnover: int
    volume: int

class HeatmapDataResponse(BaseModel):
    date: Optional[str]
    stocks: List[Dict[str, Any]]
    message: Optional[str] = None

# ==========================================
# Endpoints
# ==========================================
@router.get("/api/v1/heatmap/data", response_model=HeatmapDataResponse)
async def get_heatmap_data():
    """
    取得熱力圖數據。
    回傳即時分類好的股票最新日漲跌幅、成交金額等，供前端 Treemap 渲染。
    """
    try:
        data = engine_heatmap.get_heatmap_data()
        return data
    except Exception as e:
        print(f"[Heatmap API] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
