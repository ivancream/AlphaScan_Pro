from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import os
import google.generativeai as genai
from fastapi.responses import StreamingResponse
import pandas as pd
import sqlite3
from pathlib import Path

root_path = Path(__file__).parent.parent.parent.parent.absolute()
DB_FILE = root_path / "data" / "taiwan_stock.db"

from engines import engine_technical

router = APIRouter()

class TechnicalReportRequest(BaseModel):
    stock_code: str
    period: str = "1y"

class ChatRequest(BaseModel):
    user_msg: str
    history: List[Dict[str, str]]

def fetch_data_from_db(stock_code: str) -> pd.DataFrame:
    """從 SQLite 獲取歷史 K 線數據 (取代原本 yfinance)"""
    try:
        # Normalize symbol
        symbol = str(stock_code).strip().upper()
        # 嘗試找出正確的後綴
        symbols_to_try = []
        if symbol.isdigit() and len(symbol) in [4, 5]:
            symbols_to_try = [f"{symbol}.TW", f"{symbol}.TWO"]
        else:
            symbols_to_try = [symbol]
            
        with sqlite3.connect(str(DB_FILE)) as conn:
            for s in symbols_to_try:
                # 這裡 SQLite 的 table 是 daily_price, column 是 stock_id
                clean_id = s.split('.')[0]
                df = pd.read_sql("""
                    SELECT date as Date, open as Open, high as High, low as Low, close as Close, volume as Volume
                    FROM daily_price
                    WHERE stock_id = ?
                    ORDER BY date ASC
                """, conn, params=[clean_id])
                
                if not df.empty:
                    df['Date'] = pd.to_datetime(df['Date'])
                    df.set_index('Date', inplace=True)
                    return df
            
        return None
        
        # 為了相容 engine_technical 的 pandas_ta 計算，將 Date 設為 index
        df.set_index('Date', inplace=True)
        return df
    except Exception as e:
        print(f"DuckDB fetch error: {e}")
        return None

@router.get("/api/v1/technical/indicators/{stock_code}")
async def get_technical_indicators(stock_code: str):
    """
    提供技術指標計算後的最末筆摘要
    """
    try:
        df = fetch_data_from_db(stock_code)
        if df is None or df.empty:
            df = engine_technical.fetch_data(stock_code, "6mo")
            
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="No historical data found")
            
        df_calc = engine_technical.calculate_indicators(df)
        summary = engine_technical.get_latest_summary(df_calc)
        
        name = engine_technical.get_symbol_name(stock_code)
        
        return {
            "symbol": stock_code,
            "name": name,
            "summary": summary
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
        
        df = fetch_data_from_db(req.stock_code)
        if df is None or df.empty:
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
