# engine_technical.py
import os
from datetime import date, timedelta
import pandas as pd
import numpy as np
import google.generativeai as genai
from typing import Tuple, List, Dict, Optional, Any
from . import prompts
from .sinopac_snapshots import (
    merge_sinopac_change_pct_into_rows,
    fetch_single_stock_ohlcv,
)
from .disposition_overlay import enrich_scan_rows_disposition
import pandas_ta as ta

from backend.db import queries as _db_queries
from backend.db.symbol_utils import strip_suffix as _strip_suffix

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

def _period_to_start_date(period: str) -> date:
    """將 yfinance 風格的 period 字串換算為起始日期。"""
    _MAP = {
        "1mo": 30, "3mo": 90, "6mo": 180,
        "1y": 365, "2y": 730, "5y": 1825, "max": 3650,
    }
    days = _MAP.get(period.lower(), 365)
    return date.today() - timedelta(days=days)


def fetch_data(stock_id: str, period: str = "1y") -> Optional[pd.DataFrame]:
    """
    【雙層快取架構】取得技術分析用的完整 K 線 DataFrame。

    Layer-1（歷史層）：從 DuckDB daily_prices 讀取截至昨日的 K 線。
    Layer-2（即時層）：補入今日永豐 Sinopac snapshot，讓指標反映即時價格。
    """
    pure_id = _strip_suffix(str(stock_id).strip())

    try:
        df_raw = _db_queries.get_price_df(pure_id, period=period)
    except Exception as exc:
        print(f"[fetch_data] DuckDB 讀取失敗 ({pure_id}): {exc}")
        return None

    if df_raw is None or df_raw.empty:
        print(f"[fetch_data] DB 無資料: {pure_id}")
        return None

    df_raw["date"] = pd.to_datetime(df_raw["date"])
    df = df_raw.rename(columns={
        "date": "Date", "open": "Open", "high": "High",
        "low": "Low", "close": "Close", "volume": "Volume",
    })
    df = df.set_index("Date")
    df.index = df.index.tz_localize(None)
    df.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)

    if df.empty:
        return None

    # Layer-2: today's intraday snapshot
    today_dt = pd.Timestamp(date.today()).tz_localize(None)
    if today_dt not in df.index:
        snap = fetch_single_stock_ohlcv(pure_id)
        if snap and snap.get("Close", 0) > 0:
            today_row = pd.DataFrame(
                [{"Open": snap["Open"], "High": snap["High"],
                  "Low": snap["Low"], "Close": snap["Close"],
                  "Volume": snap["Volume"]}],
                index=[today_dt],
            )
            today_row.index.name = "Date"
            df = pd.concat([df, today_row])
            print(f"[fetch_data] {pure_id} 補入今日快照 Close={snap['Close']}")
        else:
            print(f"[fetch_data] {pure_id} 無今日快照，使用歷史資料")

    return df

