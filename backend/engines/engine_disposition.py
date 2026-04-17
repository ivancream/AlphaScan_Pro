"""
處置股走勢統計引擎 (v2)
=========================
- 自動從 TWSE / TPEx OpenAPI 抓取「當前」處置清單，並存入本地 DB 累積歷史
- 搜尋個股時，從 DB 取出該股所有歷史處置事件
- 計算處置前 N 天 ~ 出關後 N 天的每日 / 累積漲跌幅
- 多事件彙總統計
"""

import pandas as pd
import numpy as np
import yfinance as yf
import requests
import re
from datetime import date, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
import warnings
import time

warnings.filterwarnings("ignore")

# 盤中浪子／掃描依賴 disposition_events；若僅依 15:05 排程更新，日間 DB 常為空。
_LAST_DISP_OPENAPI_FETCH_MONO: float = 0.0
_DISP_OPENAPI_MIN_INTERVAL_SEC: float = 300.0

# ──────────────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────────────
PRE_DAYS = 2
POST_DAYS = 2
DATA_BUFFER = 30

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()

# DB_PATH 保留供舊版 yfinance 價格查詢路徑（disposition 分析仍用 yfinance）
# 事件儲存改用 DuckDB
from backend.db import writer as _db_writer, queries as _db_queries

try:
    import pandas_market_calendars as mcal
    _TWSE_CAL = mcal.get_calendar("XTAI")
    USE_TWSE_CAL = True
except Exception:
    USE_TWSE_CAL = False


# ──────────────────────────────────────────────────────
# 交易日工具
# ──────────────────────────────────────────────────────
def get_trading_days(start: date, end: date) -> pd.DatetimeIndex:
    if USE_TWSE_CAL:
        schedule = _TWSE_CAL.schedule(start_date=str(start), end_date=str(end))
        return mcal.date_range(schedule, frequency="1D").normalize().tz_localize(None)
    else:
        return pd.bdate_range(start=str(start), end=str(end))


def find_nth_trading_day(ref_date: date, n: int, all_days: pd.DatetimeIndex) -> Optional[date]:
    ref_ts = pd.Timestamp(ref_date)
    if n >= 0:
        candidates = all_days[all_days >= ref_ts]
        if len(candidates) <= n:
            return None
        return candidates[n].date()
    else:
        candidates = all_days[all_days < ref_ts]
        if len(candidates) < abs(n):
            return None
        return candidates[len(candidates) + n].date()


# ──────────────────────────────────────────────────────
# DB 操作  (DuckDB 版)
# ──────────────────────────────────────────────────────

def ensure_table():
    """DuckDB schema 由 init_duckdb() 在啟動時建立，此函式保留相容性。"""
    pass  # no-op: schema managed by backend.db.connection.init_duckdb()


def _mins_display_to_int(mins_label: str, measures: str = "") -> int:
    """將 _parse_mins 回傳的文字標籤或處置條件全文轉成整數分鐘（0 表示未知／無法解析）。"""
    t = (mins_label or "").strip()
    if t.endswith("分") and len(t) > 1:
        prefix = t[:-1]
        if prefix.isdigit():
            return int(prefix)
    mapping = {"5分": 5, "10分": 10, "20分": 20, "45分": 45}
    if t in mapping:
        return mapping[t]
    text = measures or ""
    # 舊版 _parse_mins 曾把「第 N 次處置」標成異常；DB 內 minutes=0 時仍可依 measures 還原
    if "第三次處置" in t or "第三次處置" in text:
        return 45
    if "第二次處置" in t or "第二次處置" in text:
        return 20
    if "第一次處置" in t or "第一次處置" in text:
        return 5
    for pat in (r"(\d+)\s*分鐘", r"每[^\d]*(\d+)\s*分"):
        m = re.search(pat, text)
        if m:
            return int(m.group(1))
    return 0


