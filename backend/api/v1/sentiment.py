import os
import json
import google.generativeai as genai
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class QualResponse(BaseModel):
    symbol: str
    sentiment_score: int
    summary: str
    key_factors: list[str]

@router.get("/api/v1/qualitative/{symbol}", response_model=QualResponse)
async def get_qualitative_analysis(symbol: str):
    # 從環境變數讀取 API Key
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        # 開發期間若尚未設定，回傳假資料以利前端串接測試
        return QualResponse(
           symbol=symbol,
           sentiment_score=75,
           summary="這是在尚未設定 Gemini API Key 時的模擬回應。該標的近期表現強勁，受惠於 AI 晶片需求大增。",
           key_factors=["AI伺服器出貨量增強", "外資調升目標價", "法說會釋出樂觀展望"]
        )

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # 此處假設已取得 raw_news_data (未來可串接爬蟲)
    raw_news_data = f"近期關於 {symbol} 的市場新聞、PTT股版討論與法人報告內文..."
    
    prompt = f"""
    請作為專業量化金融分析師，分析以下 {symbol} 的近期資訊。
    你必須嚴格以 JSON 格式回傳結果，包含以下欄位：
    - sentiment_score (整數 0-100，大於 50 偏多，小於 50 偏空)
    - summary (繁體中文，限 100 字以內，語氣專業精煉)
    - key_factors (字串陣列，精準列出 3 個影響股價的關鍵驅動因素)
    
    近期資訊：
    {raw_news_data}
    """
    
    try:
        # 啟用 JSON Schema 強制輸出模式
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        return json.loads(response.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini AI 解析失敗: {str(e)}")
