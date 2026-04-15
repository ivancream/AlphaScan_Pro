from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import os
import google.generativeai as genai
from fastapi.responses import StreamingResponse

from engines import engine_fundamental

router = APIRouter()

class SentimentRequest(BaseModel):
    stock_code: str

class AIReportRequest(BaseModel):
    stock_code: str
    data_info: Dict[str, Any]
    sentiment_summary: Dict[str, Any]

class ChatRequest(BaseModel):
    user_msg: str
    context_report: str
    history: List[Dict[str, str]]

@router.get("/api/v1/fundamental/info/{stock_code}")
async def get_basic_info(stock_code: str):
    """
    獲取個股基本面硬數據 (PE, ROE, 營收成長, 自由現金流等)
    """
    try:
        data = engine_fundamental.get_stock_info(stock_code)
        if not data:
            raise HTTPException(status_code=404, detail="Stock data not found")
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/v1/fundamental/sentiment/{stock_code}")
async def get_sentiment_news(stock_code: str):
    """
    爬取新聞與 PTT 情緒
    """
    try:
        summary = engine_fundamental.get_sentiment_summary(stock_code)
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/v1/fundamental/stream-report")
async def generate_fundamental_stream_report(req: AIReportRequest):
    """
    生成基本面 AI 深度報告 (SSE)
    """
    def event_generator():
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            yield f"data: 尚未配置 GEMINI_API_KEY\n\n"
            return
            
        genai.configure(api_key=GEMINI_API_KEY)
        
        generator = engine_fundamental.stream_generate_ai_report(
            req.stock_code, req.data_info, req.sentiment_summary
        )
        for chunk in generator:
            safe_chunk = str(chunk).replace("\n", "<br>")
            yield f"data: {safe_chunk}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/api/v1/fundamental/stream-chat")
async def chat_with_fundamental_analyst(req: ChatRequest):
    """
    基本面 AI 分析師動態解盤對話 (SSE)
    """
    def event_generator():
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            yield f"data: 尚未配置 GEMINI_API_KEY\n\n"
            return
            
        genai.configure(api_key=GEMINI_API_KEY)
        
        generator = engine_fundamental.stream_chat_with_analyst(
            req.user_msg, req.context_report, req.history
        )
        for chunk in generator:
            safe_chunk = str(chunk).replace("\n", "<br>")
            yield f"data: {safe_chunk}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")
