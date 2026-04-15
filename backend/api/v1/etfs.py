from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any, List
from fastapi.responses import StreamingResponse
import pandas as pd
import sqlite3
import os
import google.generativeai as genai

# 重用 core.model 來讀取現有資料庫
from core.model import HoldingsModel
from core.controller import ScraperController
from datetime import datetime

router = APIRouter()
model = HoldingsModel()
scraper = ScraperController()


class ETFReportRequest(BaseModel):
    buy_list_csv: str
    sell_list_csv: str

ETF_LIST = {
    "00980A": "00980A 野村臺灣智慧優選",
    "00981A": "00981A 主動統一台股增長",
    "00982A": "00982A 群益台灣精選強棒",
    "00985A": "00985A 野村臺灣增強50",
    "00986A": "00986A 台新臺灣龍頭成長",
    "00987A": "00987A 台新臺灣優勢成長",
    "00988A": "00988A 主動統一全球創新",
    "00991A": "00991A 主動復華未來50",
    "00992A": "00992A 主動群益科技創新",
    "00993A": "00993A 安聯台灣主動式"
}

@router.get("/api/v1/etfs/list")
def get_etf_list():
    """取得支援的主動式 ETF 清單"""
    return {"etfs": sorted([{"code": k, "name": v} for k, v in ETF_LIST.items()], key=lambda x: x['code'])}


@router.get("/api/v1/etfs/all/dates")
def get_all_etf_dates():
    """取得所有 ETF 在資料庫裡曾存檔的不重複日期"""
    print(f"[*] Fetching all dates from: {model.db_file}")
    try:
        if not os.path.exists(model.db_file):
            return {"dates": []}
        with sqlite3.connect(model.db_file) as conn:
            df = pd.read_sql("SELECT DISTINCT date FROM holdings_v2 ORDER BY date DESC", conn)
            dates = df['date'].tolist()
            return {"dates": dates}
    except Exception as e:
        print(f"[!] Error fetching all dates: {e}")
        return {"dates": []}

@router.get("/api/v1/etfs/{etf_code}/dates")
def get_etf_dates(etf_code: str):
    """取得特定 ETF 可用的資料日期"""
    try:
        with sqlite3.connect(model.db_file) as conn:
            df = pd.read_sql("SELECT DISTINCT date FROM holdings_v2 WHERE etf_code = ? ORDER BY date DESC", conn, params=(etf_code,))
            dates = df['date'].tolist()
            return {"dates": dates}
    except Exception as e:
        return {"dates": []}

@router.get("/api/v1/etfs/{etf_code}/holdings")
def get_etf_holdings(etf_code: str, date: str):
    """取得特定 ETF 特定日期的持股明細"""
    try:
        with sqlite3.connect(model.db_file) as conn:
            df = pd.read_sql(
                "SELECT code as '代碼', name as '名稱', shares as '股數', weight as '權重(%)' FROM holdings_v2 WHERE etf_code = ? AND date = ?", 
                conn, 
                params=(etf_code, date)
            )
            return {"holdings": df.to_dict(orient="records")}
    except Exception as e:
        return {"holdings": []}

@router.get("/api/v1/etfs/cross-analysis")
def get_cross_etf_analysis(start_date: str, end_date: str):
    """計算全體 ETF 在特定期間內的買賣動向彙整"""
    try:
        # 自動校準日期順序，避免使用者選反
        d1, d2 = start_date, end_date
        if d1 > d2:
            d1, d2 = d2, d1
        
        # d1 = 較舊日期 (Start), d2 = 較新日期 (End)
        with sqlite3.connect(model.db_file) as conn:
            df_start_all = pd.read_sql("SELECT etf_code, code, name, shares, weight FROM holdings_v2 WHERE date = ?", conn, params=(d1,))
            df_end_all = pd.read_sql("SELECT etf_code, code, name, shares, weight FROM holdings_v2 WHERE date = ?", conn, params=(d2,))
            
        if df_start_all.empty or df_end_all.empty:
            return {"buy_stats": [], "sell_stats": []}

        all_codes = set(df_start_all['code']).union(set(df_end_all['code']))
        buy_stats = []
        sell_stats = []
        
        for code in all_codes:
            # 取得單一股票在兩段日期的所有 ETF 持股記錄
            s_data = df_start_all[df_start_all['code'] == code]
            e_data = df_end_all[df_end_all['code'] == code]
            
            # 名稱整合 (優先取新的)
            name = e_data['name'].iloc[0] if not e_data.empty else s_data['name'].iloc[0]
            
            # 建立 ETF -> 股數/權重 的對照表
            s_map = s_data.set_index('etf_code')['shares'].to_dict()
            e_map = e_data.set_index('etf_code')['shares'].to_dict()
            s_w_map = s_data.set_index('etf_code')['weight'].to_dict()
            e_w_map = e_data.set_index('etf_code')['weight'].to_dict()
            
            # 計算參與變動的 ETF 數量與總變動量
            all_etfs = set(s_map.keys()).union(set(e_map.keys()))
            net_diff = 0
            net_weight_diff = 0
            buy_etf_count = 0
            sell_etf_count = 0
            
            for etf in all_etfs:
                s_sh = s_map.get(etf, 0)
                e_sh = e_map.get(etf, 0)
                diff = e_sh - s_sh
                net_diff += diff
                
                s_w = s_w_map.get(etf, 0)
                e_w = e_w_map.get(etf, 0)
                net_weight_diff += (e_w - s_w)
                
                if diff > 100: # 略過微小變動
                    buy_etf_count += 1
                elif diff < -100:
                    sell_etf_count += 1
            
            lot_diff = net_diff / 1000
            
            if lot_diff > 0.1:
                buy_stats.append({
                    "code": code,
                    "name": name,
                    "etf_count": buy_etf_count, # 顯示真正買入的檔數
                    "total_buy_lots": int(lot_diff),
                    "weight_diff": round(net_weight_diff, 2)
                })
            elif lot_diff < -0.1:
                sell_stats.append({
                    "code": code,
                    "name": name,
                    "etf_count": sell_etf_count, # 顯示真正賣出的檔數
                    "total_sell_lots": int(abs(lot_diff)),
                    "weight_diff": round(net_weight_diff, 2)
                })

        buy_stats.sort(key=lambda x: x['total_buy_lots'], reverse=True)
        sell_stats.sort(key=lambda x: x['total_sell_lots'], reverse=True)

        return {
            "buy_stats": buy_stats,
            "sell_stats": sell_stats
        }
    except Exception as e:
        return {"buy_stats": [], "sell_stats": []}

