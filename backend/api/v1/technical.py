from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import os
import google.generativeai as genai
from fastapi.responses import StreamingResponse
import pandas as pd

from engines import engine_technical

router = APIRouter()

class TechnicalReportRequest(BaseModel):
    stock_code: str
    period: str = "1y"

class ChatRequest(BaseModel):
    user_msg: str
    history: List[Dict[str, str]]

@router.get("/api/v1/technical/indicators/{stock_code}")
async def get_technical_indicators(stock_code: str):
    """
    提供技術指標計算後的最末筆摘要（包含今日盤中快照）
    """
    try:
        df = engine_technical.fetch_data(stock_code, "6mo")

        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="No historical data found")

        df_calc = engine_technical.calculate_indicators(df)
        summary = engine_technical.get_latest_summary(df_calc)
        name = engine_technical.get_symbol_name(stock_code)

        return {
            "symbol": stock_code,
            "name": name,
            "summary": summary,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/v1/technical/stream-report")
async def generate_technical_stream_report(req: TechnicalReportRequest):
    """
    生成技術面 AI 分析報告 (SSE)
    """
    def event_generator():
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            yield f"data: 尚未配置 GEMINI_API_KEY\n\n"
            return
            
        genai.configure(api_key=GEMINI_API_KEY)
        
        df = engine_technical.fetch_data(req.stock_code, req.period)
             
        if df is None or df.empty:
            yield f"data: 無法取得股價技術資料\n\n"
            return
            
        df_calc = engine_technical.calculate_indicators(df)
        generator = engine_technical.stream_initial_analysis(df_calc, req.stock_code)
        
        for chunk in generator:
            safe_chunk = str(chunk).replace("\n", "<br>")
            yield f"data: {safe_chunk}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/api/v1/technical/stream-chat")
async def chat_with_technical_analyst(req: ChatRequest):
    """
    技術面 AI 動態對話
    """
    # 這裡的 continue_chat 原本是無狀態的回傳字串，若要封裝為 SSE 可以包裝一下
    def event_generator():
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            yield f"data: 尚未配置 GEMINI_API_KEY\n\n"
            return
            
        genai.configure(api_key=GEMINI_API_KEY)
        
        response_text, _ = engine_technical.continue_chat(req.user_msg, req.history)
        
        # 簡單切塊模擬 Stream（因為原始 engine_technical.continue_chat 沒有實作 generator）
        safe_response = str(response_text).replace("\n", "<br>")
        yield f"data: {safe_response}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")
