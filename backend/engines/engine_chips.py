# engine_chips.py
import os
import google.generativeai as genai
from PIL import Image
from typing import List, Union, Dict, Any
from . import prompts

# ==========================================
# 設定區
# ==========================================
# 使用 os.getenv 讀取環境變數
# 使用 os.environ.get 讀取環境變數
# GEMINI_API_KEY is configured in main_app.py

def get_vision_model() -> genai.GenerativeModel:
    model_id = os.getenv("GEMINI_MODEL_ID", "gemini-1.5-flash")
    return genai.GenerativeModel(model_id)

def stream_analyze_chips_image(uploaded_files: List[Any], stock_symbol: str, tech_data: Dict[str, Any] = None, is_short: bool = False) -> Any:
    """
    接收 Streamlit 上傳的圖片檔案列表，串流回傳 AI 分析結果
    """
    model = get_vision_model()
    
    image_parts = []
    for uploaded_file in uploaded_files:
        try:
            if isinstance(uploaded_file, Image.Image):
                image_parts.append(uploaded_file)
            else:
                uploaded_file.seek(0)
                image = Image.open(uploaded_file)
                image_parts.append(image)
        except Exception as e:
            yield f"圖片讀取失敗: {e}"
            return
        
    if not image_parts:
        yield "未檢測到圖片，請上傳籌碼分佈截圖。"
        return

    if tech_data:
        tech_context = f"""
        **已計算的技術面分析參考：**
        * 收盤價: {tech_data.get('Close', 'N/A')}
        * 布林帶寬變動: {tech_data.get('Bandwidth_Chg', 'N/A')}%
        * 上軌斜率: {tech_data.get('Upper_Slope_Pct', tech_data.get('Slope_Pct', 'N/A'))}%
        * 月線斜率: {tech_data.get('MA20_Slope_Pct', 'N/A')}%
        * 成交量比: {tech_data.get('Vol_Ratio', 'N/A')}倍
        * 上軌位置: {tech_data.get('Pos_Upper', 'N/A')}%
        """
        if is_short:
            prompt = prompts.get_band_short_analysis_prompt(tech_context)
        else:
            prompt = prompts.get_band_long_analysis_prompt(tech_context)
    else:
        prompt = prompts.get_chips_analysis_prompt(stock_symbol)

    def _generator():
        try:
            # Gemini 1.5 Flash 支援 Vision + Streaming
            response = model.generate_content([prompt] + image_parts, stream=True)
            for chunk in response:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            yield f"AI 分析失敗: {e}"

    return _generator()

def analyze_chips_image(uploaded_files: List[Any], stock_symbol: str, tech_data: Dict[str, Any] = None, is_short: bool = False) -> str:

    """
    接收 Streamlit 上傳的圖片檔案列表，回傳 AI 分析結果
    """
    print(f"Starting chips analysis for {stock_symbol} with {len(uploaded_files)} images...")
    model = get_vision_model()
    
    # 準備圖片資料
    image_parts = []
    for uploaded_file in uploaded_files:
        try:
            # Reset pointer to start just in case, though streamlit usually handles this
            uploaded_file.seek(0)
            image = Image.open(uploaded_file)
            image_parts.append(image)
        except Exception as e:
            print(f"Error opening image: {e}")
            return f"圖片讀取失敗: {e}"
        
    if not image_parts:
        return "未檢測到圖片，請上傳籌碼分佈截圖。"

    
    # 判斷是否為技術面整合模式
    if tech_data:
        # 建構技術面 Context String
        tech_context = f"""
        **已計算的技術面分析參考：**
        * 收盤價: {tech_data.get('Close', 'N/A')}
        * 布林帶寬變動: {tech_data.get('Bandwidth_Chg', 'N/A')}%
        * 上軌斜率: {tech_data.get('Upper_Slope_Pct', tech_data.get('Slope_Pct', 'N/A'))}%
        * 月線斜率: {tech_data.get('MA20_Slope_Pct', 'N/A')}%
        * 成交量比: {tech_data.get('Vol_Ratio', 'N/A')}倍
        * 上軌位置: {tech_data.get('Pos_Upper', 'N/A')}%
        """
        # 根據模式選擇提示詞
        if is_short:
            prompt = prompts.get_band_short_analysis_prompt(tech_context)
        else:
            prompt = prompts.get_band_long_analysis_prompt(tech_context)
    else:
        # 純籌碼模式
        prompt = prompts.get_chips_analysis_prompt(stock_symbol)

    try:
        print("Sending request to Gemini Vision...")
        response = model.generate_content([prompt] + image_parts)
        print("Gemini response received.")
        return response.text
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return f"AI 分析失敗: {e}"

def extract_warrant_data_from_image(uploaded_files: List[Any]) -> List[Dict[str, Any]]:
    """
    使用結構化 Prompt 從圖片中提取權證數據
    """
    model = get_vision_model()
    image_parts = []
    for f in uploaded_files:
        if isinstance(f, Image.Image):
            image_parts.append(f)
        else:
            f.seek(0)
            image_parts.append(Image.open(f))
            
    prompt = prompts.get_warrant_structured_extraction_prompt()
    
    try:
        response = model.generate_content([prompt] + image_parts)
        # 嘗試解析 JSON
        text = response.text.strip()
        # 移除 markdown code block 標籤
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())
    except Exception as e:
        print(f"Data extraction failed: {e}")
        return []

def extract_branch_trading_from_image(uploaded_files: List[Any]) -> List[Dict[str, Any]]:
    """
    使用結構化 Prompt 從圖片中提取分點買賣超數據
    """
    model = get_vision_model()
    image_parts = []
    for f in uploaded_files:
        if isinstance(f, Image.Image):
            image_parts.append(f)
        else:
            f.seek(0)
            image_parts.append(Image.open(f))
            
    prompt = prompts.get_branch_trading_structured_extraction_prompt()
    
    try:
        response = model.generate_content([prompt] + image_parts)
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())
    except Exception as e:
        print(f"Branch trading extraction failed: {e}")
        return []
