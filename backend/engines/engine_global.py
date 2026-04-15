import os
import time
from datetime import datetime
import re
import requests
import xml.etree.ElementTree as ET
import yfinance as yf
import pandas as pd
import google.generativeai as genai
from typing import Dict, List, Tuple, Any, Optional
from concurrent.futures import ThreadPoolExecutor
import threading


# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# ==========================================
# 設定與常數
# GEMINI_API_KEY is configured in dashboard.py

MARKET_MAP = {
    "TAIEX (TWII)": "^TWII",
    "Nikkei 225 (N225)": "^N225",
    "KOSPI (KS11)": "^KS11",
    "Nasdaq (IXIC)": "^IXIC",
    "PHLX Semi (SOX)": "^SOX"
}

# ---- 全局快取與鎖機制 ----
from . import prompts
_cache_lock = threading.Lock()

_short_cache = {
    "data": None,
    "last_update": 0
}
SHORT_CACHE_TTL = 300  # 5分鐘

_macro_cache = {
    "data": None,
    "last_update": 0
}
CACHE_TTL = 300  # 5分鐘 (開發階段縮短以利驗證)

def get_model() -> genai.GenerativeModel:
    model_id = os.getenv("GEMINI_MODEL_ID", "gemini-1.5-flash")
    return genai.GenerativeModel(model_id)

# ==========================================
# 1. 市場數據 (Market Metrics)
# ==========================================
def get_market_metrics(market_name: str) -> Tuple[str, str]:
    """
    抓取指定市場的最新指數與漲跌幅
    回傳: (metrics_str, status_str)
    """
    symbol = MARKET_MAP.get(market_name, "^TWII")
    try:
        ticker = yf.Ticker(symbol)
        # 用 5 天數據避免遇到假日或休市導致無數據
        hist = ticker.history(period="5d")
        
        if hist.empty:
            return "No Data", "Unknown"
            
        last_close = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2]
        change = last_close - prev_close
        pct_change = (change / prev_close) * 100
        
        metrics = f"{last_close:,.0f} ({pct_change:+.2f}%)"
        
        # 簡單趨勢判斷
        status = "Bullish" if pct_change > 0.5 else ("Bearish" if pct_change < -0.5 else "Neutral")
        
        return metrics, status
    except Exception as e:
        return f"Error: {e}", "Error"

# ==========================================
# 2. 宏觀數據 (Macro & FX)
# ==========================================

def get_short_term_data() -> Dict[str, str]:
    """
    短線攻擊力道 (Daily) - 引進快取與優化
    """
    global _short_cache
    with _cache_lock:
        now = time.time()
        if _short_cache["data"] and (now - _short_cache["last_update"] < SHORT_CACHE_TTL):
            return _short_cache["data"]

    data = {"twd": "N/A", "vix": "N/A", "bond": "N/A", "gold": "N/A"}
    tickers_map = {
        "USDTWD=X": "twd",
        "^VIX": "vix",
        "^TNX": "bond",
        "GC=F": "gold"
    }
    
    try:
        symbols = list(tickers_map.keys())
        # 改為 5d 避免遇到假日 dataframe 空白
        df = yf.download(symbols, period="5d", group_by='ticker', threads=False, progress=False, timeout=10)
        
        if df.empty:
            return data

        for sym, key in tickers_map.items():
            try:
                series = df[sym]['Close'].dropna()
                if series.empty: continue
                val = series.iloc[-1]
                
                if key == "twd": data[key] = f"{val:.2f}"
                elif key == "vix": data[key] = f"{val:.2f}"
                elif key == "bond": data[key] = f"{val:.2f}%"
                elif key == "gold": data[key] = f"{val:,.1f}"
            except Exception as e:
                print(f"Error parse {sym}: {e}")
                continue

        with _cache_lock:
            _short_cache["data"] = data
            _short_cache["last_update"] = time.time()
            
        return data
    except Exception as e:
        print(f"Short term data error: {e}")
        return data

import re

def _fetch_rss_headlines(query: str, max_items: int = 10) -> list:
    """ 回傳 list of (pub_date, title) from Google News RSS """
    base_url = "https://news.google.com/rss/search"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    params = {"q": query, "hl": "zh-TW", "gl": "TW", "ceid": "TW:zh-Hant"}
    try:
        resp = requests.get(base_url, params=params, headers=headers, timeout=5)
        resp.encoding = 'utf-8' # 強制編碼
        root = ET.fromstring(resp.text)
        results = []
        for item in root.findall(".//item")[:max_items]:
            title = item.find("title")
            pub   = item.find("pubDate")
            if title is not None and title.text:
                results.append((pub.text[:16] if pub is not None and pub.text else "", title.text))
        return results
    except:
        return []

def _extract_number_from_headlines(headlines: list, patterns: list) -> str:
    """
    嘗試從標題列表中用 Regex 直接找出數字。
    patterns: list of regex pattern strings
    回傳第一個找到的匹配結果，找不到回傳 None
    """
    for _, title in headlines:
        for pattern in patterns:
            m = re.search(pattern, title)
            if m:
                return m.group(0).strip()
    return None

