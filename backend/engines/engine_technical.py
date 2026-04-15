# engine_technical.py
import os
import yfinance as yf
import pandas as pd
import numpy as np
import google.generativeai as genai
import streamlit as st
from typing import Tuple, List, Dict, Optional, Any
from . import prompts
from .sinopac_snapshots import merge_sinopac_change_pct_into_rows
import pandas_ta as ta

# 常用權值股中文名稱對照表 (當 yfinance 抓不到中文時的備案)
TW_NAMES = {
    "2330.TW": "台積電", "2317.TW": "鴻海", "2454.TW": "聯發科", 
    "2603.TW": "長榮", "2609.TW": "陽明", "2615.TW": "萬海",
    "2303.TW": "聯電", "2881.TW": "富邦金", "2882.TW": "國泰金",
    "2412.TW": "中華電", "2308.TW": "台達電", "6669.TW": "緯穎",
    "3037.TW": "欣興", "2337.TW": "旺宏", "2301.TW": "光寶科",
    "2357.TW": "華碩", "2382.TW": "廣達", "3231.TW": "緯創",
    "2376.TW": "技嘉", "2377.TW": "微星", "2610.TW": "華航",
    "2618.TW": "長榮航", "2834.TW": "臺企銀", "2884.TW": "玉山金",
    "2886.TW": "兆豐金"
}

# ==========================================
# 設定 Gemini API Key
# ==========================================
# 使用 os.getenv 讀取環境變數
# 使用 os.environ.get 讀取環境變數
# GEMINI_API_KEY is configured in main_app.py

def fetch_data(stock_id: str, period: str = "1y") -> Optional[pd.DataFrame]:
    """
    抓取股價並進行資料清洗
    """
    # 處理台股代碼後綴
    stock_id = str(stock_id).strip()
    symbols_to_try = []
    
    if stock_id.isdigit():
        symbols_to_try = [f"{stock_id}.TW", f"{stock_id}.TWO"]
    elif not stock_id.endswith(".TW") and not stock_id.endswith(".TWO"):
        symbols_to_try = [f"{stock_id}.TW", f"{stock_id}.TWO"]
    else:
        symbols_to_try = [stock_id]
        
    df = None
    final_symbol = symbols_to_try[0]
    
    for sym in symbols_to_try:
        try:
            print(f"正在嘗試抓取 {sym}...")
            df = yf.download(sym, period=period, progress=False, auto_adjust=False)
            if df is not None and not df.empty:
                final_symbol = sym
                break
        except Exception as e:
            print(f"嘗試 {sym} 失敗: {e}")
            continue
    
    if df is None or df.empty:
        return None
        
    # 處理 MultiIndex (yfinance 新版問題)
    if isinstance(df.columns, pd.MultiIndex):
        try:
            # 嘗試直接降維，若只有單一 Ticker，level 1 通常是 Ticker 名稱
            if symbol in df.columns.get_level_values(1):
                df = df.xs(symbol, axis=1, level=1)
            else:
                df.columns = df.columns.get_level_values(0)
        except:
             df.columns = df.columns.get_level_values(0)
    
    # 強制將索引轉為 Datetime 並移除時區資訊 (避免後續繪圖問題)
    if isinstance(df.index, pd.DatetimeIndex):
         df.index = df.index.tz_localize(None)
    else:
         df.index = pd.to_datetime(df.index).tz_localize(None)
    
    # ✅ 關鍵修正：檢查必要欄位是否存在
    # Standardize columns to simplify check
    df.columns = [c.capitalize() for c in df.columns]
    
    required_cols = ['Close', 'Open', 'High', 'Low'] 
    # Volume sometimes is missing in indices, we can handle it
    
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        print(f"缺少必要欄位: {missing_cols}")
        return None

    # 移除任何含有 NaN 的列 (確保沒有空數據日)
    df.dropna(subset=required_cols, inplace=True)
    
    if df.empty:
        return None
        
    return df

