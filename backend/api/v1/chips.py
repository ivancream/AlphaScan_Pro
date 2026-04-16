import io
import json
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import google.generativeai as genai
from PIL import Image

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from engines import engine_chips

from backend.db.connection import duck_write, duck_read

router = APIRouter()


def save_warrant_data(data: List[Dict[str, Any]], manual_date: Optional[str] = None):
    """將提取的權證數據存入 DuckDB warrant_positions 表"""
    if not data:
        return
    with duck_write() as conn:
        for item in data:
            target_date = manual_date if manual_date else item.get("date")
            conn.execute(
                """
                INSERT INTO warrant_positions
                    (snapshot_date, stock_id, stock_name, branch_name,
                     position_shares, est_pnl, est_pnl_pct, amount_k, type)
                VALUES (?::DATE, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (snapshot_date, stock_id, branch_name, type) DO UPDATE SET
                    amount_k       = excluded.amount_k,
                    est_pnl        = excluded.est_pnl,
                    est_pnl_pct    = excluded.est_pnl_pct,
                    position_shares = excluded.position_shares,
                    stock_name     = excluded.stock_name
                """,
                [
                    target_date,
                    item.get("stock_symbol"),
                    item.get("stock_name"),
                    item.get("broker"),
                    item.get("position_shares", 0),
                    item.get("estimated_pnl", 0),
                    item.get("estimated_pnl_pct", 0),
                    item.get("amount_k"),
                    item.get("type", "認購"),
                ],
            )


@router.post("/api/v1/chips/ingest")
async def ingest_warrants_endpoint(
    files: List[UploadFile] = File(...),
    target_date: Optional[str] = Form(None),
):
    """掃描截圖並將數據存入資料庫，支援手動指定日期"""
    images = []
    for file in files:
        content = await file.read()
        images.append(Image.open(io.BytesIO(content)))

    extracted_data = engine_chips.extract_warrant_data_from_image(images)

    if extracted_data:
        save_warrant_data(extracted_data, manual_date=target_date)
        return {"status": "success", "count": len(extracted_data), "data": extracted_data}
    else:
        raise HTTPException(status_code=400, detail="未能從圖片中提取到有效數據")


def save_branch_trading_data(data: List[Dict[str, Any]], manual_date: Optional[str] = None):
    """將提取的分點買賣超數據存入 DuckDB branch_trading 表"""
    if not data:
        return
    with duck_write() as conn:
        for item in data:
            target_date = manual_date if manual_date else item.get("date")
            conn.execute(
                """
                INSERT INTO branch_trading
                    (trade_date, stock_id, stock_name, branch_name,
                     buy_shares, sell_shares, net_shares, side)
                VALUES (?::DATE, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (trade_date, stock_id, branch_name) DO UPDATE SET
                    buy_shares  = excluded.buy_shares,
                    sell_shares = excluded.sell_shares,
                    net_shares  = excluded.net_shares,
                    stock_name  = excluded.stock_name
                """,
                [
                    target_date,
                    item.get("stock_symbol"),
                    item.get("stock_name"),
                    item.get("broker"),
                    item.get("buy_vol", 0),
                    item.get("sell_vol", 0),
                    item.get("net_vol", 0),
                    item.get("side", "NET"),
                ],
            )


@router.post("/api/v1/chips/branch-trading/ingest")
async def ingest_branch_trading_endpoint(
    files: List[UploadFile] = File(...),
    target_date: Optional[str] = Form(None),
):
    """掃描截圖並將分點買賣超數據存入資料庫"""
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
    try:
        with duck_read() as conn:
            if symbol:
                results = conn.execute(
                    "SELECT * FROM branch_trading WHERE stock_id = ? ORDER BY trade_date DESC, net_shares DESC",
                    [symbol],
                ).df().to_dict(orient="records")
            else:
                results = conn.execute(
                    "SELECT * FROM branch_trading ORDER BY trade_date DESC, net_shares DESC LIMIT 100"
                ).df().to_dict(orient="records")
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/api/v1/chips/warrants")
async def get_warrant_positions(symbol: Optional[str] = None):
    """從 DuckDB 讀取權證分點庫存數據"""
    try:
        with duck_read() as conn:
            if symbol:
                results = conn.execute(
                    "SELECT * FROM warrant_positions WHERE stock_id = ? ORDER BY snapshot_date DESC, amount_k DESC",
                    [symbol],
                ).df().to_dict(orient="records")
            else:
                results = conn.execute(
                    "SELECT * FROM warrant_positions ORDER BY snapshot_date DESC, amount_k DESC LIMIT 200"
                ).df().to_dict(orient="records")
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.post("/api/v1/chips/analyze")
async def analyze_chips_endpoint(
    symbol: str = Form(...),
    is_short: bool = Form(False),
    tech_data: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
):
    """接收圖片上傳與參數，透過 Gemini Vision 進行籌碼分析 (SSE 串流回傳)"""
    if not files:
        raise HTTPException(status_code=400, detail="未檢測到圖片，請上傳籌碼分佈截圖。")

    images = []
    for file in files:
        try:
            content = await file.read()
            images.append(Image.open(io.BytesIO(content)))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"圖片 {file.filename} 讀取失敗: {str(e)}")

    parsed_tech = None
    if tech_data:
        try:
            parsed_tech = json.loads(tech_data)
        except Exception:
            pass

    async def event_generator():
        try:
            generator = engine_chips.stream_analyze_chips_image(
                images, symbol, tech_data=parsed_tech, is_short=is_short
            )
            for chunk in generator:
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