# ---- 宏觀長線數據 ----

def get_long_term_data() -> Dict[str, str]:
    """
    波段持股水位 (Monthly): US CPI, TW Export, PMI, Light Signal
    策略: 多執行緒並行執行 + 快取機制
    """
    global _macro_cache
    now_dt = datetime.now()
    time_ctx = f"目前時間為 {now_dt.year}年{now_dt.month}月{now_dt.day}日"

    with _cache_lock:
        now = time.time()
        if _macro_cache["data"] and (now - _macro_cache["last_update"] < CACHE_TTL):
            print("[Macro Data] Using cache")
            return _macro_cache["data"]

    results = {"cpi": "需查詢", "export": "需查詢", "pmi": "需查詢", "signal": "需查詢"}

    def fetch_cpi():
        # 強制抓取最近 30 天新聞
        headlines = _fetch_rss_headlines("美國 CPI 年增率 when:30d")
        val = _extract_number_from_headlines(headlines, [
            r'年增[率]?\s*([\d.]+\s*%)',
            r'CPI[^\d]*([\d.]+\s*%)',
            r'([\d.]+)\s*%.*CPI',
        ])
        if val: return val
        try:
            news_text = "\n".join(f"[{d}] {t}" for d, t in headlines[:5])
            model = get_model()
            r = model.generate_content(f"{time_ctx}。從以下最近 30 天內的新聞找出【最新一期】美國 CPI 年增率。直接回傳數字如 3.2%，不可回傳舊資料，沒有就回傳空白：\n{news_text}", 
                                     generation_config={"timeout": 5})
            v = r.text.strip()
            if re.search(r'[\d.]+\s*%', v): return v
        except: pass
        return "需查詢"

    def fetch_pmi():
        # 強制抓取最近 30 天新聞
        headlines = _fetch_rss_headlines("美國 ISM 製造業 PMI when:30d")
        val = _extract_number_from_headlines(headlines, [
            r'PMI[^\d]*([\d.]+)',
            r'([\d.]+)[^\d]*PMI',
            r'製造業[^\d]*([\d.]+)',
        ])
        if val: return val
        try:
            news_text = "\n".join(f"[{d}] {t}" for d, t in headlines[:5])
            model = get_model()
            r = model.generate_content(f"{time_ctx}。從以下最近 30 天新聞找出美國【最新一期】ISM 製造業 PMI。只輸出數字，找不到就回傳空白：\n{news_text}",
                                     generation_config={"timeout": 5})
            v = r.text.strip()[:10]
            m = re.search(r'[\d.]+', v)
            if m: return m.group(0)
        except: pass
        return "需查詢"

    def fetch_export():
        # 強制抓取最近 30 天新聞
        headlines = _fetch_rss_headlines("台灣 外銷訂單 年增率 when:30d")
        val = _extract_number_from_headlines(headlines, [
            r'年[增减減][率]?\s*([\+\-]?[\d.]+\s*%)',
            r'([\+\-]?[\d.]+\s*%).*外銷',
            r'外銷[^\d]*([\d.]+\s*%)',
        ])
        if val: return val
        try:
            news_text = "\n".join(f"[{d}] {t}" for d, t in headlines[:5])
            model = get_model()
            r = model.generate_content(f"{time_ctx}。從以下最近 30 天新聞找出台灣【最新一期】外銷訂單年增率。直接回傳如 +5.2% 或 -1.3%，不要舊資訊，沒有就回傳空白：\n{news_text}",
                                     generation_config={"timeout": 5})
            v = r.text.strip()
            if re.search(r'[\d.]+\s*%', v): return v
        except: pass
        return "需查詢"

    def fetch_signal():
        # 強制抓取最近 30 天新聞：台灣景氣燈號通常每月底公佈上個月數據，所以抓 30 天內一定有最新資料
        headlines = _fetch_rss_headlines("台灣 景氣燈號 分數 when:30d")
        val = _extract_number_from_headlines(headlines, [
            r'((?:紅|黃紅|黃|綠|藍|低迷|熱絡)[燈])[^\d]{0,10}(\d+)[\s分]',
            r'(\d+)[\s分].*?((?:紅|黃紅|黃|綠|藍)[燈])',
        ])
        if val: return val
        
        # 額外針對 AI 的標題檢查，移除可能包含舊年份或月份的標題
        for _, title in headlines[:8]:
            m = re.search(r'((?:紅|黃紅|黃|綠|藍)燈)[^0-9]{0,15}([0-9]+)[分分]', title)
            if m: return f"{m.group(1)} {m.group(2)}分"
            m2 = re.search(r'([0-9]+)[分分][^0-9]{0,5}((?:紅|黃紅|黃|綠|藍)燈)', title)
            if m2: return f"{m2.group(2)} {m2.group(1)}分"
        try:
            news_text = "\n".join(f"[{d}] {t}" for d, t in headlines[:5])
            model = get_model()
            # 增加明確的指令避免 AI 引用舊月份
            r = model.generate_content(
                f"{time_ctx}。從以下最近 30 天新聞找出【台灣最新一期】景氣燈號與分數。只回傳燈號與分數(如: 紅燈38分)，"
                f"不可提到過期月份(如: 12月)。若新聞提到多個月分，請取最新的一個，若沒把握就只回傳燈號分數，不要月份。沒有就空白：\n{news_text}",
                generation_config={"timeout": 5}
            )
            v = r.text.strip()
            if v: return v
        except: pass
        return "需查詢"

    # 定義清理函式
    def clean_val(v):
        if not v or "需查詢" in v: return "需查詢"
        # 移除標點與多餘空白
        return v.replace("\n", "").strip()

    # 使用併行執行
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_cpi = executor.submit(fetch_cpi)
        future_pmi = executor.submit(fetch_pmi)
        future_export = executor.submit(fetch_export)
        future_signal = executor.submit(fetch_signal)
        
        results["cpi"] = clean_val(future_cpi.result())
        results["pmi"] = clean_val(future_pmi.result())
        results["export"] = clean_val(future_export.result())
        results["signal"] = clean_val(future_signal.result())

    with _cache_lock:
        _macro_cache["data"] = results
        _macro_cache["last_update"] = time.time()

    print(f"[Macro Data] Fetched: {results}")
    return results



