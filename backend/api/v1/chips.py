import os
import io
import json
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import google.generativeai as genai
from PIL import Image

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engines import engine_chips

import duckdb
from pathlib import Path

router = APIRouter()

def save_warrant_data(data: List[Dict[str, Any]], manual_date: Optional[str] = None):
    """
    將提取的數據存入 DuckDB
    """
    root_path = Path(__file__).parent.parent.parent.absolute()
    db_path = root_path / 'data' / 'market.duckdb'
    
    with duckdb.connect(str(db_path)) as conn:
        for item in data:
            # 如果手動指定了日期，則優先使用手動日期
            target_date = manual_date if manual_date else item.get('date')
            
            conn.execute("""
                INSERT INTO warrant_branch_positions (snapshot_date, stock_id, stock_name, branch_name, amount_k, est_pnl, type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (snapshot_date, stock_id, branch_name, type) DO UPDATE SET
                    amount_k = excluded.amount_k,
                    est_pnl = excluded.est_pnl,
                    stock_name = excluded.stock_name
            """, [
                target_date, 
                item.get('stock_symbol'), 
                item.get('stock_name'), 
                item.get('broker'), 
                item.get('amount_k'), 
                item.get('estimated_pnl', 0),
                item.get('type', '認購')
            ])

@router.post("/api/v1/chips/ingest")
async def ingest_warrants_endpoint(
    files: List[UploadFile] = File(...),
    target_date: Optional[str] = Form(None)
):
    """
    掃描截圖並將數據存入資料庫，支援手動指定日期
    """
    images = []
    for file in files:
        content = await file.read()
        images.append(Image.open(io.BytesIO(content)))
    
    # 調用結構化提取
    extracted_data = engine_chips.extract_warrant_data_from_image(images)
    
    if extracted_data:
        save_warrant_data(extracted_data, manual_date=target_date)
        return {"status": "success", "count": len(extracted_data), "data": extracted_data}
    else:
        raise HTTPException(status_code=400, detail="未能從圖片中提取到有效數據")

def save_branch_trading_data(data: List[Dict[str, Any]], manual_date: Optional[str] = None):
    root_path = Path(__file__).parent.parent.parent.absolute()
    db_path = root_path / 'data' / 'market.duckdb'
    
    with duckdb.connect(str(db_path)) as conn:
        for item in data:
            target_date = manual_date if manual_date else item.get('date')
            conn.execute("""
                INSERT INTO branch_trading (snapshot_date, stock_id, stock_name, branch_name, buy_vol, sell_vol, net_vol, avg_buy_price, avg_sell_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (snapshot_date, stock_id, branch_name) DO UPDATE SET
                    buy_vol = excluded.buy_vol,
                    sell_vol = excluded.sell_vol,
                    net_vol = excluded.net_vol,
                    avg_buy_price = excluded.avg_buy_price,
                    avg_sell_price = excluded.avg_sell_price,
                    stock_name = excluded.stock_name
            """, [
                target_date,
                item.get('stock_symbol'),
                item.get('stock_name'),
                item.get('broker'),
                item.get('buy_vol'),
                item.get('sell_vol'),
                item.get('net_vol'),
                item.get('avg_buy_price'),
                item.get('avg_sell_price')
            ])

@router.post("/api/v1/chips/branch-trading/ingest")
async def ingest_branch_trading_endpoint(
    files: List[UploadFile] = File(...),
    target_date: Optional[str] = Form(None)
):
    """
    掃描截圖並將分點買賣超數據存入資料庫
    """
    images = []
    for file in files:
        content = await file.read()
        images.append(Image.open(io.BytesIO(content)))
    
    extracted_data = engine_chips.extract_branch_trading_from_image(images)
    
    if extracted_data:
        save_branch_trading_data(extracted_data, manual_date=target_date)
        return {"status": "success", "count": len(extracted_data), "data": extracted_data}
    else:
        raise HTTPException(status_code=400, detail="未能從圖片中提取到有效數據")

@router.get("/api/v1/chips/branch-trading")
async def get_branch_trading(symbol: Optional[str] = None):
    root_path = Path(__file__).parent.parent.parent.absolute()
    db_path = root_path / 'data' / 'market.duckdb'
    
    try:
        with duckdb.connect(str(db_path)) as conn:
            if symbol:
                query = "SELECT * FROM branch_trading WHERE stock_id = ? ORDER BY snapshot_date DESC, net_vol DESC"
                results = conn.execute(query, [symbol]).df().to_dict(orient="records")
            else:
                query = "SELECT * FROM branch_trading ORDER BY snapshot_date DESC, net_vol DESC LIMIT 100"
                results = conn.execute(query).df().to_dict(orient="records")
            return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.get("/api/v1/chips/warrants")
async def get_warrant_positions(symbol: Optional[str] = None):
    """
    從 DuckDB 讀取權證分點庫存數據
    """
    root_path = Path(__file__).parent.parent.parent.absolute()
    db_path = root_path / 'data' / 'market.duckdb'
    
    try:
        with duckdb.connect(str(db_path)) as conn:
            if symbol:
                query = "SELECT * FROM warrant_branch_positions WHERE stock_id = ? ORDER BY snapshot_date DESC, amount_k DESC"
                results = conn.execute(query, [symbol]).df().to_dict(orient="records")
            else:
                query = "SELECT * FROM warrant_branch_positions ORDER BY snapshot_date DESC, amount_k DESC"
                results = conn.execute(query).df().to_dict(orient="records")
            return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.post("/api/v1/chips/analyze")
async def analyze_chips_endpoint(
    symbol: str = Form(...),
    is_short: bool = Form(False),
    tech_data: Optional[str] = Form(None),
    files: List[UploadFile] = File(...)
):
    """
    接收圖片上傳與參數，透過 Gemini Vision 進行籌碼分析 (SSE 串流回傳)
    """
    if not files:
        raise HTTPException(status_code=400, detail="未檢測到圖片，請上傳籌碼分佈截圖。")

    # 準備圖片資料 (將 UploadFile 轉為 PIL Image)
    images = []
    for file in files:
        try:
            content = await file.read()
            img = Image.open(io.BytesIO(content))
            images.append(img)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"圖片 {file.filename} 讀取失敗: {str(e)}")

    # 如果有技術面數據，嘗試解析 JSON
    parsed_tech = None
    if tech_data:
        try:
            parsed_tech = json.loads(tech_data)
        except:
            pass

    async def event_generator():
        try:
            # 取得 engine_chips 的產生器 (注意: 原本 engine_chips.stream_analyze_chips_image 接收 PIL Image list)
            # 因為原 engine 使用了 model.generate_content([prompt] + images, stream=True)
            # 我們這裡需要一個适配器來傳遞 PIL Images
            
            # 使用 engine_chips 的邏輯，但為了 SSE 需要特別處理
            # 原 engine 直接 yield 文字，我們包裝成 SSE 格式
            
            generator = engine_chips.stream_analyze_chips_image(images, symbol, tech_data=parsed_tech, is_short=is_short)
            
            for chunk in generator:
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