def get_symbol_name(stock_id: str) -> str:
    """從 DuckDB stock_info 取得股票中文名稱。"""
    pure_id = _strip_suffix(str(stock_id).strip())
    # 先查本地對照表（常用權值股快速回傳）
    for suffix in (".TW", ".TWO", ""):
        if f"{pure_id}{suffix}" in TW_NAMES:
            return TW_NAMES[f"{pure_id}{suffix}"]
    return _db_queries.get_stock_name(pure_id)

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
    
    # 8. 相對強度 RS：暫以 0 填充（已棄用 yfinance；未來可改由 DB 讀取 TAIEX 日 K）
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
        return cls.analyze_from_computed(df, upper_slope_threshold, vol_surge_multiplier)

    @classmethod
    def analyze_from_computed(cls, df, upper_slope_threshold=0.003, vol_surge_multiplier=1.5):
        """Judgment logic only — assumes df already has indicator columns."""
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
        """取得最新集保數據與週變動（從 DuckDB tdcc_distribution）。"""
        pure_id = _strip_suffix(str(stock_id).strip())
        return _db_queries.get_chip_metrics(pure_id)

    @classmethod
    def analyze_short(cls, df):
        """
        波段空方策略 (趨勢轉空 + 沿下軌佈局):
        條件一: 趨勢轉空 — MA5 < MA10 < MA20 且月線斜率 < 0
        條件二: 沿布林下軌開單 — 價格在下軌與中軌之間，且較靠近下軌
                (position_ratio = (Close - Lower) / (Middle - Lower) < 0.4)
        """
        df = cls.calculate_indicators(df)
        return cls.analyze_short_from_computed(df)

    @classmethod
    def analyze_short_from_computed(cls, df):
        """Judgment logic only — assumes df already has indicator columns."""
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
        req_ma: bool = True,
        req_vol: bool = True,
        req_slope: bool = True,
        req_chips: bool = True,
        req_near_band: bool = True,
        progress_callback=None
    ) -> Tuple[List[Dict], Dict[str, Dict]]:
        """從 DuckDB 海選股票，並套用動態過濾條件。"""
        # Load all history from DuckDB (single batch read)
        all_history_df = _db_queries.get_price_df_all(cutoff_days=500)
        if all_history_df.empty:
            return [], {}

        stock_info_df = _db_queries.get_stock_info_df()
        stock_info = stock_info_df.rename(columns={"market": "market_type"}) if not stock_info_df.empty else pd.DataFrame()

        # Minimal adapter to use same logic below
        class _FakeConn:
            def close(self): pass

        conn = _FakeConn()

        # Preload price data per stock
        _price_cache: Dict[str, pd.DataFrame] = {}
        for sid, grp in all_history_df.groupby("stock_id"):
            sub = grp.drop(columns=["stock_id"]).reset_index(drop=True)
            sub.columns = [c.capitalize() if c in ("date","open","high","low","close","volume") else c for c in sub.columns]
            sub.rename(columns={"Date": "Date", "Disposition_mins": "Disposition_Mins"}, inplace=True, errors="ignore")
            _price_cache[str(sid)] = sub

        def _read_price(stock_id: str) -> pd.DataFrame:
            return _price_cache.get(stock_id, pd.DataFrame())
        
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

        max_date_limit = None
        if _price_cache:
            all_last = [g["Date"].max() if "Date" in g.columns else g.iloc[:, 0].max()
                        for g in _price_cache.values() if not g.empty]
            if all_last:
                global_max = pd.to_datetime(max(all_last))
                max_date_limit = global_max - pd.Timedelta(days=5)

        for idx, row in stock_info.iterrows():
            stock_id = row["stock_id"]
            name = row["name"] or ""
            market = row.get("market_type", "")

            if progress_callback: progress_callback(idx + 1, total, f"{stock_id} {name}")

            df = _read_price(stock_id)
            if df.empty or len(df) < min_rows: continue

            if "Date" not in df.columns:
                df.columns = ["Date", "Open", "High", "Low", "Close", "Volume"] + list(df.columns[6:])
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

            today_close = full_df.iloc[-1]['Close']
            yes_close = full_df.iloc[-2]['Close'] if len(full_df) >= 2 else today_close
            if yes_close > 0:
                raw_pct = (today_close - yes_close) / yes_close * 100
                change_pct = round(max(-10.0, min(10.0, raw_pct)), 2)
            else:
                change_pct = 0

            data_date = pd.to_datetime(full_df.iloc[-1]['Date']).strftime('%Y-%m-%d') if 'Date' in full_df.columns else ''

            try:
                import twstock
                tw_codes = twstock.codes
                industry = getattr(tw_codes.get(stock_id), "group", "其他") if tw_codes.get(stock_id) else "其他"
            except Exception:
                industry = "其他"

            suffix = ".TWO" if market in ("OTC", "上櫃") else ".TW"
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
        return cls.analyze_wanderer_from_computed(df)

    @classmethod
    def analyze_wanderer_from_computed(cls, df):
        """Judgment logic only — assumes df already has indicator columns."""
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
        """浪子回頭策略海選（DuckDB batch read）。"""
        all_history_df = _db_queries.get_price_df_all(cutoff_days=500)
        if all_history_df.empty:
            return [], {}

        stock_info_df = _db_queries.get_stock_info_df()
        stock_info = stock_info_df.rename(columns={"market": "market_type"}) if not stock_info_df.empty else pd.DataFrame()

        _price_cache: Dict[str, pd.DataFrame] = {}
        for sid, grp in all_history_df.groupby("stock_id"):
            sub = grp.drop(columns=["stock_id"]).reset_index(drop=True)
            sub.columns = [c.capitalize() if c in ("date","open","high","low","close","volume") else c for c in sub.columns]
            sub.rename(columns={"Disposition_mins": "Disposition_Mins"}, inplace=True, errors="ignore")
            if "Disposition_Mins" not in sub.columns:
                sub["Disposition_Mins"] = 0
            _price_cache[str(sid)] = sub

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

        max_date_limit = None
        if _price_cache:
            all_last = []
            for g in _price_cache.values():
                if not g.empty and "Date" in g.columns:
                    all_last.append(g["Date"].max())
            if all_last:
                max_date_limit = pd.to_datetime(max(all_last)) - pd.Timedelta(days=5)

        for idx, row in stock_info.iterrows():
            stock_id = row['stock_id']
            name = row['name'] or ''
            market = row.get('market_type', '')

            if progress_callback: progress_callback(idx + 1, total, f'{stock_id} {name}')

            df = _price_cache.get(stock_id, pd.DataFrame())
            if df.empty or len(df) < 60: continue

            if "Date" not in df.columns:
                df.columns = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Disposition_Mins'][:len(df.columns)]
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

            suffix = '.TWO' if market in ('OTC', '上櫃') else '.TW'
            real_ticker = f'{stock_id}{suffix}'

            try:
                import twstock
                tw_codes = twstock.codes
                industry = getattr(tw_codes.get(stock_id), "group", "其他") if tw_codes.get(stock_id) else "其他"
            except Exception:
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

        enrich_scan_rows_disposition(results_list)
        merge_sinopac_change_pct_into_rows(results_list)
        return results_list, details_map


# Simple in-memory TTL cache (replaces streamlit @st.cache_data)
_stock_data_cache: Dict[str, tuple] = {}
_stock_data_ts: Dict[str, float] = {}
_CACHE_TTL = 1800  # 30 min


def get_stock_data_with_name(ticker):
    """
    取得股票 K 線資料與名稱。
    回傳: (df_with_reset_index, real_ticker, pure_id, name)
    """
    import time
    now = time.time()
    if ticker in _stock_data_cache and now - _stock_data_ts.get(ticker, 0) < _CACHE_TTL:
        return _stock_data_cache[ticker]

    try:
        pure_id = _strip_suffix(str(ticker).strip())
        market = _db_queries.get_stock_market(pure_id)
        suffix = ".TWO" if market == "OTC" else ".TW"
        real_ticker = f"{pure_id}{suffix}"

        df = fetch_data(pure_id, period="1y")
        if df is None or df.empty:
            result = (None, real_ticker, pure_id, "")
        else:
            name = get_symbol_name(pure_id)
            result = (df.reset_index(), real_ticker, pure_id, name)

        _stock_data_cache[ticker] = result
        _stock_data_ts[ticker] = now
        return result
    except Exception:
        return None, ticker, ticker, ""



