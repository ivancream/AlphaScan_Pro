"""
處置股分析 API (v2)
====================
- GET  /api/v1/disposition/current    → 即時處置清單 (TWSE + TPEx)
- GET  /api/v1/disposition/search/{stock_id} → 搜尋個股歷史處置紀錄 + 自動分析
- POST /api/v1/disposition/add-event  → 手動新增處置事件
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import date
from backend.engines.engine_disposition import (
    search_and_analyze,
    fetch_current_dispositions_and_save,
    save_events_to_db,
)

router = APIRouter(prefix="/api/v1/disposition")


# ── 即時處置清單 ──
@router.get("/current")
async def get_current_disposition():
    """
    抓取 TWSE + TPEx 的「當前處置中」個股名單，
    同時自動存入 DB 累積歷史紀錄。
    """
    try:
        items = fetch_current_dispositions_and_save()
        
        # 批量獲取最新行情（從 DuckDB daily_prices 表）
        codes = [it.get("stock_id", "") for it in items if it.get("stock_id")]
        price_map = {}
        
        if codes:
            try:
                from backend.db.connection import duck_read
                with duck_read() as conn:
                    marks = ",".join(["?" for _ in codes])
                    rows = conn.execute(
                        f"""
                        SELECT dp.stock_id, dp.close, dp.volume
                        FROM daily_prices dp
                        INNER JOIN (
                            SELECT stock_id, MAX(date) AS max_date
                            FROM daily_prices
                            WHERE stock_id IN ({marks})
                            GROUP BY stock_id
                        ) latest ON dp.stock_id = latest.stock_id AND dp.date = latest.max_date
                        """,
                        codes,
                    ).fetchall()
                for sid, close, volume in rows:
                    price_map[sid] = {"close": close, "volume": volume}
            except Exception as e:
                print(f"[API] Error fetching prices for disposition list: {e}")

        # 格式化回傳
        formatted = []
        for item in items:
            sid = item.get("stock_id", "")
            pinfo = price_map.get(sid, {})
            v = pinfo.get('volume', 0)
            c = pinfo.get('close', 0)
            
            formatted.append({
                "market": item.get("market", ""),
                "code": sid,
                "name": item.get("stock_name", ""),
                "start": item.get("disp_start", ""),
                "end": item.get("disp_end", ""),
                "mins": item.get("mins", "未知"),
                "成交量(張)": int(v / 1000) if v else 0,
                "成交額(億)": round((c * v) / 1e8, 2) if (c and v) else 0
            })
        
        return {"status": "success", "data": formatted}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ── 搜尋 + 自動分析 ──
@router.get("/search/{stock_id}")
async def search_stock_disposition(stock_id: str):
    """
    搜尋特定個股的歷史處置紀錄，自動分析處置前後漲跌幅。
    - 自動從交易所 API 更新最新處置清單到 DB
    - 從 DB 取出該股所有歷史處置事件
    - 計算每個事件的進關前N天 ~ 出關後N天漲跌幅
    """
    try:
        result = search_and_analyze(stock_id)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 手動新增事件 ──
class ManualEventRequest(BaseModel):
    stock_id: str
    disp_start: str  # YYYY-MM-DD
    disp_end: str    # YYYY-MM-DD

@router.post("/add-event")
async def add_manual_event(req: ManualEventRequest):
    """手動新增一筆處置事件 (用於 API 漏抓的歷史紀錄)"""
    try:
        save_events_to_db([{
            "stock_id": req.stock_id,
            "stock_name": "",
            "disp_start": req.disp_start,
            "disp_end": req.disp_end,
            "market": "",
            "source": "manual",
        }])
        
        # 新增後立即重新分析
        result = search_and_analyze(req.stock_id)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
