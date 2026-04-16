"""
build_correlations.py — rebuild Pearson correlation matrix from daily_prices.

Computes pairwise rolling-window correlation for all active stocks with
sufficient history, then upserts the top-N peers per stock into the
correlations table.

Run standalone:
    python -m backend.scripts.build_correlations

Called by scheduler.py every Saturday 03:00.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

import datetime

import numpy as np
import pandas as pd

from backend.db import queries, writer
from backend.db.writer import log_update_error


LOOKBACK_DAYS = 252   # ~1 trading year
MIN_OVERLAP = 60      # minimum shared trading days required
TOP_N_PEERS = 50      # store top-50 correlations per stock


def run_correlation_build() -> None:
    print("[CorrelationBuild] Starting …")
    try:
        # Load price history
        print("[CorrelationBuild] Loading price data …")
        df_all = queries.get_price_df_all(cutoff_days=LOOKBACK_DAYS + 30)

        if df_all.empty:
            print("[CorrelationBuild] No price data. Aborting.")
            return

        # Pivot to wide format: index=date, columns=stock_id, values=close
        df_pivot = df_all.pivot_table(
            index="date", columns="stock_id", values="close", aggfunc="last"
        )
        df_pivot = df_pivot.sort_index()

        # Keep only stocks with enough history
        valid_cols = df_pivot.columns[df_pivot.count() >= MIN_OVERLAP]
        df_pivot = df_pivot[valid_cols]
        print(f"[CorrelationBuild] {len(valid_cols)} stocks with ≥{MIN_OVERLAP} days data")

        # Compute log returns
        returns = np.log(df_pivot / df_pivot.shift(1)).dropna(how="all")

        # Build pairwise correlations
        print("[CorrelationBuild] Computing correlation matrix …")
        corr_matrix = returns.corr()

        # Extract top-N peers per stock (exclude self)
        rows = []
        calc_date = datetime.date.today().isoformat()
        stocks = list(corr_matrix.columns)

        for stock_id in stocks:
            col = corr_matrix[stock_id].drop(labels=[stock_id], errors="ignore")
            col = col.dropna()
            if col.empty:
                continue
            top = col.nlargest(TOP_N_PEERS)
            for peer_id, corr_val in top.items():
                rows.append(
                    {
                        "stock_id": stock_id,
                        "peer_id": str(peer_id),
                        "correlation": round(float(corr_val), 6),
                    }
                )

        df_out = pd.DataFrame(rows)
        n = writer.upsert_correlations(df_out, calc_date)
        print(f"[CorrelationBuild] Done. {n} correlation pairs stored (calc_date={calc_date}).")
    except Exception as exc:
        log_update_error("correlations", str(exc))
        print(f"[CorrelationBuild] Error: {exc}")
        raise


if __name__ == "__main__":
    run_correlation_build()
