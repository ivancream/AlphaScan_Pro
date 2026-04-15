# engine_heatmap.py
"""
資金流向熱力圖引擎 (Static Classifications)

負責：
1. 從 stock_info (SQLite) 取得最新日行情與官方產業分類 (macro)
2. 透過預先定義好的 STATIC_SECTOR_MAP，賦予 Meso 與 Micro 標籤
3. 組合前端 Treemap 格式數據
"""

import sqlite3
from typing import Dict, Any, List
from pathlib import Path

ROOT_PATH = Path(__file__).parent.parent.parent.absolute()
SQLITE_DB = ROOT_PATH / "data" / "taiwan_stock.db"

# ==========================================
# 靜態核心微標籤對應表 (根據 2026 深度解析報告)
# ==========================================
STATIC_SECTOR_MAP = {
    # [1. 核心運算基礎設施與半導體硬體板塊]
    # AI 伺服器與邊緣算力
    "2317": ("AI 伺服器與邊緣算力", "NVIDIA Vera Rubin 架構"), # 鴻海
    "2382": ("AI 伺服器與邊緣算力", "NVIDIA Vera Rubin 架構"), # 廣達
    "3231": ("AI 伺服器與邊緣算力", "NVIDIA Vera Rubin 架構"), # 緯創
    "6669": ("AI 伺服器與邊緣算力", "NVIDIA Vera Rubin 架構"), # 緯穎
    "2356": ("AI 伺服器與邊緣算力", "NVIDIA Vera Rubin 架構"), # 英業達
    "3706": ("AI 伺服器與邊緣算力", "NVIDIA Vera Rubin 架構"), # 神達
    "2344": ("AI 伺服器與邊緣算力", "HBM4 (第六代高頻寬記憶體)"), # 華邦電
    "2408": ("AI 伺服器與邊緣算力", "HBM4 (第六代高頻寬記憶體)"), # 南亞科
    
    # 散熱與電源架構革命
    "3017": ("散熱與電源架構革命", "液冷散熱 (全液冷/水冷板)"), # 奇鋐
    "3324": ("散熱與電源架構革命", "液冷散熱 (全液冷/水冷板)"), # 雙鴻
    "3653": ("散熱與電源架構革命", "液冷散熱 (全液冷/水冷板)"), # 健策
    "2421": ("散熱與電源架構革命", "液冷散熱 (全液冷/水冷板)"), # 建準
    "8996": ("散熱與電源架構革命", "液冷散熱 (全液冷/水冷板)"), # 高力
    "2308": ("散熱與電源架構革命", "CDU (冷卻液分配裝置) / HVDC"), # 台達電
    "2301": ("散熱與電源架構革命", "CDU (冷卻液分配裝置) / HVDC"), # 光寶科
    "6282": ("散熱與電源架構革命", "CDU (冷卻液分配裝置) / HVDC"), # 康舒
    
    # 先進製程與新世代封裝
    "2330": ("先進製程與新世代封裝", "2奈米 (N2) / GAA 架構"), # 台積電
    "3711": ("先進製程與新世代封裝", "TGV 玻璃基板 (Glass Substrate)"), # 日月光投控
    "3673": ("先進製程與新世代封裝", "TGV 玻璃基板 (Glass Substrate)"), # TPK-KY
    "3131": ("先進製程與新世代封裝", "TGV 玻璃基板 (Glass Substrate)"), # 弘塑
    "3189": ("先進製程與新世代封裝", "TGV 玻璃基板 (Glass Substrate)"), # 景碩
    "3037": ("先進製程與新世代封裝", "TGV 玻璃基板 (Glass Substrate)"), # 欣興
    "8046": ("先進製程與新世代封裝", "TGV 玻璃基板 (Glass Substrate)"), # 南電
    "2383": ("先進製程與新世代封裝", "銅箔基板 (CCL)"), # 台光電
    "6274": ("先進製程與新世代封裝", "銅箔基板 (CCL)"), # 台燿
    "6213": ("先進製程與新世代封裝", "銅箔基板 (CCL)"), # 聯茂
    
    # [2. 網通、光電互連與實體終端板塊]
    # CPO 矽光子與網通設備
    "3363": ("CPO 矽光子與網通設備", "COUPE 封裝陣營 / 光學互連"), # 上詮
    "4979": ("CPO 矽光子與網通設備", "CPO 共同封裝光學"), # 華星光
    "3163": ("CPO 矽光子與網通設備", "CPO 共同封裝光學"), # 波若威
    "2350": ("CPO 矽光子與網通設備", "CPO 共同封裝光學"), # 智邦
    
    # 下世代立體通訊網 (NTN)
    "3491": ("下世代立體通訊網 (NTN)", "6G NTN / 低軌衛星通訊"), # 昇達科
    "6285": ("下世代立體通訊網 (NTN)", "6G NTN / 低軌衛星通訊"), # 啟碁
    "3149": ("下世代立體通訊網 (NTN)", "6G NTN / 低軌衛星通訊"), # 耀登
    
    # 實體 AI 與智慧製造
    "2359": ("實體 AI 與智慧製造", "人形機器人 / 機器人即服務(RaaS)"), # 所羅門
    "4583": ("實體 AI 與智慧製造", "人形機器人 / 機器人即服務(RaaS)"), # 台灣精銳
    "6166": ("實體 AI 與智慧製造", "行為庫 (Behavior Library)"), # 凌華
    "2395": ("實體 AI 與智慧製造", "行為庫 (Behavior Library)"), # 研華
    "6414": ("實體 AI 與智慧製造", "行為庫 (Behavior Library)"), # 樺漢
    "8033": ("實體 AI 與智慧製造", "無人機 (空中實體 AI) / 三晶二軟"), # 雷虎
    "2634": ("實體 AI 與智慧製造", "無人機 (空中實體 AI) / 三晶二軟"), # 漢翔
    
    # 次世代消費性終端
    "3376": ("次世代消費性終端", "摺疊機 (Foldable iPhone)"), # 新日興
    "3533": ("次世代消費性終端", "摺疊機 (Foldable iPhone)"), # 嘉澤
    
    # [3. 數位經濟、政策治理與綠能醫療板塊]
    # 資安防禦與 AI 監理
    "6811": ("資安防禦與 AI 監理", "零信任架構 / SBOM / AI SOC"), # 宏碁資訊
    "6613": ("資安防禦與 AI 監理", "零信任架構 / SBOM / AI SOC"), # 零壹
    "6690": ("資安防禦與 AI 監理", "零信任架構 / SBOM / AI SOC"), # 安碁資訊
    
    # 智慧醫療與高齡科技
    "6472": ("智慧醫療與高齡科技", "AI 影像診斷 / 數位孿生醫療"), # 保瑞
    "1795": ("智慧醫療與高齡科技", "AI 影像診斷 / 數位孿生醫療"), # 美時
    
    # 綠能轉型與碳定價
    "6806": ("綠能轉型與碳定價", "碳費開徵 / 碳盤查軟體"), # 森崴能源
    "1519": ("綠能轉型與碳定價", "碳費開徵 / 碳盤查軟體"), # 華城
    "1513": ("綠能轉型與碳定價", "碳費開徵 / 碳盤查軟體"), # 中興電
    "1514": ("綠能轉型與碳定價", "碳費開徵 / 碳盤查軟體"), # 亞力
    
    # 前瞻技術探勘
    "8054": ("前瞻技術探勘", "量子通訊 / 拓撲導體"), # 安國
    "3228": ("前瞻技術探勘", "量子通訊 / 拓撲導體"), # 金麗科
}