def get_symbol_name(stock_id: str) -> str:
    """ 嘗試獲取股票名稱 """
    try:
        stock_id = str(stock_id).strip()
        symbols = [f"{stock_id}.TW", f"{stock_id}.TWO"] if stock_id.isdigit() else [stock_id]
        
        for sym in symbols:
            ticker = yf.Ticker(sym)
            try:
                # 嘗試從特定欄位獲取名稱
                info = ticker.info
                name = info.get('longName') or info.get('shortName')
                if name:
                    return name
            except:
                continue
        return ""
    except:
        return ""

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    計算技術指標：MA(5,10,20,60), BB(20,2), MACD, RSI, OBV
    """
    data = df.copy()
    
    # 1. 均線 (MA)
    data['MA5'] = data['Close'].rolling(window=5).mean()
    data['MA10'] = data['Close'].rolling(window=10).mean()
    data['MA20'] = data['Close'].rolling(window=20).mean() # 月線
    data['MA60'] = data['Close'].rolling(window=60).mean() # 季線
    
    # 2. 乖離率 (Bias)
    data['Bias_20'] = ((data['Close'] - data['MA20']) / data['MA20']) * 100
    
    # 3. 布林通道 (Bollinger Bands) - 20MA 為中軌
    std20 = data['Close'].rolling(window=20).std()
    data['BB_Upper'] = data['MA20'] + (std20 * 2)
    data['BB_Lower'] = data['MA20'] - (std20 * 2)
    data['BB_Width'] = (data['BB_Upper'] - data['BB_Lower']) / data['MA20']
    
    # 4. MACD (12, 26, 9)
    exp12 = data['Close'].ewm(span=12, adjust=False).mean()
    exp26 = data['Close'].ewm(span=26, adjust=False).mean()
    data['MACD'] = exp12 - exp26
    data['Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
    data['Hist'] = data['MACD'] - data['Signal']
    
    # 5. RSI (14日)
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))
    
    # 6. OBV (能量潮) - Check if Volume exists
    if 'Volume' in data.columns:
        data['Price_Change'] = data['Close'].diff()
        data['Direction'] = np.where(data['Price_Change'] > 0, 1, 
                                     np.where(data['Price_Change'] < 0, -1, 0))
        data['Direction'] = data['Direction'].fillna(0) # type: ignore
        data['OBV'] = (data['Volume'] * data['Direction']).cumsum()
        data.drop(['Price_Change', 'Direction'], axis=1, inplace=True)
    else:
        # If no volume, fill OBV with 0 or NaN
        data['OBV'] = 0.0
        # Also ensure Volume column exists for plotting
        data['Volume'] = 0.0

    # 7. KD 指標 (9, 3, 3)
    low_9 = data['Low'].rolling(window=9).min()
    high_9 = data['High'].rolling(window=9).max()
    rsv = ((data['Close'] - low_9) / (high_9 - low_9)) * 100
    
    # 初始化 K, D 為 50
    k = 50.0
    d = 50.0
    k_list = []
    d_list = []
    
    for val in rsv:
        if pd.isna(val):
            k_list.append(np.nan)
            d_list.append(np.nan)
        else:
            k = (2/3) * k + (1/3) * val
            d = (2/3) * d + (1/3) * k
            k_list.append(k)
            d_list.append(d)
            
    data['K'] = k_list
    data['D'] = d_list
    
    # 8. 相對強度 RS (Relative Strength) vs TAIEX (^TWII)
    try:
        # 抓取大盤數據
        twii = yf.download("^TWII", start=data.index[0], end=data.index[-1] + pd.Timedelta(days=1), progress=False)
        if isinstance(twii.columns, pd.MultiIndex):
            twii.columns = twii.columns.get_level_values(0)
        
        # 對齊日期
        idx_close = twii['Close'].reindex(data.index).ffill()
        
        # 計算 RS 線 (以第一天為 100 作為基準以便觀察強度變化)
        ratio = data['Close'] / idx_close
        first_valid_ratio = ratio.dropna().iloc[0] if not ratio.dropna().empty else 1
        data['RS'] = (ratio / first_valid_ratio) * 100
        data['RS_MA20'] = data['RS'].rolling(window=20).mean()
    except Exception as e:
        print(f"RS 計算失敗: {e}")
        data['RS'] = 0.0
        data['RS_MA20'] = 0.0

    return data

def get_latest_summary(df: pd.DataFrame) -> Dict[str, Any]:
    """
    提取最後一筆資料供 AI 使用
    """
    last = df.iloc[-1]
    
    summary = {
        "Date": str(last.name.date()),
        "Close": round(last['Close'], 2),
        "MA5": round(last['MA5'], 2),
        "MA20": round(last['MA20'], 2),
        "RSI": round(last['RSI'], 2),
        "K": round(last['K'], 2) if 'K' in last else "N/A",
        "D": round(last['D'], 2) if 'D' in last else "N/A",
        "MACD_Hist": round(last['Hist'], 2),
        "RS": round(last['RS'], 2) if 'RS' in last else "N/A",
        "BB_Status": "Upper Band" if last['Close'] > last['BB_Upper'] else ("Lower Band" if last['Close'] < last['BB_Lower'] else "Normal")
    }
    return summary

def stream_initial_analysis(df: pd.DataFrame, symbol: str) -> Any:
    """
    串流產生第一輪的技術分析
    回傳: generator (供 st.write_stream 使用)
    """
    cols = ['Close', 'Volume', 'MA5', 'MA20', 'MACD', 'Hist', 'RSI', 'BB_Width']
    available_cols = [c for c in cols if c in df.columns]
    data_for_ai = df.tail(5)[available_cols].to_markdown()
    
    system_instruction = prompts.get_technical_analysis_prompt(symbol, data_for_ai)
    model_id = os.getenv("GEMINI_MODEL_ID", "gemini-1.5-flash") # 優先讀取 .env
    model = genai.GenerativeModel(model_id)
    prompt = f"{system_instruction}\n\n請開始你的技術分析："

    def _generator():
        try:
            for chunk in model.generate_content(prompt, stream=True):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            yield f"AI 分析失敗：{e}"
    
    return _generator()

def continue_chat(user_input: str, history: List[Dict[str, str]]) -> Tuple[str, List[Dict[str, str]]]:
    """
    延續對話 (Stateless 模式)
    history: List of dicts [{'role': 'user'|'model', 'content': text}, ...]
    """
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        
        # 建構包含歷史紀錄的 Prompt
        conversation_context = ""
        for msg in history:
            role_name = "User" if msg['role'] == "user" else "AI Analyst"
            conversation_context += f"{role_name}: {msg['content']}\n\n"
            
        final_prompt = prompts.get_technical_chat_prompt(conversation_context, user_input)
        
        response = model.generate_content(final_prompt)
        
        # 更新歷史紀錄
        new_history = history + [
            {"role": "user", "content": user_input},
            {"role": "model", "content": response.text}
        ]
        
        return response.text, new_history
    except Exception as e:
        return f"Error: {e}", history

class BollingerStrategy:
    @staticmethod
    def calculate_indicators(df):
        if df is None:
            return None
        if df.empty or len(df) < 20:
            return df
            
        df = df.copy()
        try:
            # 基本均線
            df['MA5'] = ta.sma(df['Close'], length=5)
            df['MA10'] = ta.sma(df['Close'], length=10)
            df['MA20'] = ta.sma(df['Close'], length=20)
            df['MA60'] = ta.sma(df['Close'], length=60)
            df['MA120'] = ta.sma(df['Close'], length=120)
            
            bbands = ta.bbands(df['Close'], length=20, std=2)
            if bbands is not None and not bbands.empty:
                upper_col = [c for c in bbands.columns if 'BBU' in c][0]
                mid_col = [c for c in bbands.columns if 'BBM' in c][0]
                lower_col = [c for c in bbands.columns if 'BBL' in c][0]
                
                df['Upper'] = bbands[upper_col]
                df['Lower'] = bbands[lower_col]
                
                df['Bandwidth_Pct'] = (df['Upper'] - df['Lower']) / df['MA20'] * 100
                df['Volume_MA5'] = ta.sma(df['Volume'], length=5)
            else:
                for col in ['Upper', 'Lower', 'Bandwidth_Pct', 'Volume_MA5']:
                    df[col] = np.nan
        except Exception:
            for col in ['Upper', 'Lower', 'Bandwidth_Pct', 'Volume_MA5', 'MA5', 'MA10', 'MA20', 'MA60', 'MA120']:
                df[col] = np.nan
        return df

    @classmethod
    def analyze(cls, df, upper_slope_threshold=0.003, vol_surge_multiplier=1.5):
        df = cls.calculate_indicators(df)
        
        required_cols = ['Upper', 'Lower', 'MA20', 'Bandwidth_Pct', 'Volume_MA5']
        if df is None or not all(col in df.columns for col in required_cols) or len(df) < 2:
            return False, {}, df
            
        today = df.iloc[-1]
        yesterday = df.iloc[-2]
        
        if pd.isna(today['Upper']) or pd.isna(yesterday['Upper']):
            return False, {}, df
        
        today_bw = today['Bandwidth_Pct']
        yesterday_bw = yesterday['Bandwidth_Pct']
        bw_change = (today_bw - yesterday_bw) / yesterday_bw * 100 if yesterday_bw != 0 else 0
        
        upper_slope_raw = (today['Upper'] - yesterday['Upper']) / yesterday['Upper'] if yesterday['Upper'] != 0 else 0
        upper_slope_pct = upper_slope_raw * 100
        lower_slope_raw = (today['Lower'] - yesterday['Lower']) / yesterday['Lower'] if yesterday['Lower'] != 0 else 0
        
        # 1. 通道擴張的條件：布林上軌斜率>0 下軌斜率<0
        cond_a = (upper_slope_raw > 0) and (lower_slope_raw < 0)
        
        cond_b = upper_slope_raw > upper_slope_threshold
        
        # 月線斜率
        ma20_slope_raw = (today['MA20'] - yesterday['MA20']) / yesterday['MA20'] if yesterday['MA20'] != 0 else 0
        ma20_slope_pct = ma20_slope_raw * 100

        is_red = today['Close'] > today['Open']
        vol_ratio = today['Volume'] / today['Volume_MA5'] if today['Volume_MA5'] > 0 else 0
        is_vol_surge = vol_ratio > vol_surge_multiplier
        
        pos_upper = (today['Close'] / today['Upper']) * 100
        is_touching = pos_upper >= 99.0
        
        cond_c = is_red and is_touching and is_vol_surge
        
        # 4. 均線多排檢查 (MA5 > MA10 > MA20 > MA60)
        # 需確保均線值都存在 (非 NaN)
        has_mas = all(not pd.isna(today[col]) for col in ['MA5', 'MA10', 'MA20', 'MA60'])
        if has_mas:
            cond_d = (today['MA5'] > today['MA10']) and \
                     (today['MA10'] > today['MA20']) and \
                     (today['MA20'] > today['MA60'])
        else:
            cond_d = False
        
        # 2. 只有通道擴張 (cond_a) 為必要條件，均線多排 (cond_d) 改為選配
        is_match = cond_a
        
        quant_data = {
            "Match": is_match,
            "Close": today['Close'],
            "Bandwidth_Pct": round(today_bw, 1),
            "Bandwidth_Chg": round(bw_change, 1),
            "Upper_Slope_Pct": round(upper_slope_pct, 2),
            "MA20_Slope_Pct": round(ma20_slope_pct, 2),
            "Vol_Ratio": round(vol_ratio, 1),
            "Pos_Upper": round(pos_upper, 1),
            "Is_Red": is_red,
            "Details": {
               "cond_a": cond_a, "cond_b": cond_b, "cond_c": cond_c, "cond_d": cond_d
            }
        }
        return is_match, quant_data, df

    @classmethod
    def get_chip_metrics(cls, stock_id: str):
        """
        取得該股票的最新集保數據與變動
        """
        import sqlite3
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        chip_db_path = os.path.join(project_root, "databases", "db_chips_ownership.db")
        if not os.path.exists(chip_db_path):
            return None
        
        try:
            conn = sqlite3.connect(chip_db_path)
            # 抓取最近兩週數據來比較
            df = pd.read_sql(
                f"SELECT date, retail_pct, whale_1000_pct FROM tdcc_dist WHERE stock_id='{stock_id}' ORDER BY date DESC LIMIT 2",
                conn
            )
            conn.close()
            
            if len(df) < 2:
                return None
            
            latest = df.iloc[0]
            prev = df.iloc[1]
            
            retail_diff = latest['retail_pct'] - prev['retail_pct']
            whale_diff = latest['whale_1000_pct'] - prev['whale_1000_pct']
            
            return {
                "retail_chg": round(retail_diff, 2),
                "whale_chg": round(whale_diff, 2),
                "is_retail_up": retail_diff > 0,
                "is_whale_down": whale_diff < 0
            }
        except Exception:
            return None

    @classmethod
    def analyze_short(cls, df):
        """
        波段空方策略 (趨勢轉空 + 沿下軌佈局):
        條件一: 趨勢轉空 — MA5 < MA10 < MA20 且月線斜率 < 0
        條件二: 沿布林下軌開單 — 價格在下軌與中軌之間，且較靠近下軌
                (position_ratio = (Close - Lower) / (Middle - Lower) < 0.4)
        """
        df = cls.calculate_indicators(df)
        
        required_cols = ['MA5', 'MA10', 'MA20', 'MA60', 'MA120', 'Upper', 'Lower']
        if df is None or not all(col in df.columns for col in required_cols) or len(df) < 2:
            return False, {}, df
            
        today = df.iloc[-1]
        yesterday = df.iloc[-2]
        
        # --- 條件一: 趨勢轉空 ---
        # 均線空頭排列: MA5 < MA10 < MA20
        cond_ma_bearish = (today['MA5'] < today['MA10']) and (today['MA10'] < today['MA20'])
        # 月線下彎: MA20 斜率 < 0
        ma20_slope = (today['MA20'] - yesterday['MA20']) / yesterday['MA20'] if yesterday['MA20'] != 0 else 0
        cond_ma20_down = ma20_slope < 0
        # 趨勢條件 = 空頭排列 + 月線下彎
        cond_trend = cond_ma_bearish and cond_ma20_down
        
        # --- 條件二: 沿布林下軌佈局 ---
        # 中軌 = MA20, 價格需介於 Lower 與 MA20 之間，且靠近 Lower
        bb_middle = today['MA20']
        bb_lower = today['Lower']
        bb_upper = today['Upper']
        bb_width = bb_middle - bb_lower  # 中軌到下軌的距離
        
        if bb_width > 0:
            # position_ratio: 0 = 在下軌上, 1 = 在中軌上; < 0.4 代表靠近下軌
            position_ratio = (today['Close'] - bb_lower) / bb_width
            cond_near_lower = (0 <= position_ratio <= 0.4)
        else:
            position_ratio = np.nan
            cond_near_lower = False
        
        # --- 最終判定: 只看趨勢轉空 (布林位置僅供參考) ---
        is_match = cond_trend
        
        # --- 附帶資訊: 乖離率 ---
        # --- 附帶資訊: 乖離率 ---
        ma60_val = today.get('MA60', 0)
        ma60_bias = (today['Close'] - ma60_val) / ma60_val * 100 if ma60_val > 0 else 0
        ma120_val = today.get('MA120', 0)
        ma120_bias = (today['Close'] - ma120_val) / ma120_val * 100 if ma120_val > 0 else 0
        
        quant_data = {
            "Match": is_match,
            "Close": today['Close'],
            "MA5": round(today['MA5'], 2),
            "MA10": round(today['MA10'], 2),
            "MA20": round(today['MA20'], 2),
            "MA20_Slope": round(ma20_slope * 100, 4),  # 百分比顯示
            "BB_Upper": round(bb_upper, 2),
            "BB_Lower": round(bb_lower, 2),
            "BB_Position_Ratio": round(position_ratio, 3) if not np.isnan(position_ratio) else None,
            "MA60_Bias": round(ma60_bias, 2),
            "MA120_Bias": round(ma120_bias, 2),
            "Details": {
               "cond_trend_bearish": cond_ma_bearish,   # MA5<MA10<MA20
               "cond_ma20_slope_down": cond_ma20_down,   # 月線下彎
               "cond_near_lower_band": cond_near_lower,  # 靠近布林下軌
               "position_ratio": round(position_ratio, 3) if not np.isnan(position_ratio) else None,
            }
        }
        return is_match, quant_data, df

    @classmethod
    def screen_from_db(
        cls,
        strategy: str = "long",
        slope_val: float = 0.003,
        vol_mul: float = 1.5,
        # 新增選配過濾條件 (由前端勾選決定)
        req_ma: bool = True,
        req_vol: bool = True,
        req_slope: bool = True,
        req_chips: bool = True,
        req_near_band: bool = True,
        progress_callback=None
    ) -> Tuple[List[Dict], Dict[str, Dict]]:
        """
        從資料庫海選股票，並套用動態過濾條件。
        """
        import sqlite3
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_path = os.path.join(project_root, "databases", "db_technical_prices.db")
        
        if not os.path.exists(db_path):
            return [], {}

        conn = sqlite3.connect(db_path)
        stock_info = pd.read_sql("SELECT stock_id, name, market_type FROM stock_info", conn)
        
        def is_eligible(sid, sname):
            if any(c.isalpha() for c in sid):
                if not (len(sid) == 6 and sid.endswith('A') and sid[:-1].isdigit()): return False
            if sname:
                if "正2" in sname or "反1" in sname: return False
                if "-DR" in sname: return False
            return True

        stock_info = stock_info[stock_info.apply(lambda x: is_eligible(x['stock_id'], x['name']), axis=1)]
        
        total = len(stock_info)
        results_list = []
        details_map = {}
        min_rows = 120 if strategy == "short" else 60
        
        global_max_date = pd.read_sql("SELECT MAX(date) FROM daily_price", conn).iloc[0, 0]
        max_date_limit = pd.to_datetime(global_max_date) - pd.Timedelta(days=5) if global_max_date else None

        for idx, row in stock_info.iterrows():
            stock_id = row["stock_id"]
            name = row["name"] or ""
            market = row.get("market_type", "")

            if progress_callback: progress_callback(idx + 1, total, f"{stock_id} {name}")

            df = pd.read_sql(f"SELECT date, open, high, low, close, volume FROM daily_price WHERE stock_id='{stock_id}' ORDER BY date ASC", conn)
            if df.empty or len(df) < min_rows: continue

            df.columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
            df["Date"] = pd.to_datetime(df["Date"])
            if max_date_limit and df["Date"].iloc[-1] < max_date_limit: continue

            try:
                if strategy == "long":
                    _, q_data, full_df = cls.analyze(df, slope_val, vol_mul)
                    # 1. 通道擴張 (核心必要條件)
                    if not q_data["Details"]["cond_a"]: continue
                    # 2. 上軌斜率 (選配)
                    if req_slope and not q_data["Details"]["cond_b"]: continue
                    # 3. 爆量表態 (選配)
                    if req_vol and not q_data["Details"]["cond_c"]: continue
                    # 4. 均線多排 (選配)
                    if req_ma and not q_data["Details"]["cond_d"]: continue
                    match = True
                else:
                    _, q_data, full_df = cls.analyze_short(df)
                    # 1. 均線空排 (選配)
                    if req_ma and not q_data["Details"]["cond_trend_bearish"]: continue
                    # 2. 月線下彎 (選配)
                    if req_slope and not q_data["Details"]["cond_ma20_slope_down"]: continue
                    # 3. 沿下軌 (選配)
                    if req_near_band and not q_data["Details"]["cond_near_lower_band"]: continue
                    match = True
            except Exception:
                continue

            # --- 籌碼過濾 (僅空方策略選配) ---
            chip_info = cls.get_chip_metrics(stock_id)
            chip_cond = "-"
            if chip_info:
                chip_cond = "🔥" if (chip_info["is_whale_down"] and chip_info["is_retail_up"]) else "ok"

            if strategy == "short":
                if req_chips and chip_cond != "🔥": continue

            # 計算今日漲跌幅
            today_close = full_df.iloc[-1]['Close']
            yes_close = full_df.iloc[-2]['Close'] if len(full_df) >= 2 else today_close
            change_pct = round((today_close - yes_close) / yes_close * 100, 2) if yes_close > 0 else 0

            # 取得資料日期 (最後一筆 K 棒的日期)
            data_date = pd.to_datetime(full_df.iloc[-1]['Date']).strftime('%Y-%m-%d') if 'Date' in full_df.columns else ''

            # 取得產業分類
            try:
                import twstock
                tw_codes = twstock.codes
                industry = getattr(tw_codes.get(stock_id), "group", "其他") if tw_codes.get(stock_id) else "其他"
            except:
                industry = "其他"

            # 組裝結果 (多方 / 空方欄位不同)
            suffix = ".TW" if market == "上市" else ".TWO"
            real_ticker = f"{stock_id}{suffix}"

            if strategy == "long":
                result_row = {
                    "代號": stock_id,
                    "名稱": name,
                    "產業": industry,
                    "收盤價": q_data["Close"],
                    "今日漲跌幅(%)": change_pct,
                    "成交量(張)": int(full_df.iloc[-1]['Volume'] / 1000) if 'Volume' in full_df.columns else 0,
                    "成交額(億)": round((full_df.iloc[-1]['Close'] * full_df.iloc[-1]['Volume']) / 1e8, 2) if all(k in full_df.columns for k in ['Close', 'Volume']) else 0,
                    "均線多排": "V" if q_data["Details"]["cond_d"] else "-",
                    "爆量表態": "V" if q_data["Details"]["cond_c"] else "-",
                    "月線斜率": q_data["MA20_Slope_Pct"],
                    "上軌斜率": q_data["Upper_Slope_Pct"],
                    "帶寬增長(%)": q_data["Bandwidth_Chg"],
                    "量比": q_data["Vol_Ratio"],
                    "資料日期": data_date,
                    "上軌乖離(%)": q_data["Pos_Upper"],
                    "_ticker": real_ticker,
                    "_name": name,
                }
            else:
                result_row = {
                    "代號": stock_id,
                    "名稱": name,
                    "產業": industry,
                    "收盤價": q_data["Close"],
                    "今日漲跌幅(%)": change_pct,
                    "成交量(張)": int(full_df.iloc[-1]['Volume'] / 1000) if 'Volume' in full_df.columns else 0,
                    "成交額(億)": round((full_df.iloc[-1]['Close'] * full_df.iloc[-1]['Volume']) / 1e8, 2) if all(k in full_df.columns for k in ['Close', 'Volume']) else 0,
                    "空頭排列": "V" if q_data["Details"]["cond_trend_bearish"] else "-",
                    "月線下彎": "V" if q_data["Details"]["cond_ma20_slope_down"] else "-",
                    "籌碼渙散": chip_cond,
                    "沿下軌": "V" if q_data["Details"]["cond_near_lower_band"] else "-",
                    "大戶變動": chip_info["whale_chg"] if chip_info else 0,
                    "散戶變動": chip_info["retail_chg"] if chip_info else 0,
                    "月線斜率": q_data["MA20_Slope"],
                    "資料日期": data_date,
                    "布林位置": q_data["BB_Position_Ratio"],
                    "季線乖離": q_data["MA60_Bias"],
                    "半年線乖離": q_data["MA120_Bias"],
                    "_ticker": real_ticker,
                    "_name": name,
                }

            results_list.append(result_row)
            details_map[real_ticker] = {
                "q_data": q_data,
                "df": full_df,
                "pure_id": stock_id,
                "name": name,
                "industry": industry
            }

        conn.close()
        merge_sinopac_change_pct_into_rows(results_list)
        return results_list, details_map

    @classmethod
    def analyze_wanderer(cls, df):
        """
        浪子回頭策略:
        條件一: 月線斜率 > 0.8% (今日MA20 - 昨日MA20) / 昨日MA20 > 0.008
        條件二: 布林位階 < 4
            計算方式: 以上軌為+10, 中軌為0, 下軌為-10 線性映射
            若 Close 在中軌以上 -> 位階 = (Close - Middle) / (Upper - Middle) * 10
            若 Close 在中軌以下 -> 位階 = (Close - Middle) / (Middle - Lower) * 10  (為負值)
            位階 < 4 表示收盤價尚未接近上軌區間
        """
        df = cls.calculate_indicators(df)

        required_cols = ['MA20', 'Upper', 'Lower']
        if df is None or not all(col in df.columns for col in required_cols) or len(df) < 2:
            return False, {}, df

        today = df.iloc[-1]
        yesterday = df.iloc[-2]

        if pd.isna(today['MA20']) or pd.isna(yesterday['MA20']) or pd.isna(today['Upper']) or pd.isna(today['Lower']):
            return False, {}, df

        # 條件一: 月線斜率 > 0.8%
        ma20_slope_raw = (today['MA20'] - yesterday['MA20']) / yesterday['MA20'] if yesterday['MA20'] != 0 else 0
        ma20_slope_pct = ma20_slope_raw * 100
        cond_slope = ma20_slope_pct > 0.8

        # 條件二: 布林位階 < 4
        bb_upper = today['Upper']
        bb_lower = today['Lower']
        bb_middle = today['MA20']
        close = today['Close']

        upper_half = bb_upper - bb_middle  # 中軌到上軌距離
        lower_half = bb_middle - bb_lower  # 中軌到下軌距離

        if close >= bb_middle and upper_half > 0:
            bb_position = (close - bb_middle) / upper_half * 10  # 0 ~ +10
        elif close < bb_middle and lower_half > 0:
            bb_position = (close - bb_middle) / lower_half * 10  # 0 ~ -10 (負值)
        else:
            bb_position = 0.0

        cond_bb_level = bb_position < 4.0

        is_match = cond_slope and cond_bb_level

        quant_data = {
            'Match': is_match,
            'Close': today['Close'],
            'MA20_Slope_Pct': round(ma20_slope_pct, 4),
            'BB_Position': round(bb_position, 2),
            'BB_Upper': round(bb_upper, 2),
            'BB_Middle': round(bb_middle, 2),
            'BB_Lower': round(bb_lower, 2),
            'Details': {
                'cond_slope': cond_slope,        # 月線斜率 > 0.8%
                'cond_bb_level': cond_bb_level,  # 布林位階 < 4
            }
        }
        return is_match, quant_data, df

    @classmethod
    def screen_wanderer_from_db(
        cls,
        ma20_slope_threshold: float = 0.8,
        bb_level_threshold: float = 4.0,
        req_slope: bool = True,
        req_bb_level: bool = True,
        progress_callback=None
    ) -> Tuple[List[Dict], Dict[str, Dict]]:
        """
        浪子回頭策略海選，支援動態參數過濾。
        """
        import sqlite3
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_path = os.path.join(project_root, 'databases', 'db_technical_prices.db')
        
        if not os.path.exists(db_path):
            return [], {}

        conn = sqlite3.connect(db_path)
        stock_info = pd.read_sql('SELECT stock_id, name, market_type FROM stock_info', conn)
        
        def is_eligible(sid, sname):
            if any(c.isalpha() for c in sid):
                if not (len(sid) == 6 and sid.endswith('A') and sid[:-1].isdigit()): return False
            if sname:
                if '正2' in sname or '反1' in sname: return False
                if '-DR' in sname: return False
            return True

        stock_info = stock_info[stock_info.apply(lambda x: is_eligible(x['stock_id'], x['name']), axis=1)]
        
        total = len(stock_info)
        results_list = []
        details_map = {}
        
        global_max_date = pd.read_sql("SELECT MAX(date) FROM daily_price", conn).iloc[0, 0]
        max_date_limit = pd.to_datetime(global_max_date) - pd.Timedelta(days=5) if global_max_date else None

        for idx, row in stock_info.iterrows():
            stock_id = row['stock_id']
            name = row['name'] or ''
            market = row.get('market_type', '')

            if progress_callback: progress_callback(idx + 1, total, f'{stock_id} {name}')

            df = pd.read_sql(
                f"SELECT date, open, high, low, close, volume, IFNULL(disposition_mins, 0) as disposition_mins FROM daily_price WHERE stock_id='{stock_id}' ORDER BY date ASC",
                conn
            )
            if df.empty or len(df) < 60: continue

            df.columns = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Disposition_Mins']
            df['Date'] = pd.to_datetime(df['Date'])
            if max_date_limit and df["Date"].iloc[-1] < max_date_limit: continue

            try:
                _, q_data, full_df = cls.analyze_wanderer(df)
                # --- 動態濾網 ---
                if req_slope and not q_data["Details"]["cond_slope"]: continue
                if req_bb_level and not q_data["Details"]["cond_bb_level"]: continue
                match = True
            except Exception:
                continue

            # 計算當日漲跌幅
            today_close = full_df.iloc[-1]['Close']
            yes_close = full_df.iloc[-2]['Close'] if len(full_df) >= 2 else today_close
            change_pct = round((today_close - yes_close) / yes_close * 100, 2) if yes_close > 0 else 0

            suffix = '.TW' if market == '上市' else '.TWO'
            real_ticker = f'{stock_id}{suffix}'

            # 取得產業分類
            try:
                import twstock
                tw_codes = twstock.codes
                industry = getattr(tw_codes.get(stock_id), "group", "其他") if tw_codes.get(stock_id) else "其他"
            except:
                industry = "其他"

            # 讀取最後一天的處置狀態
            disp_val = df.iloc[-1]['Disposition_Mins'] if 'Disposition_Mins' in df.columns else 0
            disp_str = f"每 {int(disp_val)} 分鐘撮合" if disp_val > 0 else "-"
            data_date = pd.to_datetime(df.iloc[-1]['Date']).strftime('%Y-%m-%d') if 'Date' in df.columns else ''

            result_row = {
                '代號': stock_id,
                '名稱': name,
                '產業': industry,
                '收盤價': round(q_data['Close'], 2),
                '今日漲跌幅(%)': change_pct,
                '成交量(張)': int(full_df.iloc[-1]['Volume'] / 1000) if 'Volume' in full_df.columns else 0,
                '成交額(億)': round((full_df.iloc[-1]['Close'] * full_df.iloc[-1]['Volume']) / 1e8, 2) if all(k in full_df.columns for k in ['Close', 'Volume']) else 0,
                '月線斜率(%)': round(q_data['MA20_Slope_Pct'], 4),
                '布林位階': round(q_data['BB_Position'], 2),
                '資料日期': data_date,
                '處置狀態': disp_str,
                'is_disposition': bool(disp_val > 0),
                '布林上軌': round(q_data['BB_Upper'], 2),
                '布林中軌': round(q_data['BB_Middle'], 2),
                '布林下軌': round(q_data['BB_Lower'], 2),
                '_ticker': real_ticker,
                '_name': name,
            }

            results_list.append(result_row)
            details_map[real_ticker] = {
                'q_data': q_data,
                'df': full_df,
                'pure_id': stock_id,
                'name': name,
                'industry': industry
            }

        conn.close()
        merge_sinopac_change_pct_into_rows(results_list)
        return results_list, details_map

@st.cache_data(ttl=3600)
def get_stock_data_with_name(ticker):
    """
    獲取股票數據並回傳 (df, real_ticker, display_ticker)
    """
    try:
        t = str(ticker).strip()
        symbols = [f"{t}.TW", f"{t}.TWO"] if t.isdigit() and len(t) == 4 else [t]
        
        df = pd.DataFrame()
        final_t = symbols[0]
        
        for sym in symbols:
            try:
                stock = yf.Ticker(sym)
                df = stock.history(period="250d")
                if not df.empty:
                    final_t = sym
                    break
            except:
                continue
        
        if not df.empty:
            # 優先從 Ticker.info 抓取名稱
            name = ""
            try:
                stock_obj = yf.Ticker(final_t)
                info = stock_obj.info
                name = info.get('longName') or info.get('shortName', '')
            except:
                name = ""
            
            # 清理代號顯示 (移除 .TW .TWO)
            pure_id = final_t.replace(".TW", "").replace(".TWO", "")
            
            return df.reset_index(), final_t, pure_id, name
        return None, final_t, ticker, ""
    except Exception:
        return None, ticker, ticker, ""



