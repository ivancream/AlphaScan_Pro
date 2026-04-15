from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List
import os
import time
import asyncio
import google.generativeai as genai
from fastapi.responses import StreamingResponse

# 載入原有的核心解析引擎
from engines import engine_global

router = APIRouter()

class GlobalReportRequest(BaseModel):
    market_name: str

class ChatRequest(BaseModel):
    user_msg: str
    report_context: str
    chat_history: List[Dict[str, str]]

@router.get("/api/v1/global/fast-test")
async def fast_test():
    return {"status": "ok", "time": time.time()}

@router.get("/api/v1/global/macro-data")
async def get_macro_data():
    """
    獲取最新總經指標 (並行 pre-fetch + Cache)
    """
    try:
        task_short = asyncio.to_thread(engine_global.get_short_term_data)
        task_long = asyncio.to_thread(engine_global.get_long_term_data)
        
        short_term, long_term = await asyncio.gather(task_short, task_long)
        return {"short": short_term, "long": long_term}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/v1/global/market-metrics/{market_name}")
async def get_regional_metrics(market_name: str):
    """
    獲取各國大盤的基礎指標漲跌幅 (並行抓取)
    """
    try:
        # 建立並行任務
        task_metrics = asyncio.to_thread(engine_global.get_market_metrics, market_name)
        task_fx = asyncio.to_thread(engine_global.get_fx_data, market_name)
        
        results = await asyncio.gather(task_metrics, task_fx)
        metrics_tuple, fx_val = results
        metrics, status = metrics_tuple
        
        return {"metrics": metrics, "status": status, "fx_val": fx_val}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/v1/global/market-news/{market_name}")
async def get_regional_news(market_name: str):
    """
    獲取指定市場的即時新聞爬蟲 (免 AI)
    """
    try:
        news = await asyncio.to_thread(engine_global.get_investing_news, market_name)
        return {"news": news}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/v1/global/stream-report")
async def generate_global_stream_report(req: GlobalReportRequest):
    """
    以 SSE 串流回傳 Gemini AI 全球市場報告 (大幅優化 pre-fetch 速度)
    """
    market_select = req.market_name
    
    # 全部任務並行執行
    tasks = [
        asyncio.to_thread(engine_global.get_market_metrics, market_select),
        asyncio.to_thread(engine_global.get_fx_data, market_select),
        asyncio.to_thread(engine_global.get_investing_news, market_select),
        asyncio.to_thread(engine_global.get_short_term_data),
        asyncio.to_thread(engine_global.get_long_term_data)
    ]
    
    results = await asyncio.gather(*tasks)
    
    (metrics_val, _), fx_val, news_summary, s_data, l_data = results
    metrics = metrics_val
    
    macro_str = f"VIX: {s_data.get('vix')} | Bond: {s_data.get('bond')}"
    commo_str = f"Gold: {s_data.get('gold')} | CPI: {l_data.get('cpi')}"

    def event_generator():
        # 設定 API Key
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            yield f"data: 尚未配置 GEMINI_API_KEY\n\n"
            return
            
        genai.configure(api_key=GEMINI_API_KEY)
        
        generator = engine_global.stream_generate_global_report(
            market_select, metrics, macro_str, fx_val, commo_str, news_summary
        )
        for chunk in generator:
            # Server-Sent Events (SSE) format requires "data: <string>\n\n"
            # 替換掉換行符號避免 SSE 格式錯誤
            safe_chunk = str(chunk).replace("\n", "<br>")
            yield f"data: {safe_chunk}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/api/v1/global/stream-chat")
async def chat_with_analyst(req: ChatRequest):
    """
    AI 策略師動態解盤對話 (SSE)
    """
    def event_generator():
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        if not GEMINI_API_KEY:
            yield f"data: 尚未配置 GEMINI_API_KEY\n\n"
            return
            
        genai.configure(api_key=GEMINI_API_KEY)
        
        # Generator for conversation logic
        generator = engine_global.stream_chat_with_global_analyst(
            req.user_msg, req.report_context, req.chat_history
        )
        for chunk in generator:
            safe_chunk = str(chunk).replace("\n", "<br>")
            yield f"data: {safe_chunk}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")
