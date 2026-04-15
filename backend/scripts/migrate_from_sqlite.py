import duckdb
import sqlite3
import pandas as pd
import os

def migrate_databases():
    # Legacy DB paths
    tech_db_path = "../databases/db_technical_prices.db"
    chips_db_path = "../databases/db_chips_ownership.db"
    new_duckdb_path = "data/market.duckdb"
    
    os.makedirs(os.path.dirname(os.path.abspath(new_duckdb_path)), exist_ok=True)
    duck_conn = duckdb.connect(new_duckdb_path)

    print("🚀 建立 DuckDB tables...")
    duck_conn.execute("""
        CREATE TABLE IF NOT EXISTS historical_prices (
            symbol VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT,
            PRIMARY KEY (symbol, date)
        );
        CREATE TABLE IF NOT EXISTS stock_info (
            symbol VARCHAR PRIMARY KEY, name VARCHAR, market_type VARCHAR
        );
        CREATE TABLE IF NOT EXISTS tdcc_dist (
            date DATE, symbol VARCHAR, total_owners BIGINT, retail_pct DOUBLE, whale_400_pct DOUBLE, whale_1000_pct DOUBLE,
            PRIMARY KEY (date, symbol)
        );
        CREATE TABLE IF NOT EXISTS institutional_investors (
            date DATE, symbol VARCHAR, foreign_buy BIGINT, trust_buy BIGINT, dealer_self_buy BIGINT, dealer_hedge_buy BIGINT,
            PRIMARY KEY (date, symbol)
        );
    """)

    # 1. Migrate Technical Prices & Info
    if os.path.exists(tech_db_path):
        print("📥 搬運 db_technical_prices.db...")
        try:
            sql_tech = sqlite3.connect(tech_db_path)
            
            # Migrate stock_info
            print("  -> 搬運 stock_info...")
            df_info = pd.read_sql("SELECT stock_id as symbol, name, market_type FROM stock_info", sql_tech)
            if not df_info.empty:
                duck_conn.execute("""
                    INSERT OR IGNORE INTO stock_info 
                    SELECT symbol, name, market_type FROM df_info
                """)
                
            # Migrate daily_price
            print("  -> 搬運 daily_price (historical_prices)...")
            df_price = pd.read_sql("SELECT stock_id as symbol, date, open, high, low, close, volume FROM daily_price", sql_tech)
            if not df_price.empty:
                df_price['date'] = pd.to_datetime(df_price['date']).dt.date
                # DuckDB bulk insert
                duck_conn.execute("""
                    INSERT OR IGNORE INTO historical_prices 
                    SELECT symbol, CAST(date AS DATE), open, high, low, close, volume FROM df_price
                """)
                
            sql_tech.close()
            print("✅ db_technical_prices 搬運完成")
        except Exception as e:
            print(f"❌ db_technical_prices.db 搬運錯誤: {e}")
    else:
        print(f"⚠️ 找不到 {tech_db_path}")

    # 2. Migrate Chips Ownership
    if os.path.exists(chips_db_path):
        print("📥 搬運 db_chips_ownership.db...")
        try:
            sql_chips = sqlite3.connect(chips_db_path)
            
            # Migrate tdcc_dist
            print("  -> 搬運 tdcc_dist...")
            df_tdcc = pd.read_sql("SELECT date, stock_id as symbol, total_owners, retail_pct, whale_400_pct, whale_1000_pct FROM tdcc_dist", sql_chips)
            if not df_tdcc.empty:
                df_tdcc['date'] = pd.to_datetime(df_tdcc['date']).dt.date
                duck_conn.execute("""
                    INSERT OR IGNORE INTO tdcc_dist 
                    SELECT CAST(date AS DATE), symbol, total_owners, retail_pct, whale_400_pct, whale_1000_pct FROM df_tdcc
                """)

            # Migrate institutional_investors
            print("  -> 搬運 institutional_investors...")
            df_inst = pd.read_sql("SELECT date, stock_id as symbol, foreign_buy, trust_buy, dealer_self_buy, dealer_hedge_buy FROM institutional_investors", sql_chips)
            if not df_inst.empty:
                df_inst['date'] = pd.to_datetime(df_inst['date']).dt.date
                duck_conn.execute("""
                    INSERT OR IGNORE INTO institutional_investors 
                    SELECT CAST(date AS DATE), symbol, foreign_buy, trust_buy, dealer_self_buy, dealer_hedge_buy FROM df_inst
                """)

            sql_chips.close()
            print("✅ db_chips_ownership 搬運完成")
        except Exception as e:
            print(f"❌ db_chips_ownership.db 搬運錯誤: {e}")
    else:
        print(f"⚠️ 找不到 {chips_db_path}")

    duck_conn.close()
    print("🎉 資料庫整體搬運結束！")

if __name__ == "__main__":
    migrate_databases()