def save_events_to_db(events: List[Dict]):
    """將處置事件儲存到 DuckDB disposition_events。"""
    if not events:
        return
    rows = []
    for ev in events:
        stock_id = ev.get("stock_id", "")
        disp_start = ev.get("disp_start", "")
        disp_end = ev.get("disp_end") or None
        reason = ev.get("market", "") or ev.get("reason", "")
        mins_int = _mins_display_to_int(str(ev.get("mins") or ""), str(ev.get("measures") or ""))
        rows.append((stock_id, disp_start, disp_end, reason, mins_int))
    try:
        _db_writer.upsert_disposition_events(rows)
    except Exception as exc:
        print(f"[Disposition] save_events_to_db failed: {exc}")


def get_stock_events_from_db(stock_id: str) -> List[Dict]:
    """從 DuckDB 取出某檔個股的所有處置事件。"""
    return _db_queries.get_disposition_events(stock_id)


# ──────────────────────────────────────────────────────
# 爬蟲: 從 TWSE / TPEx OpenAPI 抓取「當前」處置清單
# ──────────────────────────────────────────────────────
def _parse_twse_date(text: str) -> str:
    """嘗試把各種格式轉成 YYYY-MM-DD"""
    text = str(text).strip()
    
    # 民國年格式 (含分隔符): 115/04/02 or 115-04-02
    text_clean = text.replace("/", "-")
    parts = text_clean.split("-")
    if len(parts) == 3:
        try:
            y = int(parts[0])
            m = int(parts[1])
            d = int(parts[2])
            # 如果年份 < 200，判定為民國年
            if y < 200:
                y += 1911
            return f"{y}-{m:02d}-{d:02d}"
        except ValueError:
            pass
    
    # 民國年格式 (無分隔): 1130304 → 2024-03-04
    if len(text) == 7 and text[0] == '1':
        try:
            y = int(text[:3]) + 1911
            m = text[3:5]
            d = text[5:7]
            return f"{y}-{m}-{d}"
        except ValueError:
            pass

    return text_clean


def _parse_period(period_str: str) -> tuple:
    """解析 '115/03/04～115/03/15' 格式的處置區間"""
    parts = period_str.replace("~", "～").split("～")
    if len(parts) == 2:
        start = _parse_twse_date(parts[0].strip())
        end = _parse_twse_date(parts[1].strip())
        return start, end
    return "", ""


def fetch_current_dispositions_and_save() -> List[Dict]:
    """
    從交易所 OpenAPI 抓取「當前正在處置中」的個股名單，
    同時存入本地 DB 進行歷史累積。
    """
    ensure_table()
    all_items = []

    # ── 上市 (TWSE) ──
    try:
        resp = requests.get(
            "https://openapi.twse.com.tw/v1/announcement/punish",
            timeout=8
        )
        if resp.status_code == 200:
            for row in resp.json():
                code = row.get("Code", "").strip()
                name = row.get("Name", "").strip()
                period = row.get("DispositionPeriod", "")
                start, end = _parse_period(period)
                cond = row.get("DispositionMeasures", "")
                mins = _parse_mins(cond)
                
                if code and start and end:
                    ev = {
                        "stock_id": code, "stock_name": name,
                        "disp_start": start, "disp_end": end,
                        "market": "上市", "source": "twse_api",
                        "mins": mins, "measures": cond,
                    }
                    all_items.append(ev)
    except Exception as e:
        print(f"[Disposition] TWSE fetch error: {e}")

    # ── 上櫃 (TPEx) ──
    try:
        resp = requests.get(
            "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information",
            timeout=8
        )
        if resp.status_code == 200:
            for row in resp.json():
                code = row.get("SecuritiesCompanyCode", "").strip()
                name = row.get("CompanyName", "").strip()
                start = _parse_twse_date(row.get("DisposalStartDate", ""))
                end = _parse_twse_date(row.get("DisposalEndDate", ""))
                cond = row.get("DisposalMeasures", "")
                mins = _parse_mins(cond)

                if code and start and end:
                    ev = {
                        "stock_id": code, "stock_name": name,
                        "disp_start": start, "disp_end": end,
                        "market": "上櫃", "source": "tpex_api",
                        "mins": mins, "measures": cond,
                    }
                    all_items.append(ev)
    except Exception as e:
        print(f"[Disposition] TPEx fetch error: {e}")

    # 存入 DB 累積
    save_events_to_db(all_items)
    return all_items


