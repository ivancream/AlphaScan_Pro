# engine_heatmap.py
"""
資金流向：全市場漲跌幅／成交金額 + 三層產業標籤。

【行情資料從哪裡來 — 與 LiveQuoteEngine 的分工】
- 本模組 **不** 呼叫 yfinance、**不** 逐檔呼叫 Shioaji，也 **不** 讀 LiveQuoteEngine
  記憶體快取。每次 API 僅做 **DuckDB 讀取**（daily_prices + stock_info + stock_sectors）。
- 盤中約每 5 分鐘，由 backend.scheduler → intraday._run_intraday_update 將當日 OHLCV
  **批次寫入** daily_prices：
    - 優先：sinopac_session.get_ohlcv_map（內部為 **api.snapshots(contracts)** 分段批次）
    - 降級：yfinance **批次** yf.download（每批最多約 100 檔），同樣非逐檔。
- LiveQuoteEngine 用途為 WebSocket／即時報價 UI（symbol pool 訂閱 tick），與全市場
  資金流向 **解耦**；若改從 LiveQuote 拼全市場，會缺檔且與排程寫庫重複。

1. 行情：DuckDB daily_prices 最新交易日（成交額 = close × volume 股數）。
   漲跌幅若與前收相比異常（>45%），改試當日開→收；仍異常則 change_pct=null，不列入板塊加權平均（避免面額變更等拉歪）。
2. 大／中視野：stock_sectors（證交所 CSV 匯入）+ twstock 後備
3. 小視野：stock_sectors.micro、data/stock_themes.json、內建 theme_data 後備
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.db.connection import DUCKDB_PATH, duck_read
from backend.engines.theme_data import STATIC_SECTOR_MAP
from backend.engines.theme_loader import load_json_theme_micros

# 相容舊 import
__all__ = ["get_heatmap_data", "STATIC_SECTOR_MAP"]

# 與前收相比之漲跌幅若超過此值，多半為面額變更／除權未還原／跨尺度混用，改試當日開收比。
_RAW_CHANGE_OUTLIER_PCT = 45.0
# 當日開→收漲跌幅合理上限（一般現股漲跌停 ±10%，略放寬含盤中誤差與部分商品）。
_INTRADAY_SANITY_MAX_PCT = 15.0


def _heatmap_change_pct(
    prev_close: Optional[float],
    close: float,
    open_px: Optional[float],
) -> tuple[Optional[float], Optional[str]]:
    """
    回傳 (漲跌幅%, 備註)。無法可靠計算時回傳 (None, 'unreliable')，不應納入板塊成交加權平均。

    備註 'intraday' 表示因前後尺度異常改採「當日開盤→收盤」漲跌幅。
    """
    if prev_close is None or prev_close <= 0:
        return 0.0, None

    raw = (close - prev_close) / prev_close * 100.0

    if abs(raw) <= _RAW_CHANGE_OUTLIER_PCT:
        return round(raw, 2), None

    if open_px is not None and open_px > 0:
        intraday = (close - open_px) / open_px * 100.0
        if abs(intraday) <= _INTRADAY_SANITY_MAX_PCT:
            return round(intraday, 2), "intraday"

    return None, "unreliable"


def _get_fallback_tags(macro: str) -> tuple[str, str]:
    if "半導體" in macro:
        return ("傳統晶圓與IC設計", "晶片製造與設計")
    if "光電" in macro:
        return ("光電與面板組件", "顯示與感測技術")
    if "電腦及週邊" in macro:
        return ("傳統PC與代工", "電腦系統裝配")
    if "通信" in macro:
        return ("傳統網通設備", "有線與無線通訊")
    if "電機" in macro:
        return ("電機機械與零組件", "傳動與控制")
    if "金融" in macro:
        return ("金控與保險", "金融服務")
    if "航運" in macro:
        return ("海空運與物流", "運輸服務")
    if "生技醫療" in macro:
        return ("傳統醫療與製藥", "生醫產品與服務")
    return (macro, macro)


def _resolve_labels(
    stock_id: str,
    sector: Optional[dict[str, Any]],
    tw_group: Optional[str],
    theme_json: dict[str, str],
) -> tuple[str, str, str]:
    tw_group = (tw_group or "").strip() or None

    if sector and (sector.get("macro") or "").strip():
        macro = str(sector["macro"]).strip()
    elif tw_group:
        macro = tw_group
    else:
        macro = "其他"

    if sector and (sector.get("meso") or "").strip():
        meso = str(sector["meso"]).strip()
    elif tw_group:
        meso = tw_group
    else:
        meso, _ = _get_fallback_tags(macro)

    if stock_id in theme_json:
        micro = theme_json[stock_id]
    elif sector and (sector.get("micro") or "").strip():
        micro = str(sector["micro"]).strip()
    elif stock_id in STATIC_SECTOR_MAP:
        micro = STATIC_SECTOR_MAP[stock_id][1]
    else:
        micro = meso

    return macro, meso, micro


def get_heatmap_data(metric: str = "change_pct") -> Dict[str, Any]:
    if not DUCKDB_PATH.exists():
        return {
            "date": None,
            "stocks": [],
            "data_freshness": "no_database",
            "as_of_date": None,
            "price_source": None,
            "ingest_path": None,
        }

    try:
        import twstock

        tw_codes = twstock.codes
    except Exception:
        tw_codes = {}

    theme_json = load_json_theme_micros()

    with duck_read() as conn:
        latest_date_row = conn.execute(
            "SELECT MAX(date)::VARCHAR FROM daily_prices"
        ).fetchone()
        if not latest_date_row or not latest_date_row[0]:
            return {
                "date": None,
                "stocks": [],
                "data_freshness": "no_daily_prices",
                "as_of_date": None,
                "price_source": None,
                "ingest_path": None,
            }
        latest_date = latest_date_row[0]

        today_rows = conn.execute(
            "SELECT stock_id, close, volume, open FROM daily_prices WHERE date::VARCHAR = ?",
            [latest_date],
        ).fetchall()

        prev_date_row = conn.execute(
            "SELECT MAX(date)::VARCHAR FROM daily_prices WHERE date::VARCHAR < ?",
            [latest_date],
        ).fetchone()
        prev_date = prev_date_row[0] if prev_date_row else None

        prev_close_map: dict[str, float] = {}
        if prev_date:
            prev_rows = conn.execute(
                "SELECT stock_id, close FROM daily_prices WHERE date::VARCHAR = ?",
                [prev_date],
            ).fetchall()
            prev_close_map = {r[0]: r[1] for r in prev_rows}

        names_rows = conn.execute("SELECT stock_id, name FROM stock_info").fetchall()
        stock_names = {r[0]: r[1] for r in names_rows}

        sector_rows = conn.execute(
            "SELECT stock_id, macro, meso, micro, industry_raw FROM stock_sectors"
        ).fetchall()
        sector_map = {
            r[0]: {
                "macro": r[1],
                "meso": r[2],
                "micro": r[3],
                "industry_raw": r[4],
            }
            for r in sector_rows
        }

    stocks = []
    for stock_id, close, volume, open_price in today_rows:
        if close is None or close <= 0:
            continue

        tw = tw_codes.get(stock_id) if stock_id in tw_codes else None
        tw_group = getattr(tw, "group", None) if tw else None

        sector = sector_map.get(stock_id)
        macro, meso, micro = _resolve_labels(
            stock_id, sector, tw_group, theme_json
        )

        name = stock_names.get(stock_id, stock_id)

        prev_close = prev_close_map.get(stock_id)
        open_f = float(open_price) if open_price is not None else None
        change_pct, cp_note = _heatmap_change_pct(prev_close, float(close), open_f)

        turnover = int(close * volume) if volume else 0

        row: Dict[str, Any] = {
            "ticker": stock_id,
            "name": name,
            "macro": macro,
            "meso": meso,
            "micro": micro,
            "close": round(close, 2),
            "change_pct": change_pct,
            "turnover": turnover,
            "volume": int(volume / 1000) if volume else 0,
        }
        if cp_note:
            row["change_pct_basis"] = cp_note
        if sector and sector.get("industry_raw"):
            row["industry_raw"] = sector["industry_raw"]

        stocks.append(row)

    stocks.sort(key=lambda s: s["turnover"], reverse=True)
    return {
        "date": latest_date,
        "as_of_date": latest_date,
        "data_freshness": "daily_snapshot",
        # 供前端／除錯確認：價量來自庫表，非即時逐檔 API
        "price_source": "duckdb_daily_prices",
        "ingest_path": "scheduler_intraday_batch",
        "stocks": stocks,
    }
