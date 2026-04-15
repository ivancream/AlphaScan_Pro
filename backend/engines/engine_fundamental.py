import os
import time
import re
import requests
import pandas as pd
import yfinance as yf
import google.generativeai as genai
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, Optional, Union, Any, List
from concurrent.futures import ThreadPoolExecutor

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from . import prompts

# ==========================================
# 1. 設定與工具函式 (Setup & Utils)
# ==========================================
# 使用 os.getenv 讀取環境變數
# 使用 os.environ.get 讀取環境變數
# GEMINI_API_KEY is configured in main_app.py

def get_model() -> genai.GenerativeModel:
    model_id = os.getenv("GEMINI_MODEL_ID", "gemini-1.5-flash")
    return genai.GenerativeModel(model_id)

def remove_emojis(text: str) -> str:
    """ 移除 Emoji，保持報告專業度 """
    return re.sub(r'[^\w\s,.:;!?()\[\]{}@#$%^&*\-+=/\\\'"<>~`|]', '', text)

def calculate_technicals_str(hist_df: pd.DataFrame) -> str:
    """ 計算技術指標並回傳格式化字串 (供 AI 閱讀) """
    try:
        if len(hist_df) < 60: return "Data insufficient for technicals"
        
        close = hist_df['Close']
        ma5 = close.rolling(window=5).mean().iloc[-1]
        ma20 = close.rolling(window=20).mean().iloc[-1]
        ma60 = close.rolling(window=60).mean().iloc[-1]
        
        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain.iloc[-1] / loss.iloc[-1]
        rsi = 100 - (100 / (1 + rs))
        
        # KD (9, 3, 3)
        low_9 = hist_df['Low'].rolling(window=9).min()
        high_9 = hist_df['High'].rolling(window=9).max()
        rsv = ((close - low_9) / (high_9 - low_9)) * 100
        k = 50.0
        d = 50.0
        for val in rsv:
            if not pd.isna(val):
                k = (2/3) * k + (1/3) * val
                d = (2/3) * d + (1/3) * k
        
        # Trend Status
        trend = "Bullish (Strong)" if ma5 > ma20 > ma60 else ("Bearish (Weak)" if ma5 < ma20 < ma60 else "Consolidation")
        
        return (f"Trend: {trend} | RSI(14): {rsi:.2f} | K: {k:.2f} | D: {d:.2f} | "
                f"MA5: {ma5:.2f} | MA20: {ma20:.2f} | MA60: {ma60:.2f}")
    except:
        return "Technical calculation error"

# ==========================================
# 2. 核心數據獲取 (Data Mining)
# ==========================================
def get_stock_info(stock_code: str) -> Optional[Dict[str, Union[str, float]]]:
    """
    獲取硬數據：股價、PE、ROE、技術指標
    回傳: dict (包含所有關鍵數據)
    """
    result: Dict[str, Union[str, float]] = {}
    
    try:
        # 1. 處理代碼
        code = stock_code.strip().upper()
        if code.isdigit():
            # 優先嘗試台灣上市，若無則嘗試上櫃 (這裡簡化邏輯)
            ticker = yf.Ticker(f"{code}.TW")
            hist = ticker.history(period="3mo")
            if hist.empty:
                ticker = yf.Ticker(f"{code}.TWO")
                hist = ticker.history(period="3mo")
        else:
            ticker = yf.Ticker(code)
            hist = ticker.history(period="3mo")
            
        if hist.empty:
            return None

        # 2. 獲取基本面 (Fundamentals)
        info = ticker.info
        result['name'] = info.get('longName', code)
        
        # Try to get price from info, fallback to history
        current_price = info.get('currentPrice') or info.get('regularMarketPrice')
        if not current_price:
            current_price = hist.iloc[-1]['Close']
        
        result['price'] = round(current_price, 2)
        
        # PE / ROE / Growth / Margin / Debt / FCF
        pe = info.get('forwardPE') or info.get('trailingPE')
        result['pe'] = f"{pe:.2f}" if pe else "N/A"
        
        roe = info.get('returnOnEquity')
        result['roe'] = f"{roe*100:.2f}%" if roe else "N/A"
        
        rev_growth = info.get('revenueGrowth')
        result['growth'] = f"{rev_growth*100:.2f}%" if rev_growth else "N/A"

        margin = info.get('grossMargins')
        result['margin'] = f"{margin*100:.2f}%" if margin else "N/A"

        debt = info.get('debtToEquity')
        result['debt_ratio'] = f"{debt:.2f}%" if debt else "N/A"

        fcf = info.get('freeCashflow')
        if fcf:
            result['fcf'] = f"{fcf/1e8:.2f} 億" # 轉成億為單位
        else:
            result['fcf'] = "N/A"
        
        # 3. 計算技術指標 (Technicals)
        result['technicals'] = calculate_technicals_str(hist)
        
        return result
        
    except Exception as e:
        print(f"Error in get_stock_info: {e}")
        return None