def refresh_disposition_openapi_best_effort(*, force: bool = False) -> None:
    """
    從 TWSE／TPEx OpenAPI 同步「當前處置」到 DuckDB。

    - force=False：5 分鐘內不重複請求（供 enrich 等頻繁路徑）。
    - force=True：每次必拉（例：全市場掃描前，確保撮合分鐘正確）。
    """
    global _LAST_DISP_OPENAPI_FETCH_MONO
    now = time.monotonic()
    if not force and (now - _LAST_DISP_OPENAPI_FETCH_MONO) < _DISP_OPENAPI_MIN_INTERVAL_SEC:
        return
    try:
        fetch_current_dispositions_and_save()
        _LAST_DISP_OPENAPI_FETCH_MONO = time.monotonic()
    except Exception as exc:  # noqa: BLE001
        print(f"[Disposition] refresh_disposition_openapi_best_effort: {exc}")


def _parse_mins(text: str) -> str:
    if not text:
        return '未知'
    # TWSE／櫃買 OpenAPI 常只給「第 N 次處置」，不含「5 分鐘」字面，否則會落到「異常」→ minutes=0 → 盤中永遠顯示「-」
    if "第三次處置" in text:
        return "45分"
    if "第二次處置" in text:
        return "20分"
    if "第一次處置" in text:
        return "5分"
    if '5分鐘' in text or '五分鐘' in text or '5分' in text:
        return '5分'
    if '10分鐘' in text or '十分鐘' in text or '10分' in text:
        return '10分'
    if '20分鐘' in text or '二十分鐘' in text or '20分' in text:
        return '20分'
    if '45分鐘' in text or '四十五分鐘' in text or '45分' in text:
        return '45分'
    match = re.search(r'每[^\d]*(\d+)[^\d]*分', text)
    if match:
        return match.group(1) + '分'
    return '異常/人工管制'


# ──────────────────────────────────────────────────────
# 爬蟲: 嘗試取得特定個股的「歷史」處置紀錄
# ──────────────────────────────────────────────────────
def crawl_stock_disposition_history(stock_id: str) -> List[Dict]:
    """
    嘗試多管道蒐集個股的歷史處置紀錄:
    1. 先從本地 DB 取已知紀錄
    2. 重新抓一次「當前」處置清單 (順便更新 DB)
    3. 回傳所有已知紀錄
    
    隨著系統長期運行，DB 會自然累積越來越完整的歷史。
    """
    ensure_table()
    
    # Step 1: 更新 DB (從 TWSE / TPEx 抓最新的處置清單)
    fetch_current_dispositions_and_save()
    
    # Step 2: 從 DB 拿出這檔標的的所有歷史處置事件
    db_events = get_stock_events_from_db(stock_id)
    
    return db_events


# ──────────────────────────────────────────────────────
# 價格資料
# ──────────────────────────────────────────────────────
def fetch_price(symbol_tw: str, start: str, end: str) -> pd.DataFrame:
    """從 yfinance 抓取價格 (備用)"""
    ticker = symbol_tw if symbol_tw.endswith(".TW") else f"{symbol_tw}.TW"
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df.empty:
        # 嘗試上櫃 .TWO
        ticker_two = symbol_tw.replace(".TW", "") + ".TWO"
        df = yf.download(ticker_two, start=start, end=end, progress=False, auto_adjust=True)
    if df.empty:
        return pd.DataFrame()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close", "Volume"]]



