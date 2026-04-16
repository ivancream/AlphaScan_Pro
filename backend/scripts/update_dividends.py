"""
update_dividends.py — annual dividend backfill from yfinance.

The script is idempotent: it checks the last update timestamp in update_log
and skips if the dividends table was already updated within the last 300 days
(roughly one year), so it's safe to schedule daily.

Run standalone:
    python -m backend.scripts.update_dividends
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

import datetime
import yfinance as yf

from backend.db import queries, writer
from backend.db.writer import log_update_error


# Guard: skip if updated less than 300 days ago
_UPDATE_INTERVAL_DAYS = 300


def _should_run() -> bool:
    try:
        df = queries.get_update_log()
        if df.empty:
            return True
        row = df[df["table_name"] == "dividends"]
        if row.empty:
            return True
        last_ts = row.iloc[0]["last_update"]
        if not last_ts:
            return True
        last_dt = datetime.datetime.fromisoformat(str(last_ts)[:19])
        age_days = (datetime.datetime.now() - last_dt).days
        if age_days < _UPDATE_INTERVAL_DAYS:
            print(
                f"[DividendUpdate] Last updated {age_days} days ago "
                f"(threshold {_UPDATE_INTERVAL_DAYS}). Skipping."
            )
            return False
    except Exception:
        pass
    return True


def run_dividend_update() -> None:
    """Fetch dividends from yfinance for all active stocks and upsert into DuckDB."""
    if not _should_run():
        return

    print("[DividendUpdate] Starting …")
    try:
        stocks_df = queries.get_active_stocks()
        if stocks_df.empty:
            print("[DividendUpdate] No active stocks found. Aborting.")
            return

        total = len(stocks_df)
        all_rows = []

        for i, row in stocks_df.iterrows():
            stock_id = str(row["stock_id"])
            market = str(row.get("market", "TSE"))
            suffix = ".TWO" if market == "OTC" else ".TW"
            ticker = f"{stock_id}{suffix}"

            try:
                t = yf.Ticker(ticker)
                divs = t.dividends
                if divs.empty:
                    continue
                for d_date, d_val in divs.items():
                    all_rows.append((stock_id, d_date.strftime("%Y-%m-%d"), float(d_val)))
            except Exception:
                continue

            if (i + 1) % 100 == 0:
                print(f"  … {i + 1}/{total}")

        n = writer.upsert_dividends(all_rows)
        print(f"[DividendUpdate] Done. Upserted {n} dividend records for {total} stocks.")
    except Exception as exc:
        log_update_error("dividends", str(exc))
        print(f"[DividendUpdate] Error: {exc}")
        raise


if __name__ == "__main__":
    run_dividend_update()
