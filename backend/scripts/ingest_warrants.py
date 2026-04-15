# ingest_warrants.py
import duckdb
import pandas as pd
from datetime import date

def ingest_warrant_data():
    """
    將權證籌碼數據輸入 DuckDB
    """
    db_path = '../data/market.duckdb'
    conn = duckdb.connect(db_path)
    
    # 建立表結構 (如果不存在)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS warrant_chips (
            symbol VARCHAR, 
            name VARCHAR, 
            broker VARCHAR, 
            amount_k DOUBLE, 
            type VARCHAR, 
            date DATE, 
            estimated_pnl DOUBLE,
            PRIMARY KEY (symbol, broker, date, type)
        );
    """)
    
    # 從圖片中提取的數據 (日期統一為 2026-03-06)
    data = [
        {"symbol": "3231", "name": "緯創", "broker": "群益金鼎-中壢", "amount_k": 3299.0, "type": "認購", "date": "2026-03-06", "estimated_pnl": -2609.4},
        {"symbol": "8210", "name": "勤誠", "broker": "群益金鼎-中壢", "amount_k": 1453.0, "type": "認購", "date": "2026-03-06", "estimated_pnl": -574.1},
        {"symbol": "3324", "name": "雙鴻", "broker": "元大-南屯", "amount_k": 6400.0, "type": "認購", "date": "2026-03-06", "estimated_pnl": -713.2},
        {"symbol": "2308", "name": "台達電", "broker": "元大-南屯", "amount_k": 4986.0, "type": "認購", "date": "2026-03-06", "estimated_pnl": 5359.7},
        {"symbol": "2329", "name": "華泰", "broker": "華南永昌-台中", "amount_k": 4669.0, "type": "認購", "date": "2026-03-06", "estimated_pnl": -2894.3},
        {"symbol": "1795", "name": "美時", "broker": "永豐金-竹北", "amount_k": 3872.0, "type": "認購", "date": "2026-03-06", "estimated_pnl": -2425.9},
        {"symbol": "2603", "name": "長榮", "broker": "永豐金-員林", "amount_k": 2143.0, "type": "認購", "date": "2026-03-06", "estimated_pnl": -68.5},
        {"symbol": "3661", "name": "世芯-KY", "broker": "國票", "amount_k": 1993.0, "type": "認購", "date": "2026-03-06", "estimated_pnl": -161.2},
        {"symbol": "2317", "name": "鴻海", "broker": "永豐金-新竹", "amount_k": 2912.0, "type": "認購", "date": "2026-03-06", "estimated_pnl": -265.6}
    ]
    
    df = pd.DataFrame(data)
    df['date'] = pd.to_datetime(df['date']).dt.date
    
    print(f"正在輸入 {len(df)} 筆權證籌碼數據（含推估損益）...")
    
    # Upsert 邏輯
    conn.execute("""
        INSERT INTO warrant_chips 
        SELECT symbol, name, broker, amount_k, type, date, estimated_pnl FROM df
        ON CONFLICT (symbol, broker, date, type) DO UPDATE SET
            amount_k = excluded.amount_k,
            estimated_pnl = excluded.estimated_pnl,
            name = excluded.name;
    """)
    
    conn.close()
    print("數據輸入完成。")

if __name__ == "__main__":
    ingest_warrant_data()
