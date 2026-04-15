"""
cb_crawler.py — 可轉債資料爬蟲（重寫版）

資料策略：
  基本資料 (TWSE 上市)：
    - 主要: TWSE /zh/bond/cbBook HTML table parse
    - 備援: TWSE opendata t187ap03_L / t187ap03_O CSV
  基本資料 (TPEX 上櫃)：
    - 主要: TPEX /web/bond/CB/search/result.php HTML
    - 備援: 靜態範例
  行情：
    - 主要: TWSE t187ap03 系列 CSV（按日）
    - 備援: 從 goodinfo 爬

套利報酬率 = (轉換價值 / CB現價 - 1) × 100%
轉換價值   = (現貨股價 / 轉換價格) × 100
"""
import sqlite3
import requests
import pandas as pd
import datetime
import time
import os
import re

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CB_DB_PATH = os.path.join(BASE_DIR, "data", "cb.db")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.twse.com.tw/",
}

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ──────────────────────────────────────────────
#  SQLite DB
# ──────────────────────────────────────────────

class CBDB:
    def __init__(self):
        self.conn = sqlite3.connect(CB_DB_PATH, check_same_thread=False, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS cb_info (
                cb_id         TEXT PRIMARY KEY,
                stock_id      TEXT,
                name          TEXT,
                issue_date    TEXT,
                maturity_date TEXT,
                conv_price    REAL,
                face_value    REAL DEFAULT 100,
                is_secured    INTEGER DEFAULT 0,
                coupon_rate   REAL,
                market        TEXT,
                put_date      TEXT,
                put_price     REAL,
                credit_rating TEXT,
                updated_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS cb_daily (
                cb_id   TEXT,
                date    TEXT,
                open    REAL,
                high    REAL,
                low     REAL,
                close   REAL,
                volume  REAL,
                amount  REAL,
                PRIMARY KEY (cb_id, date)
            );

            CREATE TABLE IF NOT EXISTS stock_fundamentals (
                stock_id TEXT PRIMARY KEY,
                debt_ratio REAL,
                quick_ratio REAL,
                updated_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_cb_daily_date ON cb_daily(date);
            CREATE INDEX IF NOT EXISTS idx_cb_info_stock ON cb_info(stock_id);
        """)
        self.conn.commit()

    def upsert_cb_info(self, rows: list):
        if not rows:
            return
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.executemany("""
            INSERT OR REPLACE INTO cb_info
                (cb_id, stock_id, name, issue_date, maturity_date,
                 conv_price, face_value, is_secured, coupon_rate, market,
                 put_date, put_price, credit_rating, updated_at)
            VALUES
                (:cb_id, :stock_id, :name, :issue_date, :maturity_date,
                 :conv_price, :face_value, :is_secured, :coupon_rate, :market,
                 :put_date, :put_price, :credit_rating, :updated_at)
        """, [{
            **r,
            "put_date": r.get("put_date"),
            "put_price": r.get("put_price"),
            "credit_rating": r.get("credit_rating"),
            "updated_at": now
        } for r in rows])
        self.conn.commit()

    def upsert_stock_fundamentals(self, rows: list):
        if not rows:
            return
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.executemany("""
            INSERT OR REPLACE INTO stock_fundamentals (stock_id, debt_ratio, quick_ratio, updated_at)
            VALUES (:stock_id, :debt_ratio, :quick_ratio, :updated_at)
        """, [{**r, "updated_at": now} for r in rows])
        self.conn.commit()

    def upsert_cb_daily(self, rows: list):
        if not rows:
            return
        self.conn.executemany("""
            INSERT OR REPLACE INTO cb_daily
                (cb_id, date, open, high, low, close, volume, amount)
            VALUES
                (:cb_id, :date, :open, :high, :low, :close, :volume, :amount)
        """, rows)
        self.conn.commit()

    def get_latest_daily_date(self):
        row = self.conn.execute("SELECT MAX(date) FROM cb_daily").fetchone()
        return row[0] if row else None

    def get_all_cb_ids(self) -> list:
        return [r[0] for r in self.conn.execute("SELECT cb_id FROM cb_info").fetchall()]

    def get_cb_info_df(self) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM cb_info", self.conn)

    def count_info(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM cb_info").fetchone()[0]

    def count_daily(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM cb_daily").fetchone()[0]

    def close(self):
        self.conn.close()


# ──────────────────────────────────────────────
#  TWSE 上市 CB 基本資料（HTML table）
# ──────────────────────────────────────────────

def fetch_twse_cb_list() -> list:
    """
    主要：TWSE /zh/bond/cbBook 頁面 HTML table
    備援：opendata t187ap03 CSV
    """
    results = _try_twse_html_table()
    if results:
        print(f"[TWSE] HTML table 解析成功，{len(results)} 筆")
        return results

    results = _try_twse_t187ap03_csv()
    if results:
        print(f"[TWSE] t187ap03 CSV 解析成功，{len(results)} 筆")
        return results

    print("[TWSE] 所有方法失敗，使用靜態範例資料")
    return _get_fallback_cb_list("上市")


def _try_twse_html_table() -> list:
    """解析 TWSE 上市 CB 基本資料 HTML 頁面"""
    urls = [
        "https://www.twse.com.tw/zh/bond/cbBook",
        "https://www.twse.com.tw/zh/bonds/cbBook",
        "https://www.twse.com.tw/rwd/zh/bond/cbBook",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200 or len(r.text) < 2000:
                continue
            r.encoding = "utf-8"
            tables = pd.read_html(r.text, thousands=",", flavor="html5lib")
            for df in tables:
                if len(df) < 3:
                    continue
                results = []
                for _, row in df.iterrows():
                    row_str = " ".join(str(v) for v in row.values)
                    # 判斷是否為 CB 資料列（要有數字代號）
                    cb_id = None
                    for v in row.values:
                        v_str = str(v).strip().replace(",", "")
                        if re.match(r"^\d{4,6}$", v_str):
                            cb_id = v_str
                            break
                    if not cb_id:
                        continue

                    # 找轉換價格（通常是最後幾個數字欄位）
                    nums = []
                    for v in row.values:
                        f = _parse_float(v)
                        if f is not None and f > 0:
                            nums.append(f)

                    conv_price = nums[-1] if nums else None
                    stock_id = _extract_stock_id(cb_id)

                    # 名稱
                    name = cb_id
                    for v in row.values:
                        vs = str(v).strip()
                        if re.search(r"[\u4e00-\u9fff]", vs) and len(vs) >= 2:
                            name = vs
                            break

                    results.append({
                        "cb_id": cb_id,
                        "stock_id": stock_id,
                        "name": name,
                        "issue_date": None,
                        "maturity_date": None,
                        "conv_price": conv_price,
                        "face_value": 100.0,
                        "is_secured": 0,
                        "coupon_rate": None,
                        "market": "上市",
                    })
                if len(results) > 5:
                    return results
        except Exception as e:
            print(f"[TWSE HTML] {url[-40:]}: {e}")
    return []


def _try_twse_t187ap03_csv() -> list:
    """
    TWSE 上市 CB 基本資料 opendata CSV 替代方案。
    t187ap03_L = 不含利率; t187ap03_O = 帶選擇權
    """
    url = "https://www.twse.com.tw/rwd/zh/bond/t187ap03_L?response=csv"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200 or len(r.text) < 500:
            # 試另一個
            url2 = "https://openapi.twse.com.tw/v1/exchangeReport/t187ap03_L"
            r = requests.get(url2, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                return []
            data = r.json()
            if not data:
                return []
            return _parse_t187(pd.DataFrame(data))

        r.encoding = "utf-8"

        # CSV 可能有幾行頭部說明，找真正的 header
        lines = r.text.splitlines()
        header_idx = 0
        for i, l in enumerate(lines):
            if "債券" in l or "代號" in l or "Bond" in l:
                header_idx = i
                break

        from io import StringIO
        csv_text = "\n".join(lines[header_idx:])
        df = pd.read_csv(StringIO(csv_text), on_bad_lines="skip")
        return _parse_t187(df)
    except Exception as e:
        print(f"[t187ap03] {e}")
        return []


def _parse_t187(df: pd.DataFrame) -> list:
    results = []
    for _, row in df.iterrows():
        vals = list(row.values)
        cb_id  = None
        for v in vals:
            s = str(v).strip().replace(",","")
            if re.match(r"^\d{4,6}$", s):
                cb_id = s
                break
        if not cb_id:
            continue

        nums = [_parse_float(v) for v in vals if _parse_float(v) is not None and _parse_float(v) > 0]
        # 名稱（中文字）
        name = next((str(v).strip() for v in vals if re.search(r"[\u4e00-\u9fff]", str(v)) and len(str(v).strip()) >= 2), cb_id)
        # 轉換價格（通常是稍大的數，在 20~2000 之間）
        conv_price = next((n for n in nums if 10 < n < 5000 and n != _parse_float(cb_id)), None)
        results.append({
            "cb_id": cb_id,
            "stock_id": _extract_stock_id(cb_id),
            "name": name,
            "issue_date": None,
            "maturity_date": None,
            "conv_price": conv_price,
            "face_value": 100.0,
            "is_secured": 0,
            "coupon_rate": None,
            "market": "上市",
        })
    return results


# ──────────────────────────────────────────────
#  TPEX 上櫃 CB 基本資料
# ──────────────────────────────────────────────

def fetch_tpex_cb_list() -> list:
    """TPEX 上櫃 CB 基本資料"""
    # 試 HTML table
    try:
        r = requests.get(
            "https://www.tpex.org.tw/web/bond/CB/search/result.php?l=zh-tw&search_type=ALL",
            headers={**HEADERS, "Referer": "https://www.tpex.org.tw/"},
            timeout=15
        )
        if r.status_code == 200 and len(r.text) > 2000:
            r.encoding = "utf-8"
            tables = pd.read_html(r.text, thousands=",", flavor="html5lib")
            for df in tables:
                if len(df) < 3:
                    continue
                results = []
                for _, row in df.iterrows():
                    cb_id = None
                    for v in row.values:
                        s = str(v).strip().replace(",","")
                        if re.match(r"^\d{4,6}$", s):
                            cb_id = s
                            break
                    if not cb_id:
                        continue
                    name = next((str(v).strip() for v in row.values if re.search(r"[\u4e00-\u9fff]", str(v))), cb_id)
                    nums = [_parse_float(v) for v in row.values if _parse_float(v) is not None and _parse_float(v) > 0]
                    conv_price = next((n for n in nums if 5 < n < 5000), None)
                    results.append({
                        "cb_id": cb_id,
                        "stock_id": _extract_stock_id(cb_id),
                        "name": name,
                        "issue_date": None,
                        "maturity_date": None,
                        "conv_price": conv_price,
                        "face_value": 100.0,
                        "is_secured": 0,
                        "coupon_rate": None,
                        "market": "上櫃",
                    })
                if len(results) > 3:
                    print(f"[TPEX] HTML table 解析成功，{len(results)} 筆")
                    return results
    except Exception as e:
        print(f"[TPEX HTML] {e}")

    print("[TPEX] 使用靜態範例資料")
    return _get_fallback_cb_list("上櫃")


# ──────────────────────────────────────────────
#  CB 日行情 — TWSE t187ap03 格式 CSV
# ──────────────────────────────────────────────

def fetch_twse_cb_daily_by_date(date_str: str) -> list:
    """
    抓 TWSE CB 當日行情（format: YYYYMMDD）。
    嘗試多種格式。
    """
    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

    # 試 JSON
    for url in [
        f"https://www.twse.com.tw/rwd/zh/cbBook/CB_TRAN?response=json&date={date_str}",
        f"https://www.twse.com.tw/zh/bond/CB_TRAN?response=json&date={date_str}",
        f"https://www.twse.com.tw/exchangeReport/CB_TRAN?response=json&date={date_str}",
    ]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data.get("stat") == "OK" and data.get("data"):
                    fields = data["fields"]
                    results = []
                    for row in data["data"]:
                        d = dict(zip(fields, row))
                        cb_id = str(d.get("債券代號","")).strip()
                        if not cb_id:
                            continue
                        results.append({
                            "cb_id":  cb_id,
                            "date":   date_fmt,
                            "open":   _parse_float(_find_field(d, ["開盤價","開盤"])),
                            "high":   _parse_float(_find_field(d, ["最高價","最高"])),
                            "low":    _parse_float(_find_field(d, ["最低價","最低"])),
                            "close":  _parse_float(_find_field(d, ["收盤價","成交價","收盤","均價"])),
                            "volume": _parse_float(_find_field(d, ["成交量","成交張數","張數"])),
                            "amount": _parse_float(_find_field(d, ["成交金額","金額"])),
                        })
                    if results:
                        return results
        except Exception:
            pass

    # 試 opendata CSV
    for url in [
        f"https://www.twse.com.tw/rwd/zh/cbBook/t187ap03_L?response=csv&date={date_str}",
        f"https://openapi.twse.com.tw/v1/exchangeReport/t187ap03_L?date={date_str}",
    ]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200 and len(r.text) > 200:
                if r.headers.get("Content-Type","").startswith("application/json"):
                    data = r.json()
                    if isinstance(data, list) and data:
                        results = _parse_daily_json(data, date_fmt)
                        if results:
                            return results
                else:
                    # CSV
                    from io import StringIO
                    try:
                        df = pd.read_csv(StringIO(r.text), on_bad_lines="skip")
                        results = _parse_daily_df(df, date_fmt)
                        if results:
                            return results
                    except Exception:
                        pass
        except Exception:
            pass

    return []


def _parse_daily_json(data: list, date_fmt: str) -> list:
    results = []
    for d in data:
        cb_id = str(d.get("Code") or d.get("債券代號") or "").strip()
        if not cb_id or not cb_id.isdigit():
            continue
        results.append({
            "cb_id":  cb_id,
            "date":   date_fmt,
            "open":   _parse_float(d.get("Open") or d.get("開盤價")),
            "high":   _parse_float(d.get("High") or d.get("最高價")),
            "low":    _parse_float(d.get("Low") or d.get("最低價")),
            "close":  _parse_float(d.get("Close") or d.get("收盤價") or d.get("成交價")),
            "volume": _parse_float(d.get("Volume") or d.get("成交量")),
            "amount": _parse_float(d.get("Amount") or d.get("成交金額")),
        })
    return results


def _parse_daily_df(df: pd.DataFrame, date_fmt: str) -> list:
    results = []
    for _, row in df.iterrows():
        cb_id = None
        for v in row.values:
            s = str(v).strip().replace(",","")
            if re.match(r"^\d{4,6}$", s):
                cb_id = s
                break
        if not cb_id:
            continue
        vals = [_parse_float(v) for v in row.values]
        nums = [v for v in vals if v is not None and v > 0]
        results.append({
            "cb_id":  cb_id,
            "date":   date_fmt,
            "open":   nums[0] if len(nums)>0 else None,
            "high":   nums[1] if len(nums)>1 else None,
            "low":    nums[2] if len(nums)>2 else None,
            "close":  nums[3] if len(nums)>3 else None,
            "volume": nums[4] if len(nums)>4 else None,
            "amount": nums[5] if len(nums)>5 else None,
        })
    return results


# ──────────────────────────────────────────────
#  整合更新入口
# ──────────────────────────────────────────────

def update_cb_info(db: CBDB, progress_callback=None) -> int:
    if progress_callback:
        progress_callback("正在抓取 TWSE 上市 CB 基本資料...")
    twse_rows = fetch_twse_cb_list()
    time.sleep(0.5)

    if progress_callback:
        progress_callback("正在抓取 TPEX 上櫃 CB 基本資料...")
    tpex_rows = fetch_tpex_cb_list()

    all_rows = twse_rows + tpex_rows
    if all_rows:
        db.upsert_cb_info(all_rows)
    return len(all_rows)


def update_cb_daily(db: CBDB, days_back: int = 30, progress_callback=None) -> int:
    """更新 CB 日行情（最近 N 個工作日）"""
    today = datetime.date.today()
    total = 0
    tried = 0

    for i in range(days_back * 2):
        if tried >= days_back:
            break
        d = today - datetime.timedelta(days=i)
        if d.weekday() >= 5:   # 跳週末
            continue
        tried += 1
        date_str = d.strftime("%Y%m%d")

        if progress_callback and tried % 3 == 0:
            progress_callback(f"抓取 CB 日行情 {d} ...")

        rows = fetch_twse_cb_daily_by_date(date_str)
        if rows:
            db.upsert_cb_daily(rows)
            total += len(rows)
        time.sleep(0.3)

    return total


def update_stock_fundamentals(db: CBDB, progress_callback=None) -> int:
    """用 yfinance 更新可轉債對應現貨的財報指標 (負債比、速動比)"""
    try:
        import yfinance as yf
    except ImportError:
        print("[yf] yfinance 未安裝")
        return 0

    df = db.get_cb_info_df()
    if df.empty:
        return 0

    stock_ids = df["stock_id"].dropna().unique()
    rows = []
    
    for i, sid in enumerate(stock_ids):
        if not sid or not str(sid).isdigit():
            continue
            
        if progress_callback and i % 10 == 0:
            progress_callback(f"[{i+1}/{len(stock_ids)}] 取得現貨 {sid} 基本面 ...")

        try:
            ticker = yf.Ticker(f"{sid}.TW")
            info = ticker.info
            
            # yf.info 可能為空，如果沒有 TW 就試 TWO
            if not info or "quickRatio" not in info:
                ticker = yf.Ticker(f"{sid}.TWO")
                info = ticker.info

            quick_ratio = info.get("quickRatio")
            # Yahoo finance 的 debtToEquity 實際單位是 %，例如 13.018 代表 13.018%
            # D/E ratio = D/E. Debt ratio = D / (D+E).  如果 D/E 是 13%, 那 D比例大約是 11%
            # 為了符合台灣常見的「負債佔資產比率」(%)，換算: debt_ratio (%) = (D/E) / (1 + D/E) * 100
            # 注意 yf 提供的是 D/E * 100 (百分比形式)
            de_pct = info.get("debtToEquity")
            debt_ratio = None
            if de_pct is not None:
                de_ratio = float(de_pct) / 100.0
                debt_ratio = round((de_ratio / (1 + de_ratio)) * 100, 2)
            
            # 台灣 Quick Ratio 通常用 % 表示, 如果 yf 給 1.5, 就是 150%
            if quick_ratio is not None:
                quick_ratio = round(float(quick_ratio) * 100, 2)

            if quick_ratio is not None or debt_ratio is not None:
                rows.append({
                    "stock_id": str(sid),
                    "debt_ratio": debt_ratio,
                    "quick_ratio": quick_ratio
                })
        except Exception as e:
            pass
            
        time.sleep(0.1)

    if rows:
        db.upsert_stock_fundamentals(rows)
        
    if progress_callback:
        progress_callback(f"基本面更新完成，共 {len(rows)} 檔")

    return len(rows)



# ──────────────────────────────────────────────
#  查詢（UI 用）
# ──────────────────────────────────────────────

def get_cb_with_latest_price(db: CBDB) -> pd.DataFrame:
    sql = """
    SELECT
        i.cb_id, i.stock_id, i.name,
        i.conv_price, i.maturity_date, i.issue_date,
        i.is_secured, i.coupon_rate, i.market,
        i.put_date, i.put_price, i.credit_rating,
        d.date  AS price_date,
        d.close AS cb_close,
        d.volume,
        sf.debt_ratio, sf.quick_ratio
    FROM cb_info i
    LEFT JOIN cb_daily d ON i.cb_id = d.cb_id
        AND d.date = (
            SELECT MAX(d2.date) FROM cb_daily d2 WHERE d2.cb_id = i.cb_id
        )
    LEFT JOIN stock_fundamentals sf ON i.stock_id = sf.stock_id
    ORDER BY i.cb_id
    """
    try:
        return pd.read_sql(sql, db.conn)
    except Exception as e:
        print(f"[get_cb_with_latest_price] {e}")
        return pd.DataFrame()


def get_cb_history(db: CBDB, cb_id: str, days: int = 90) -> pd.DataFrame:
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    try:
        df = pd.read_sql(
            f"SELECT date, open, high, low, close, volume FROM cb_daily "
            f"WHERE cb_id='{cb_id}' AND date>='{cutoff}' ORDER BY date ASC",
            db.conn
        )
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
        return df
    except Exception as e:
        return pd.DataFrame()


# ──────────────────────────────────────────────
#  套利計算
# ──────────────────────────────────────────────

def calc_arbitrage(cb_price, stock_price, conv_price):
    """
    套利報酬率 = (轉換價值 / CB現價 - 1) × 100%
    轉換價值 = (現貨股價 / 轉換價格) × 100

    負值 → CB 溢價（比轉換價值貴）→ 主力強勢鎖倉
    正值 → CB 折價 → 有套利空間
    """
    try:
        if not conv_price or not cb_price or not stock_price:
            return None
        conv_value = (float(stock_price) / float(conv_price)) * 100
        return round((conv_value / float(cb_price) - 1) * 100, 2)
    except Exception:
        return None


def calc_premium(cb_price, stock_price, conv_price):
    arb = calc_arbitrage(cb_price, stock_price, conv_price)
    return round(-arb, 2) if arb is not None else None

def calc_ytp(cb_price, put_price, put_date_str):
    """
    計算持有至賣回日的年化殖利率 (Yield To Put)
    YTP = (賣回價 / CB買賣價) ^ (365 / 距賣回日) - 1
    """
    try:
        if not cb_price or not put_price or not put_date_str:
            return None
        
        # 轉換 put_date_str (YYYY-MM-DD) 為 datetime
        put_date = datetime.datetime.strptime(str(put_date_str)[:10], "%Y-%m-%d").date()
        today = datetime.date.today()
        days_to_put = (put_date - today).days
        
        if days_to_put <= 0:
            return None
            
        ytp = ((float(put_price) / float(cb_price)) ** (365.0 / days_to_put)) - 1
        return round(ytp * 100, 2)
    except Exception:
        return None


# ──────────────────────────────────────────────
#  靜態備援資料
# ──────────────────────────────────────────────

def _get_fallback_cb_list(market: str) -> list:
    """當所有 API 都失敗時的示範資料"""
    if market == "上市":
        return [
            {"cb_id":"13651","stock_id":"1365","name":"中租-KY五",
             "issue_date":"2022-09-01","maturity_date":"2027-09-01",
             "conv_price":250.0,"face_value":100,"is_secured":0,"coupon_rate":0.0,"market":"上市",
             "put_date": "2025-09-01", "put_price": 100.0, "credit_rating": "5"},
            {"cb_id":"24011","stock_id":"2401","name":"凌陽一",
             "issue_date":"2023-03-01","maturity_date":"2027-03-01",
             "conv_price":55.0,"face_value":100,"is_secured":0,"coupon_rate":0.0,"market":"上市",
             "put_date": "2026-03-01", "put_price": 100.5, "credit_rating": "6"},
            {"cb_id":"23031","stock_id":"2303","name":"聯電一",
             "issue_date":"2024-01-01","maturity_date":"2028-01-01",
             "conv_price":48.0,"face_value":100,"is_secured":0,"coupon_rate":0.0,"market":"上市",
             "put_date": "2027-01-01", "put_price": 102.5, "credit_rating": "7"},
            {"cb_id":"24541","stock_id":"2454","name":"聯發科一",
             "issue_date":"2023-06-01","maturity_date":"2027-06-01",
             "conv_price":800.0,"face_value":100,"is_secured":0,"coupon_rate":0.0,"market":"上市",
             "put_date": "2026-06-01", "put_price": 101.5, "credit_rating": "8"},
        ]
    else:
        return [
            {"cb_id":"67171","stock_id":"6717","name":"岱宇一",
             "issue_date":"2022-06-01","maturity_date":"2026-06-01",
             "conv_price":58.0,"face_value":100,"is_secured":0,"coupon_rate":0.0,"market":"上櫃",
             "put_date": "2025-06-01", "put_price": 100.0, "credit_rating": "6"},
            {"cb_id":"83591","stock_id":"8359","name":"金居一",
             "issue_date":"2023-01-01","maturity_date":"2027-01-01",
             "conv_price":32.0,"face_value":100,"is_secured":0,"coupon_rate":0.0,"market":"上櫃",
             "put_date": "2026-01-01", "put_price": 101.0, "credit_rating": "7"},
        ]


# ──────────────────────────────────────────────
#  工具函式
# ──────────────────────────────────────────────

def _extract_stock_id(cb_id: str) -> str:
    s = re.sub(r"[^\d]", "", cb_id)
    return s[:4] if len(s) >= 4 else s


def _parse_float(val):
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _find_field(d: dict, candidates: list):
    for k in candidates:
        v = d.get(k)
        if v not in (None, "", "--", "---", "N/A"):
            return v
    return None


def _normalize_date(val):
    if not val:
        return None
    s = str(val).strip()
    m = re.match(r"^(\d{2,3})[/\-.](\d{1,2})[/\-.](\d{1,2})$", s)
    if m:
        y = int(m.group(1))
        if y < 200:
            y += 1911
        return f"{y}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m2 = re.match(r"^(\d{8})$", s)
    if m2:
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s[:10] if len(s) >= 10 else s


# ──────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────

if __name__ == "__main__":
    db = CBDB()
    print("=== 更新 CB 基本資料 ===")
    n = update_cb_info(db, progress_callback=print)
    print(f"寫入 {n} 筆\n")
    print("=== 更新近 5 日行情 ===")
    n2 = update_cb_daily(db, days_back=5, progress_callback=print)
    print(f"寫入 {n2} 筆\n")
    df = get_cb_with_latest_price(db)
    print(df.head(15).to_string())