# ==========================================
# 3. 消息面爬蟲 (Sentiment Mining)
# ==========================================

def get_google_news(keyword: str, site: str = "", label: str = "") -> str:
    """ 高效使用 Google News RSS 取得特定網站的新聞，並附帶日期 """
    import xml.etree.ElementTree as ET
    
    query = f"{keyword} site:{site}" if site else f"{keyword} 股市"
    base_url = "https://news.google.com/rss/search"
    params = {"q": query, "hl": "zh-TW", "gl": "TW", "ceid": "TW:zh-Hant"}
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        resp = requests.get(base_url, params=params, headers=headers, timeout=5)
        root = ET.fromstring(resp.text)
        results = []
        for item in root.findall(".//item")[:3]:
            title = item.find("title")
            pub = item.find("pubDate")
            if title is not None and title.text:
                d = pub.text[:16] if pub is not None and pub.text else ""
                # 清理標題結尾通常帶有的報社名稱 (如 " - Yahoo奇摩股市")
                clean_t = title.text.split(" - ")[0]
                results.append(f"- [{d}] [{label}] {clean_t}")
        return "\n".join(results) if results else f"No specific news on {label}."
    except Exception as e:
        print(f"News RSS error for {label}: {e}")
        return f"No specific news on {label}."

def get_ptt_sentiment(clean_code: str) -> str:
    """ PTT Stock 版爬蟲 """
    headers = {'User-Agent': 'Mozilla/5.0', 'Cookie': 'over18=1'}
    url = f"https://www.ptt.cc/bbs/Stock/search?q={clean_code}"
    posts = []
    try:
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        divs = soup.find_all('div', class_='r-ent')
        for i, div in enumerate(divs):
            try:
                title = div.find('div', class_='title').text.strip()
                date_str = div.find('div', class_='date').text.strip()
                # 簡單判斷是否為近期 (這裡簡化邏輯)
                posts.append(f"- [{date_str}] {title}")
                if i >= 4: # 取得 5 篇後停止
                    break
            except: continue
    except Exception: pass
    return "\n".join(posts) if posts else "Low retail discussion on PTT."

def get_sentiment_summary(stock_code: str) -> Dict[str, str]:
    """
    整合新聞與 PTT 爬蟲 (並行加速)
    """
    # 處理代碼與名稱
    clean_code = stock_code.replace(".TW", "").replace(".TWO", "")
    search_keyword = clean_code
        
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_anue = executor.submit(get_google_news, search_keyword, "cnyes.com", "Anue")
        future_yahoo = executor.submit(get_google_news, search_keyword, "tw.stock.yahoo.com", "Yahoo")
        future_ptt = executor.submit(get_ptt_sentiment, clean_code)
        
        return {
            'anue': future_anue.result(),
            'yahoo': future_yahoo.result(),
            'ptt': future_ptt.result()
        }

