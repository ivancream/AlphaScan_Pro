import sqlite3
import requests
import re
from datetime import datetime, timedelta
import os
import sys

# Define root paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATHS = [
    os.path.join(PROJECT_ROOT, "databases", "db_technical_prices.db"),
    os.path.join(PROJECT_ROOT, "data", "taiwan_stock.db")
]

def _parse_mins(text: str) -> int:
    if not text: return 0
    if '5分鐘' in text or '五分鐘' in text or '5分' in text: return 5
    if '10分鐘' in text or '十分鐘' in text or '10分' in text: return 10
    if '20分鐘' in text or '二十分鐘' in text or '20分' in text: return 20
    if '22分鐘' in text: return 22
    if '25分鐘' in text: return 25
    
    match = re.search(r'每[^\d]*(\d+)[^\d]*分', text)
    if match: return int(match.group(1))
    
    if '第一次處置' in text: return 5
    if '第二次處置' in text: return 20
    if '第三次處置' in text: return 45
    return 0 # 預設無

def _format_date_roc_to_iso(roc_date: str) -> str:
    """ 轉換民國年格式 (如: 1150326 或 115/03/26) 到 ISO 格式 (2026-03-26) """
    d = str(roc_date).replace('/', '')
    if len(d) == 7 and d.startswith('1'):
        year = int(d[:3]) + 1911
        month = d[3:5]
        day = d[5:]
        return f"{year}-{month}-{day}"
    return d

def fetch_current_dispositions():
    res = []
    
    # TWSE 上市處置
    print("[*] 正在抓取 TWSE 上市處置資訊...")
    try:
        twse_data = requests.get("https://openapi.twse.com.tw/v1/announcement/punish", timeout=10).json()
        for row in twse_data:
            code = row.get("Code", "")
            period = row.get("DispositionPeriod", "")
            start = period.split('～')[0].strip() if '～' in period else ''
            end = period.split('～')[1].strip() if '～' in period else ''
            cond = row.get("DispositionMeasures", "")
            mins = _parse_mins(cond)
            if code and start and end:
                res.append({
                    "code": code,
                    "start": _format_date_roc_to_iso(start),
                    "end": _format_date_roc_to_iso(end),
                    "mins": mins
                })
    except Exception as e:
        print(f"[!] TWSE Error: {e}")

    # TPEx 上櫃處置
    print("[*] 正在抓取 TPEx 上櫃處置資訊...")
    try:
        tpex_data = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_disposal_information", timeout=10).json()
        for row in tpex_data:
            code = row.get("SecuritiesCompanyCode", "")
            start = row.get("DisposalStartDate", "")
            end = row.get("DisposalEndDate", "")
            cond = row.get("DisposalMeasures", "")
            mins = _parse_mins(cond)
            if code and start and end:
                res.append({
                    "code": code,
                    "start": _format_date_roc_to_iso(start),
                    "end": _format_date_roc_to_iso(end),
                    "mins": mins
                })
    except Exception as e:
        print(f"[!] TPEx Error: {e}")

    return res

def expand_date_range(start_iso: str, end_iso: str):
    """ 將日期區間展開成清單，用於批次 Update """
    try:
        st = datetime.strptime(start_iso, "%Y-%m-%d")
        ed = datetime.strptime(end_iso, "%Y-%m-%d")
        dates = []
        curr = st
        while curr <= ed:
            # yfinance 抓回來的 date 通常是 ISO string 或者包含時區的 string
            dates.append(curr.strftime("%Y-%m-%d"))
            curr += timedelta(days=1)
        return dates
    except Exception as e:
        return []

def main():
    print("========================================")
    print("        處置股標記更新腳本 (Update Disp)")
    print("========================================")
    
    events = fetch_current_dispositions()
    if not events:
        print("[-] 今日無處置股資料可以更新。")
        return
        
    print(f"[*] 解析完成，共 {len(events)} 筆處置資料準備寫入資料庫...")
    
    for db_path in DB_PATHS:
        if not os.path.exists(db_path):
            print(f"[!] 資料庫不存在略過: {db_path}")
            continue
            
        print(f"\n[*] 連接資料庫: {db_path}")
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 首先重置未來的處置紀錄 (防止處置提早解除或被覆蓋)
            # 因為 yfinance 通常只有已收盤的日期，所以重置這兩個月內的所有標籤 (確保洗盤乾淨)
            today_iso = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("UPDATE daily_price SET disposition_mins = 0 WHERE date >= date(?, '-60 days')", (today_iso,))
            
            updates_count = 0
            
            for ev in events:
                code = ev['code']
                mins = ev['mins']
                date_list = expand_date_range(ev['start'], ev['end'])
                if not date_list: continue

                # 將 Date LIKE 對應，因為 daily_price date 可能是 "2024-03-26 00:00:00"
                for d in date_list:
                    # 嘗試更新這檔股票在這天的紀錄 (支援無後綴或有 .TW/.TWO 的格式)
                    cursor.execute(
                        f"UPDATE daily_price SET disposition_mins = ? WHERE stock_id IN (?, ?, ?) AND date LIKE ?",
                        (mins, code, f"{code}.TW", f"{code}.TWO", f"{d}%")
                    )
                    updates_count += cursor.rowcount
            
            conn.commit()
            print(f"[+] 成功更新 {updates_count} 筆處置記號於 {os.path.basename(db_path)}")
            conn.close()
        except Exception as e:
            print(f"[!] 更新資料庫時發生錯誤: {e}")

if __name__ == '__main__':
    main()