def _get_fallback_tags(macro: str) -> tuple[str, str]:
    """根據大視野 (macro) 給予預設的中/小視野標籤"""
    if "半導體" in macro:
        return ("傳統晶圓與IC設計", "晶片製造與設計")
    elif "光電" in macro:
        return ("光電與面板組件", "顯示與感測技術")
    elif "電腦及週邊" in macro:
        return ("傳統PC與代工", "電腦系統裝配")
    elif "通信" in macro:
        return ("傳統網通設備", "有線與無線通訊")
    elif "電機" in macro:
        return ("電機機械與零組件", "傳動與控制")
    elif "金融" in macro:
        return ("金控與保險", "金融服務")
    elif "航運" in macro:
        return ("海空運與物流", "運輸服務")
    elif "生技醫療" in macro:
        return ("傳統醫療與製藥", "生醫產品與服務")
    else:
        return (macro, macro)

def get_heatmap_data(metric: str = "change_pct") -> Dict[str, Any]:
    if not SQLITE_DB.exists():
        return {"date": None, "stocks": []}

    try:
        import twstock
        tw_codes = twstock.codes
    except Exception:
        tw_codes = {}

    with sqlite3.connect(str(SQLITE_DB)) as conn:
        latest_date_row = conn.execute("SELECT MAX(date) FROM daily_price").fetchone()
        if not latest_date_row or not latest_date_row[0]:
            return {"date": None, "stocks": []}
        latest_date = latest_date_row[0]

        today_rows = conn.execute(
            "SELECT stock_id, close, volume, open FROM daily_price WHERE date = ?",
            [latest_date]
        ).fetchall()

        prev_date_row = conn.execute(
            "SELECT MAX(date) FROM daily_price WHERE date < ?", [latest_date]
        ).fetchone()
        prev_date = prev_date_row[0] if prev_date_row else None

        prev_close_map = {}
        if prev_date:
            prev_rows = conn.execute(
                "SELECT stock_id, close FROM daily_price WHERE date = ?", [prev_date]
            ).fetchall()
            prev_close_map = {r[0]: r[1] for r in prev_rows}

        stock_names = {}
        names_rows = conn.execute("SELECT stock_id, name FROM stock_info").fetchall()
        for stock_id, name in names_rows:
            stock_names[stock_id] = name

    stocks = []
    for stock_id, close, volume, open_price in today_rows:
        if close is None or close <= 0:
            continue

        macro = "其他"
        if stock_id in tw_codes:
            macro = getattr(tw_codes[stock_id], "group", "其他") or "其他"
        
        name = stock_names.get(stock_id, stock_id)

        # 決定 Meso 與 Micro
        if stock_id in STATIC_SECTOR_MAP:
            meso, micro = STATIC_SECTOR_MAP[stock_id]
        else:
            meso, micro = _get_fallback_tags(macro)

        prev_close = prev_close_map.get(stock_id)
        if prev_close and prev_close > 0:
            change_pct = round((close - prev_close) / prev_close * 100, 2)
        else:
            change_pct = 0.0

        # Turnover = 股價 * 成交股數
        turnover = int(close * volume) if volume else 0

        stocks.append({
            "ticker": stock_id,
            "name": name,
            "macro": macro,
            "meso": meso,
            "micro": micro,
            "close": round(close, 2),
            "change_pct": change_pct,
            "turnover": turnover,
            "volume": int(volume / 1000) if volume else 0, # 轉換成「張」
        })

    stocks.sort(key=lambda s: s["turnover"], reverse=True)
    return {"date": latest_date, "stocks": stocks}
