import yfinance as yf
import duckdb
import pandas as pd
import os

def ingest_historical_data(symbol: str, db_path: str = '../data/market.duckdb'):
    """
    從 yfinance 下載歷史數據並 Upsert 寫入 DuckDB
    """
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = duckdb.connect(db_path)
    
    # 建立核心表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS historical_prices (
            symbol VARCHAR, 
            date DATE, 
            open DOUBLE, 
            high DOUBLE, 
            low DOUBLE, 
            close DOUBLE, 
            volume BIGINT,
            PRIMARY KEY (symbol, date)
        );
    """)
    
    print(f"Downloading data for {symbol}...")
    df = yf.download(symbol, period="max")
    if df.empty:
        print(f"No data found for {symbol}")
        return
        
    df = df.reset_index()
    # 處理 yfinance 可能回傳的多層次 Column Index
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    # 保留必要欄位並確保欄位名稱小寫
    cols = {c: c.lower() for c in df.columns}
    df = df.rename(columns=cols)
    
    # 確保包含所需欄位
    required = ['date', 'open', 'high', 'low', 'close', 'volume']
    for req in required:
        if req not in df.columns:
            print(f"Missing required column: {req}")
            return
            
    df = df[required].copy()
    df['symbol'] = symbol
    
    print(f"Ingesting {len(df)} rows into DuckDB...")
    # 利用 DuckDB 內建的關聯特性
    conn.execute("""
        INSERT INTO historical_prices 
        SELECT symbol, CAST(date AS DATE), open, high, low, close, volume FROM df
        ON CONFLICT (symbol, date) DO UPDATE SET
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume;
    """)
    conn.close()
    print(f"Successfully ingested data for {symbol}.")

if __name__ == "__main__":
    # 以台積電為範例測試
    ingest_historical_data("2330.TW")
