import sqlite3
import yfinance as yf
import pandas as pd
import datetime
import twstock # 需安裝: pip install twstock
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.path.join(BASE_DIR, "data", "taiwan_stock.db")

class MarketDB:
    def __init__(self):
        # 允許跨執行緒使用，解決 GUI 卡住問題
        self.conn = sqlite3.connect(DB_NAME, check_same_thread=False, timeout=30)
        self.conn.execute('PRAGMA journal_mode=WAL')  # 允許多程序同時讀寫
        self.conn.execute('PRAGMA busy_timeout=10000')  # 等鎖最多 10 秒
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        # 建立股價表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_price (
                stock_id TEXT,
                date TIMESTAMP,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (stock_id, date)
            )
        ''')
        # 建立一個簡單的股票基本資料表 (存股票名稱)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_info (
                stock_id TEXT PRIMARY KEY,
                name TEXT,
                market_type TEXT
            )
        ''')
        # 新增 is_active 標籤 (若已存在則略過)
        try:
            cursor.execute('ALTER TABLE stock_info ADD COLUMN is_active INTEGER DEFAULT 1')
        except:
            pass

        # 建立除息紀錄表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dividends (
                stock_id TEXT,
                date TIMESTAMP,
                dividend REAL,
                PRIMARY KEY (stock_id, date)
            )
        ''')
        self.conn.commit()

    def clean_inactive_stocks(self, days=14):
        """
        [維護功能] 從資料庫移除超過指定天數(預設14天)沒有交易資料的股票
        這通常代表該股票已經下市、改名或暫停交易
        """
        print("🧹 正在清理資料庫中的殭屍/下市股票...")
        cutoff_date = (datetime.date.today() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
        
        try:
            # 找出久未更新的股票並刪除
            self.conn.execute(f'''
                DELETE FROM stock_info 
                WHERE stock_id IN (
                    SELECT stock_id FROM daily_price 
                    GROUP BY stock_id 
                    HAVING MAX(date) < '{cutoff_date}'
                )
            ''')
            self.conn.commit()
            print(f"✨ 清理完成！已移除超過 {days} 天無交易紀錄的股票。")
        except Exception as e:
            print(f"⚠️ 清理失敗: {e}")

    def get_all_taiwan_tickers(self):
        """
        利用 twstock 取得全台股清單 (上市 + 上櫃)
        """
        print("📜 正在向證交所索取最新股票清單 (透過 twstock)...")
        stock_map = {}
        
        # 遍歷 twstock 的所有代號
        for code, info in twstock.codes.items():
            # 我們只抓「股票」和「ETF」
            if info.type in ['股票', 'ETF']:
                suffix = ""
                if info.market == '上市':
                    suffix = ".TW"
                elif info.market == '上櫃':
                    suffix = ".TWO"
                
                if suffix:
                    stock_map[code] = {
                        'yf_ticker': f"{code}{suffix}",
                        'name': info.name,
                        'market': info.market,
                        'type': info.type
                    }
                    
        print(f"✅ 共取得 {len(stock_map)} 檔上市櫃股票與 ETF")
        return stock_map

    def update_stock_data(self, stock_map):
        """
        [專業版] 雙重濾網更新機制
        濾網 1 (針對一般股): 成交量 > 500 張
        濾網 2 (針對高價股): 成交金額 > 1500 萬台幣 (避免錯殺信譁、大立光)
        """
        total = len(stock_map)
        current = 0
        
        # --- 參數設定區 ---
        # 1. 成交量門檻 (股): 500 張 = 500,000 股
        MIN_VOLUME_SHARES = 500000 
        
        # 2. 成交金額門檻 (元): 1500 萬台幣
        #    (針對高價股，例如股價 3000元 x 5張 = 1500萬，雖然量少但金額大)
        MIN_TURNOVER_TWD = 15000000
        # ------------------
        
        print(f"📥 準備更新 {total} 檔股票 (啟用雙重濾網)...")
        print(f"   👉 保留標準 A: 日均量 > {MIN_VOLUME_SHARES/1000:.0f} 張")
        print(f"   👉 保留標準 B: 日均額 > {MIN_TURNOVER_TWD/10000000:.1f} 千萬 (保護高價股)")
        
        skipped_count = 0
        
        for stock_id, info in stock_map.items():
            current += 1
            ticker = info['yf_ticker']
            stock_name = info['name']
            
            # --- [快篩階段] 下載 5 天數據進行評估 ---
            try:
                # 這裡只下載 5 天，速度很快
                check_df = yf.download(ticker, period="5d", progress=False)
                
                if check_df.empty:
                    continue
                
                # 處理 MultiIndex (yfinance 新版相容性)
                if isinstance(check_df.columns, pd.MultiIndex):
                    check_df.columns = [col[0] for col in check_df.columns]

                # 計算關鍵指標
                # 1. 平均成交量 (股)
                avg_vol = check_df['Volume'].mean()
                
                # 2. 平均成交金額 (元) = 收盤價 * 成交量 (粗估)
                avg_turnover = (check_df['Close'] * check_df['Volume']).mean()
                
                # 滿足 A (量夠大) OR 滿足 B (錢夠多) -> 保留
                is_active = (avg_vol > MIN_VOLUME_SHARES)
                is_high_value = (avg_turnover > MIN_TURNOVER_TWD)
                
                # 若為 ETF 且過於冷門，直接剔除節儉空間與更新時間
                if info['type'] == 'ETF' and not (is_active or is_high_value):
                    skipped_count += 1
                    continue
                    
                is_active_flag = 1 if (is_active or is_high_value) else 0

            except Exception as e:
                print(f"[{current}/{total}] 檢查失敗 {stock_id}: {e}")
                continue
            # ---------------------------

            # --- [正式更新階段] 通過篩選後，才寫入資料庫 ---
            
            # 1. 更新基本資料
            try:
                self.conn.execute(
                    "INSERT OR REPLACE INTO stock_info (stock_id, name, market_type, is_active) VALUES (?, ?, ?, ?)",
                    (stock_id, stock_name, info['market'], is_active_flag)
                )
            except Exception as e:
                pass # 忽略輕微錯誤

            # 2. 決定下載區間
            try:
                last_date_df = pd.read_sql(f"SELECT MAX(date) as last_date FROM daily_price WHERE stock_id='{stock_id}'", self.conn)
                last_date = last_date_df.iloc[0]['last_date']
            except:
                last_date = None
            
            if last_date:
                start_date = (pd.to_datetime(last_date) + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
                if start_date <= datetime.date.today().strftime('%Y-%m-%d'):
                    # 補下載缺漏的日期，並包含除權息與分割
                    df = yf.download(ticker, start=start_date, progress=False, actions=True)
                else:
                    df = pd.DataFrame()
            else:
                print(f"[{current}/{total}] New {stock_id} {stock_name} (download 10y)...")
                df = yf.download(ticker, period="10y", progress=False, actions=True)

            if not df.empty:
                # 3. 寫入股價資料庫
                df = df.reset_index()
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [col[0] for col in df.columns]
                    
                data_to_insert = []
                div_to_insert = []
                for index, row in df.iterrows():
                    dt_str = row['Date'].strftime('%Y-%m-%d')
                    if not pd.isna(row.get('Close', float('nan'))):
                        data_to_insert.append((
                            stock_id, dt_str,
                            row['Open'], row['High'], row['Low'], row['Close'], row['Volume']
                        ))
                    
                    if 'Dividends' in row and not pd.isna(row['Dividends']) and row['Dividends'] > 0:
                        div_to_insert.append((stock_id, dt_str, float(row['Dividends'])))
                
                if data_to_insert:
                    try:
                        self.conn.executemany('''
                            INSERT OR IGNORE INTO daily_price (stock_id, date, open, high, low, close, volume)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', data_to_insert)
                        self.conn.commit()
                    except:
                        pass
                
                if div_to_insert:
                    try:
                        self.conn.executemany('''
                            INSERT OR IGNORE INTO dividends (stock_id, date, dividend)
                            VALUES (?, ?, ?)
                        ''', div_to_insert)
                        self.conn.commit()
                    except:
                        pass

            # 4. 永遠從 yfinance 全量回補除息歷史（INSERT OR REPLACE 確保資料最新且不重複）
            try:
                t_obj = yf.Ticker(ticker)
                divs = t_obj.dividends
                if not divs.empty:
                    history_divs = [
                        (stock_id, d_date.strftime('%Y-%m-%d'), float(d_val))
                        for d_date, d_val in divs.items()
                    ]
                    self.conn.executemany(
                        "INSERT OR REPLACE INTO dividends (stock_id, date, dividend) VALUES (?, ?, ?)",
                        history_divs
                    )
                    self.conn.commit()
            except Exception:
                pass
        
        # 執行後的統計與清理
        print(f"\n 更新完成！")
        print(f"   - 總掃描: {total} 檔")
        print(f"   - 剔除冷門/殭屍股: {skipped_count} 檔")
        print(f"   - 實際入庫: {total - skipped_count} 檔")
        
        self.clean_inactive_stocks()

    def get_stock_data(self, stock_id):
        """從資料庫讀取資料"""
        query = f"SELECT * FROM daily_price WHERE stock_id='{stock_id}' ORDER BY date ASC"
        df = pd.read_sql(query, self.conn)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
        return df
    
    def get_stock_name(self, stock_id):
        """查詢股票名稱 (給 GUI 用)"""
        try:
            cursor = self.conn.execute(f"SELECT name FROM stock_info WHERE stock_id='{stock_id}'")
            result = cursor.fetchone()
            return result[0] if result else stock_id
        except:
            return stock_id

    def backfill_10y(self):
        """
        對 DB 內所有股票，往前補齊到 10 年的行情資料。
        只補「最早日期 > 今天 -10年」的股票，不重複下載已有的日期。
        同時也全量回補除息歷史。
        """
        target_start = (datetime.date.today() - datetime.timedelta(days=365*10)).strftime('%Y-%m-%d')

        # 取得 DB 中所有股票的最早日期
        rows = self.conn.execute(
            "SELECT stock_id, MIN(date) as min_date FROM daily_price GROUP BY stock_id"
        ).fetchall()

        total = len(rows)
        print(f"\n開始回補 10 年行情，共 {total} 檔...")

        # 同時取得 yf_ticker 對照（從 stock_info 拿 stock_id，自行組合後綴）
        info_rows = self.conn.execute(
            "SELECT stock_id, market_type FROM stock_info"
        ).fetchall()
        suffix_map = {}
        for sid, mkt in info_rows:
            if '上市' in (mkt or ''):
                suffix_map[sid] = f"{sid}.TW"
            elif '上櫃' in (mkt or ''):
                suffix_map[sid] = f"{sid}.TWO"
            else:
                suffix_map[sid] = f"{sid}.TW"

        for i, (stock_id, min_date) in enumerate(rows, 1):
            if min_date is None:
                continue
            if min_date <= target_start:
                # 已有 10 年，跳過
                continue

            ticker = suffix_map.get(stock_id, f"{stock_id}.TW")
            print(f"[{i}/{total}] 補齊 {stock_id}  (現有最早: {min_date}, 目標: {target_start})")

            # 下載 target_start ~ min_date 前一天
            end_date = (pd.to_datetime(min_date) - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
            if end_date <= target_start:
                continue
            try:
                df = yf.download(ticker, start=target_start, end=end_date, progress=False, actions=True)
                if df.empty:
                    continue
                df = df.reset_index()
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [col[0] for col in df.columns]

                price_rows, div_rows = [], []
                for _, row in df.iterrows():
                    dt_str = row['Date'].strftime('%Y-%m-%d')
                    if not pd.isna(row.get('Close', float('nan'))):
                        price_rows.append((
                            stock_id, dt_str,
                            row['Open'], row['High'], row['Low'], row['Close'], row['Volume']
                        ))
                    if 'Dividends' in row and not pd.isna(row['Dividends']) and row['Dividends'] > 0:
                        div_rows.append((stock_id, dt_str, float(row['Dividends'])))

                if price_rows:
                    self.conn.executemany(
                        "INSERT OR IGNORE INTO daily_price (stock_id,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)",
                        price_rows
                    )
                if div_rows:
                    self.conn.executemany(
                        "INSERT OR REPLACE INTO dividends (stock_id,date,dividend) VALUES (?,?,?)",
                        div_rows
                    )
                self.conn.commit()

            except Exception as e:
                print(f"  -> 失敗: {e}")
                continue

            # 也順便從 yfinance 全量回補除息（確保不漏）
            try:
                t_obj = yf.Ticker(ticker)
                divs = t_obj.dividends
                if not divs.empty:
                    history_divs = [
                        (stock_id, d.strftime('%Y-%m-%d'), float(v))
                        for d, v in divs.items()
                    ]
                    self.conn.executemany(
                        "INSERT OR REPLACE INTO dividends (stock_id,date,dividend) VALUES (?,?,?)",
                        history_divs
                    )
                    self.conn.commit()
            except:
                pass

        print("\n10 年行情回補完成！")

    def get_weekly_tdcc(self, stock_id, limit=4):
        """取得特定現貨的歷史集保戶數與大戶比例"""
        try:
            df = pd.read_sql(
                "SELECT date, total_holders, large_holders_pct FROM stock_tdcc WHERE stock_id=? ORDER BY date DESC LIMIT ?",
                self.conn, params=(stock_id, limit)
            )
            return df
        except:
            return pd.DataFrame()

# --- 執行區 ---
if __name__ == "__main__":
    import sys
    db = MarketDB()

    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        # 單獨跑回補模式: python core/market_db.py backfill
        db.backfill_10y()
    else:
        # 正常更新模式
        print("正在初始化全台股清單...")
        full_stock_map = db.get_all_taiwan_tickers()
        db.update_stock_data(full_stock_map)