@router.post("/api/v1/etfs/trigger-update/{etf_code}")
def trigger_etf_update(etf_code: str, target_date: str = Query(None)):
    """手動觸發特定 ETF 的爬蟲更新並存入資料庫"""
    try:
        from core.controller import ScraperController
        # initialize locally to avoid browser accumulation if global
        local_scraper = ScraperController() 
        print(f"[*] Starting manual update for ETF: {etf_code}")
        
        holdings = local_scraper.fetch_holdings(etf_code)
        
        if not holdings:
            raise HTTPException(status_code=400, detail=f"Failed to fetch data for {etf_code}")
            
        # 標記為指定的日期或今天的日期
        today = target_date if target_date else datetime.now().strftime('%Y-%m-%d')
        model.save_holdings(etf_code, holdings, target_date=today)
        
        return {"status": "success", "message": f"{etf_code} 數據已成功同步至 {today}", "count": len(holdings)}
    except Exception as e:
        print(f"Update failed for {etf_code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/etfs/trigger-update-all")
async def trigger_all_etfs_update(target_date: str = Query(None)):
    """背景執行或長時執行所有 ETF 的更新"""
    from core.controller import ScraperController
    local_scraper = ScraperController()
    today = target_date if target_date else datetime.now().strftime('%Y-%m-%d')
    
    results = []
    
    # 這裡可以考慮改成 BackgroundTasks
    # 不過如果是給個人用的工具，直接等它完成也可以，只是需要較長時間
    # 此處我們直接等它跑完
    for etf_code in ETF_LIST.keys():
        try:
            print(f"[*] Starting manual update for ETF: {etf_code}")
            holdings = local_scraper.fetch_holdings(etf_code)
            
            if holdings:
                model.save_holdings(etf_code, holdings, target_date=today)
                results.append({"code": etf_code, "status": "success", "count": len(holdings)})
            else:
                results.append({"code": etf_code, "status": "failed"})
                
        except Exception as e:
            print(f"Update failed for {etf_code}: {e}")
            results.append({"code": etf_code, "status": "error", "message": str(e)})

    return {"status": "completed", "date": today, "results": results}




@router.post("/api/v1/etfs/stream-report")
async def generate_etf_report(req: ETFReportRequest):
    """串流 AI 資金動向分析報告"""
    def generate():
        try:
            model_ai = genai.GenerativeModel("gemini-1.5-flash")
            prompt = f"""
            你是一位資深的台股基金經理人。請分析以下兩份數據：
            
            共同買入清單 (代碼,名稱,檔數,總張數):
            {req.buy_list_csv}
            
            共同賣出清單 (代碼,名稱,檔數,總張數):
            {req.sell_list_csv}
            
            請提供一份具備專業洞察的市場分析：
            1. 歸納目前的「主流熱門產業」以及經理人正在撤出的「避雷區」。
            2. 指出幾檔最具指標性的共同買入或賣出標的，並推論其背後可能的產業面或籌碼面因素。
            3. 最後給出這段期間整體的資金動向評估與未來一週的應對建議。
            
            請用繁體中文回答，條列清晰，口吻專業。
            """
            response = model_ai.generate_content(prompt, stream=True)
            for chunk in response:
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            yield f"\n[AI 分析中斷: {str(e)}]"

    return StreamingResponse(generate(), media_type="text/plain")
