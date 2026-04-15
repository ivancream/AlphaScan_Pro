import asyncio
from functools import partial

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any, List

# 共用 technical engine 裡的篩選邏輯
from engines import engine_technical

router = APIRouter()

class ScanTargetResponse(BaseModel):
    results: List[Dict[str, Any]]
    
@router.get("/api/v1/swing/long", response_model=ScanTargetResponse)
async def scan_swing_long(
    req_ma: bool = Query(True),
    req_vol: bool = Query(True),
    req_slope: bool = Query(True)
):
    """
    執行海選: 多方策略 (均線多排 + 猛虎出閘 + 爆量表態)
    """
    try:
        loop = asyncio.get_event_loop()
        fn = partial(
            engine_technical.BollingerStrategy.screen_from_db,
            strategy="long",
            req_ma=req_ma,
            req_vol=req_vol,
            req_slope=req_slope,
        )
        results, _ = await loop.run_in_executor(None, fn)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/v1/swing/short", response_model=ScanTargetResponse)
async def scan_swing_short(
    req_ma: bool = Query(True),
    req_slope: bool = Query(True),
    req_chips: bool = Query(True),
    req_near_band: bool = Query(True)
):
    """
    執行海選: 空方策略 (均線空排 + 籌碼渙散 + 沿下軌)
    """
    try:
        loop = asyncio.get_event_loop()
        fn = partial(
            engine_technical.BollingerStrategy.screen_from_db,
            strategy="short",
            req_ma=req_ma,
            req_slope=req_slope,
            req_chips=req_chips,
            req_near_band=req_near_band,
        )
        results, _ = await loop.run_in_executor(None, fn)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/v1/swing/wanderer", response_model=ScanTargetResponse)
async def scan_swing_wanderer(
    req_slope: bool = Query(True),
    req_bb_level: bool = Query(True)
):
    """
    執行海選: 浪子回頭策略 (月線斜率 > 0.8% + 布林位階 < 4)
    """
    try:
        loop = asyncio.get_event_loop()
        fn = partial(
            engine_technical.BollingerStrategy.screen_wanderer_from_db,
            req_slope=req_slope,
            req_bb_level=req_bb_level,
        )
        results, _ = await loop.run_in_executor(None, fn)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