# ──────────────────────────────────────────────────────
# 核心分析
# ──────────────────────────────────────────────────────
def analyze_single_event(
    price_df: pd.DataFrame,
    disp_start: date,
    disp_end: date,
    all_trading_days: pd.DatetimeIndex,
) -> Optional[dict]:
    """分析單一處置事件：處置前 N 天 ~ 出關後 N 天的每日漲跌幅"""
    if price_df.empty:
        return None

    pre_start_date = find_nth_trading_day(disp_start, -(PRE_DAYS), all_trading_days)
    post_end_date = find_nth_trading_day(disp_end, POST_DAYS, all_trading_days)

    if pre_start_date is None or post_end_date is None:
        return None

    # 基準日 = 進關前第 PRE_DAYS 天的前一天收盤
    pre_start_minus1 = find_nth_trading_day(pre_start_date, -1, all_trading_days)
    if pre_start_minus1 is None:
        return None

    ref_ts = pd.Timestamp(pre_start_minus1)
    if ref_ts not in price_df.index:
        candidates = price_df.index[price_df.index <= ref_ts]
        if len(candidates) == 0:
            return None
        ref_close = price_df.loc[candidates[-1], "Close"]
    else:
        ref_close = price_df.loc[ref_ts, "Close"]

    if pd.isna(ref_close) or ref_close == 0:
        return None
    ref_close = float(ref_close)

    # 擷取觀察區間
    mask = (price_df.index >= pd.Timestamp(pre_start_date)) & \
           (price_df.index <= pd.Timestamp(post_end_date))
    seg_df = price_df.loc[mask].copy()
    if seg_df.empty:
        return None

    seg_df["cum_ret"] = (seg_df["Close"] / ref_close - 1) * 100
    seg_df["daily_ret"] = seg_df["Close"].pct_change() * 100
    seg_df.iloc[0, seg_df.columns.get_loc("daily_ret")] = (
        seg_df.iloc[0]["Close"] / ref_close - 1
    ) * 100

    # 分段
    pre_mask = (seg_df.index >= pd.Timestamp(pre_start_date)) & \
               (seg_df.index < pd.Timestamp(disp_start))
    during_mask = (seg_df.index >= pd.Timestamp(disp_start)) & \
                  (seg_df.index <= pd.Timestamp(disp_end))
    post_mask = seg_df.index > pd.Timestamp(disp_end)

    pre_df = seg_df.loc[pre_mask]
    during_df = seg_df.loc[during_mask]
    post_df = seg_df.loc[post_mask].head(POST_DAYS)

    # 建立每日明細表格
    daily_rows = []

    for i, (ts, row) in enumerate(pre_df.iterrows()):
        daily_rows.append({
            "date": ts.strftime("%Y-%m-%d"),
            "phase": f"進關前{PRE_DAYS - i}天",
            "phase_tag": "pre",
            "close": round(float(row["Close"]), 2),
            "daily_ret": round(float(row["daily_ret"]), 2),
            "cum_ret": round(float(row["cum_ret"]), 2),
        })

    for i, (ts, row) in enumerate(during_df.iterrows()):
        daily_rows.append({
            "date": ts.strftime("%Y-%m-%d"),
            "phase": f"處置第{i+1}天",
            "phase_tag": "during",
            "close": round(float(row["Close"]), 2),
            "daily_ret": round(float(row["daily_ret"]), 2),
            "cum_ret": round(float(row["cum_ret"]), 2),
        })

    for i, (ts, row) in enumerate(post_df.iterrows()):
        daily_rows.append({
            "date": ts.strftime("%Y-%m-%d"),
            "phase": f"出關+{i+1}天",
            "phase_tag": "post",
            "close": round(float(row["Close"]), 2),
            "daily_ret": round(float(row["daily_ret"]), 2),
            "cum_ret": round(float(row["cum_ret"]), 2),
        })

    # K 線圖資料
    chart_data = []
    for ts, row in seg_df.iterrows():
        chart_data.append({
            "time": ts.date().isoformat(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "cum_ret": float(row["cum_ret"]),
        })

    return {
        "daily_rows": daily_rows,
        "ref_close": ref_close,
        "chart_data": chart_data,
        "event_dates": {
            "pre_start": pre_start_date.isoformat(),
            "disp_start": disp_start.isoformat(),
            "disp_end": disp_end.isoformat(),
            "post_end": (post_df.index[-1].date() if not post_df.empty else disp_end).isoformat(),
        },
        "disp_days": len(during_df),
    }


def build_summary_stats(all_results: list[dict]) -> list[dict]:
    """
    跨事件彙總統計: 進關前 / 處置第一天 / 處置最後一天 / 出關後
    """
    stat_keys = (
        [f"進關前{PRE_DAYS - i}天" for i in range(PRE_DAYS)] +
        ["處置第1天", "處置最後一天"] +
        [f"出關+{i+1}天" for i in range(POST_DAYS)]
    )

    rows_by_key: dict[str, list[float]] = {k: [] for k in stat_keys}

    for res in all_results:
        label_map = {pt["phase"]: pt for pt in res["daily_rows"]}

        # 特殊處理「處置最後一天」
        during_rows = [r for r in res["daily_rows"] if r["phase_tag"] == "during"]
        if during_rows:
            last = during_rows[-1].copy()
            label_map["處置最後一天"] = last

        for key in stat_keys:
            if key in label_map:
                rows_by_key[key].append(label_map[key]["cum_ret"])

    records = []
    for key, values in rows_by_key.items():
        if not values:
            continue
        arr = np.array(values)
        records.append({
            "node": key,
            "count": len(arr),
            "avg_ret": round(float(arr.mean()), 2),
            "median_ret": round(float(np.median(arr)), 2),
            "win_rate": round(float((arr > 0).mean() * 100), 1),
            "max": round(float(arr.max()), 2),
            "min": round(float(arr.min()), 2),
        })

    return records


# ──────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────
def search_and_analyze(stock_id: str, manual_events: list = None) -> dict:
    """
    主函數：自動搜尋處置紀錄 → 分析
    
    Args:
        stock_id: 台股代號 (e.g. "2603")
        manual_events: 可選的手動事件 [{"start": "2024-03-04", "end": "2024-03-15"}, ...]
    """
    # 1. 自動爬取 + DB 累積
    db_events = crawl_stock_disposition_history(stock_id)

    # 2. 合併手動事件 (如果有)
    events = []
    for ev in db_events:
        events.append({"start": ev["disp_start"], "end": ev["disp_end"]})
    
    if manual_events:
        existing_starts = {e["start"] for e in events}
        for me in manual_events:
            if me["start"] not in existing_starts:
                events.append(me)
                # 也存入 DB
                save_events_to_db([{
                    "stock_id": stock_id,
                    "stock_name": "",
                    "disp_start": me["start"],
                    "disp_end": me["end"],
                    "market": "",
                    "source": "manual",
                }])

    if not events:
        return {
            "symbol": stock_id,
            "events": [],
            "summary": [],
            "found_count": 0,
            "message": "未找到任何處置紀錄，可手動新增。",
        }

    # 3. 排序
    events.sort(key=lambda x: x["start"])

    # 4. 抓取價格
    all_starts = [date.fromisoformat(e["start"]) for e in events]
    all_ends = [date.fromisoformat(e["end"]) for e in events]
    earliest = min(all_starts) - timedelta(days=DATA_BUFFER)
    latest = max(all_ends) + timedelta(days=POST_DAYS * 3 + 10)

    # 從 DuckDB 取本地歷史價格，不足時 fallback yfinance
    try:
        from backend.db.queries import get_price_df as _get_price_df
        price_df = _get_price_df(stock_id, start=str(earliest), end=str(latest))
        if not price_df.empty:
            price_df = price_df[["open", "high", "low", "close", "volume"]].rename(
                columns={"open": "Open", "high": "High", "low": "Low",
                         "close": "Close", "volume": "Volume"}
            )
        else:
            price_df = pd.DataFrame()
    except Exception:
        price_df = pd.DataFrame()
    if price_df.empty or len(price_df) < 10:
        price_df = fetch_price(stock_id, str(earliest), str(latest + timedelta(days=1)))

    if price_df.empty:
        return {
            "symbol": stock_id,
            "events": [],
            "summary": [],
            "found_count": len(events),
            "message": f"找到 {len(events)} 筆處置紀錄，但無法取得價格資料。",
        }

    all_trading_days = get_trading_days(earliest, latest)

    # 5. 逐事件分析
    all_results = []
    for ev in events:
        disp_start = date.fromisoformat(ev["start"])
        disp_end = date.fromisoformat(ev["end"])
        result = analyze_single_event(price_df, disp_start, disp_end, all_trading_days)
        if result:
            all_results.append({
                "disp_start": ev["start"],
                "disp_end": ev["end"],
                "data": result,
            })

    # 6. 彙總統計
    summary = build_summary_stats([r["data"] for r in all_results])

    return {
        "symbol": stock_id,
        "events": all_results,
        "summary": summary,
        "found_count": len(events),
    }


# Alias for scheduler compatibility
fetch_and_save_current = fetch_current_dispositions_and_save