# ==========================================
# 4. AI 報告生成 (AI Synthesis)
# ==========================================
def remove_emojis(text: str) -> str:
    """ 移除 Emoji，保持報告專業度，並確保不破壞中文字元 """
    if not text:
        return ""
    # 修正 Regex: 
    # 1. 將 - 放在開頭或結尾避免變成 range
    # 2. 確保涵蓋常見標點符號，同時保留 \w (包含中文) 與 \s (包含換行)
    return re.sub(r'[^\w\s,.:;!?()\[\]{}@#$%^&*\-+=/\\\'"<>~`|]', '', text)

def generate_ai_report(stock_code: str, data_info: Dict, sentiment_summary: Dict) -> str:
    """
    整合數據與情緒，生成 Markdown 報告 (非串流版)
    """
    model = get_model()
    financials_str = f"""
    * Price: {data_info.get('price')}
    * Fundamentals: PE: {data_info.get('pe')} | ROE: {data_info.get('roe')} | Rev Growth: {data_info.get('growth')}
    * Technicals: {data_info.get('technicals')}
    """
    sentiment_str = f"""
    - News (Anue): {sentiment_summary.get('anue')}
    - News (Yahoo): {sentiment_summary.get('yahoo')}
    - Retail (PTT): {sentiment_summary.get('ptt')}
    """
    prompt = prompts.get_fundamental_report_prompt(stock_code, financials_str, sentiment_str)
    try:
        response = model.generate_content(prompt)
        return remove_emojis(response.text)
    except Exception as e:
        return f"AI Report Generation Error: {e}"

def stream_generate_ai_report(stock_code: str, data_info: Dict, sentiment_summary: Dict) -> Any:
    """
    串流產生基本面分析報告
    """
    model = get_model()
    financials_str = f"""
    * Price: {data_info.get('price')}
    * Fundamentals: PE: {data_info.get('pe')} | ROE: {data_info.get('roe')} | Rev Growth: {data_info.get('growth')}
    * Technicals: {data_info.get('technicals')}
    """
    sentiment_str = f"""
    - News (Anue): {sentiment_summary.get('anue')}
    - News (Yahoo): {sentiment_summary.get('yahoo')}
    - Retail (PTT): {sentiment_summary.get('ptt')}
    """
    prompt = prompts.get_fundamental_report_prompt(stock_code, financials_str, sentiment_str)

    def _generator():
        try:
            # 使用更穩定的串流讀取方式
            response = model.generate_content(prompt, stream=True)
            for chunk in response:
                try:
                    if chunk.text:
                        yield remove_emojis(chunk.text)
                except (ValueError, AttributeError):
                    # 處理安全過濾造成的 text 存取錯誤
                    continue
        except Exception as e:
            yield f"AI Report Generation Error: {e}"
    return _generator()

def chat_with_analyst(user_msg: str, context_report: str, history: list = []) -> str:
    """
    讓使用者針對報告進行提問 (支援對話記憶) (非串流版)
    """
    model = get_model()
    history_text = ""
    for msg in history:
        role = "User" if msg['role'] == "user" else "Analyst"
        history_text += f"{role}: {msg['content']}\n\n"
    prompt = prompts.get_fundamental_chat_prompt(context_report, history_text, user_msg)
    try:
        response = model.generate_content(prompt)
        return remove_emojis(response.text)
    except Exception as e:
        return f"Chat Error: {e}"

def stream_chat_with_analyst(user_msg: str, context_report: str, history: list = []) -> Any:
    """
    串流與分析師對話
    """
    model = get_model()
    history_text = ""
    for msg in history:
        role = "User" if msg['role'] == "user" else "Analyst"
        history_text += f"{role}: {msg['content']}\n\n"
    prompt = prompts.get_fundamental_chat_prompt(context_report, history_text, user_msg)
    
    def _generator():
        try:
            for chunk in model.generate_content(prompt, stream=True):
                if chunk.text:
                    yield remove_emojis(chunk.text)
        except Exception as e:
            yield f"Chat Error: {e}"
    return _generator()
