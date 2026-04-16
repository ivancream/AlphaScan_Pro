"""
refresh_universe.py — refresh stock universe (stock_info) from twstock + yfinance.

Called by scheduler.py every Monday 03:00.
Can also be run standalone:
    python -m backend.scripts.refresh_universe
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

import datetime
import yfinance as yf
import twstock

from backend.db import writer
from backend.db.writer import log_update_error


def run_universe_refresh() -> None:
    """
    Fetch Taiwan stock universe via twstock, filter by activity using yfinance,
    then upsert into stock_info.
    """
    print("[UniverseRefresh] Starting …")
    try:
        stock_map: dict[str, dict] = {}
        for code, info in twstock.codes.items():
            if info.type not in ("股票", "ETF"):
                continue
            if info.market == "上市":
                market = "TSE"
                suffix = ".TW"
            elif info.market == "上櫃":
                market = "OTC"
                suffix = ".TWO"
            else:
                continue
            stock_map[code] = {
                "name": info.name,
                "market": market,
                "yf_ticker": f"{code}{suffix}",
            }

        print(f"[UniverseRefresh] {len(stock_map)} candidates from twstock")

        rows = []
        skipped = 0
        min_vol = 500_000       # 500 張
        min_turnover = 15_000_000  # 1500 萬台幣

        for code, info in stock_map.items():
            try:
                df = yf.download(info["yf_ticker"], period="5d", progress=False)
                if df.empty:
                    skipped += 1
                    continue
                if hasattr(df.columns, "get_level_values"):
                    df.columns = df.columns.get_level_values(0)
                avg_vol = float(df["Volume"].mean()) if "Volume" in df.columns else 0
                avg_turnover = float((df["Close"] * df["Volume"]).mean()) if "Close" in df.columns else 0
                is_active = (avg_vol > min_vol) or (avg_turnover > min_turnover)
            except Exception:
                is_active = True  # keep on error to avoid false negatives

            rows.append((code, info["name"], info["market"], is_active))

        n = writer.upsert_stock_info(rows)
        print(f"[UniverseRefresh] Done. Updated {n} stocks, skipped {skipped} inactive.")
    except Exception as exc:
        log_update_error("stock_info", str(exc))
        print(f"[UniverseRefresh] Error: {exc}")
        raise


if __name__ == "__main__":
    run_universe_refresh()
