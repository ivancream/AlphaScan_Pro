import sqlite3
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, "data", "holdings.db")

class HoldingsModel:
    def __init__(self, db_file=None):
        if db_file is None:
            # 強制使用絕對路徑避免相對路徑偏差
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.db_file = os.path.join(project_root, "data", "holdings.db")
        else:
            self.db_file = db_file
        
        print(f"[*] HoldingsModel linked to: {self.db_file}")
        self._init_db()

    def _init_db(self):
        """初始化資料庫與資料表"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            # 建立支援多檔 ETF 的 table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS holdings_v2 (
                    etf_code TEXT,
                    date TEXT,
                    code TEXT,
                    name TEXT,
                    shares INTEGER,
                    weight REAL,
                    PRIMARY KEY (etf_code, date, code)
                )
            ''')
            conn.commit()

            # 嘗試把舊的 00981A_holdings.db 移轉過來 (如果有)
            old_db = "00981A_holdings.db"
            if os.path.exists(old_db):
                try:
                    cursor.execute('ATTACH DATABASE ? AS old_db', (old_db,))
                    cursor.execute('''
                        INSERT OR IGNORE INTO holdings_v2 (etf_code, date, code, name, shares, weight)
                        SELECT '00981A', date, code, name, shares, weight FROM old_db.holdings
                    ''')
                    cursor.execute('DETACH DATABASE old_db')
                    conn.commit()
                except Exception as e:
                    print("Migration error:", e)

    def get_yesterday_holdings(self, etf_code, target_date=None):
        if target_date is None:
            target_date = datetime.now().strftime('%Y-%m-%d')
            
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT date FROM holdings_v2 WHERE etf_code = ? AND date < ? ORDER BY date DESC LIMIT 1', (etf_code, target_date))
            row = cursor.fetchone()
            
            if not row:
                return None
                
            prev_date = row[0]
            
            cursor.execute('SELECT code, name, shares, weight FROM holdings_v2 WHERE etf_code = ? AND date = ?', (etf_code, prev_date))
            rows = cursor.fetchall()
            
            holdings = {}
            for row in rows:
                code, name, shares, weight = row
                holdings[code] = {
                    "name": name,
                    "shares": shares,
                    "weight": weight
                }
            return holdings

    def save_holdings(self, etf_code, holdings, target_date=None):
        if not holdings:
            return
            
        if target_date is None:
            target_date = datetime.now().strftime('%Y-%m-%d')
            
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            for code, data in holdings.items():
                cursor.execute('''
                    INSERT OR REPLACE INTO holdings_v2 (etf_code, date, code, name, shares, weight)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (etf_code, target_date, code, data['name'], data['shares'], data['weight']))
            conn.commit()