def get_fx_data(market_name: str) -> str:
    """
    抓取區域報告所需的匯率 (USDTWD, JPY, HKD)
    """
    try:
        if "TAIEX" in market_name or "TW" in market_name: 
            pair = "USDTWD=X"
        elif "Nikkei" in market_name or "JP" in market_name: 
            pair = "JPY=X"
        elif "HK" in market_name: 
            pair = "HKD=X"
        else: 
            return "USD Index (DXY)"
            
        ticker = yf.Ticker(pair)
        hist = ticker.history(period="5d")
        if not hist.empty:
            rate = hist['Close'].iloc[-1]
            return f"{pair}: {rate:.2f}"
        return "N/A"
    except:
        return "N/A"

# ==========================================
# 3. 新聞爬蟲 (News)
# ==========================================
def get_investing_news(market_name: str) -> str:
    """
    大幅優化：捨棄緩慢的 Selenium，改用 Google News RSS 獲取全球市場新聞。
    """
    query = f"{market_name} market news"
    if "TW" in market_name:
        query = f"{market_name} 股市新聞"
        
    headlines = _fetch_rss_headlines(query, max_items=5)
    if not headlines:
        return "暫時無法獲取即時新聞。"
    
    return "\n".join(f"- [{d}] {t}" for d, t in headlines)

# ==========================================
# 4. AI 報告
# ==========================================
def generate_global_report(market: str, metrics: str, macro: str, fx: str, commodities: str, news: str) -> str:
    """
    綜合宏觀數據生成報告 (非串流版)
    """
    model = get_model()
    prompt = prompts.get_global_report_prompt(market, metrics, macro, fx, commodities, news)
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI Report Failed: {e}"

def stream_generate_global_report(market: str, metrics: str, macro: str, fx: str, commodities: str, news: str) -> Any:
    """
    串流綜合宏觀數據生成報告
    """
    model = get_model()
    prompt = prompts.get_global_report_prompt(market, metrics, macro, fx, commodities, news)
    
    def _generator():
        try:
            for chunk in model.generate_content(prompt, stream=True):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            yield f"AI Report Failed: {e}"
    return _generator()

def chat_with_global_analyst(user_msg: str, report_context: str, chat_history: List[Dict]) -> str:
    """
    與全球宏觀策略師進行對談 (非串流版)
    """
    model = get_model()
    history = []
    for m in chat_history[-10:]:
        history.append({"role": "user" if m["role"] == "user" else "model", "parts": [m["content"]]})
    
    chat = model.start_chat(history=history)
    prompt = f"""
    你是剛才撰寫這份報告的「全球宏觀策略師」。
    初始報告內容如下作為背景：
    {report_context}
    
    請針對使用者的問題進行專業、客觀且具備洞察力的回答。若問題涉及特定的投資建議，請維持中立並強調風險。
    使用繁體中文回答。
    
    使用者問題：{user_msg}
    """
    try:
        response = chat.send_message(prompt)
        return response.text
    except Exception as e:
        return f"對談出錯: {e}"

def stream_chat_with_global_analyst(user_msg: str, report_context: str, chat_history: List[Dict]) -> Any:
    """
    與全球宏觀策略師進行串流對談
    """
    model = get_model()
    history_text = ""
    for m in chat_history[-10:]:
        role = "用戶" if m["role"] == "user" else "策略師"
        history_text += f"{role}: {m['content']}\n\n"
    
    prompt = f"""
    你是撰寫報告的「全球宏觀策略師」。
    初始報告背景：{report_context}
    對話歷史：{history_text}
    
    請針對使用者的問題進行專業回答。繁體中文。
    使用者問題：{user_msg}
    """
    
    def _generator():
        try:
            for chunk in model.generate_content(prompt, stream=True):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            yield f"對談出錯: {e}"
    return _generator()
