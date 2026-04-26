"""
Phase 2: Walk-forward rule mining -> JSON output of surviving IF-THEN rules.

Reads training_data.parquet produced by 03_build_dataset.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# backend/scripts/ml_research/this_file.py -> repo root is 3 levels up
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.engines.ml_pipeline.rule_miner import (  # noqa: E402
    dump_rules_json,
    run_wfo_rule_mining,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="WFO decision-tree rule mining")
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "data" / "ml_datasets" / "training_data.parquet",
        help="Training parquet from 03_build_dataset",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "ml_datasets" / "wfo_surviving_rules.json",
        help="Output JSON path",
    )
    parser.add_argument("--forward-return-days", type=int, default=5)
    parser.add_argument(
        "--train-days",
        type=int,
        default=504,
        help="In-sample length in unique trading dates (~2y)",
    )
    parser.add_argument(
        "--test-days",
        type=int,
        default=66,
        help="OOS length in unique trading dates (~3mo)",
    )
    parser.add_argument(
        "--market-excess",
        type=float,
        default=0.02,
        help="Binary target: stock fwd ret > market fwd ret + this (default 0.02 = 2%% pts)",
    )
    parser.add_argument("--tree-depth", type=int, default=3)
    parser.add_argument("--min-samples-leaf", type=int, default=40)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument(
        "--min-is-win-rate",
        type=float,
        default=0.65,
        help="In-sample win rate floor on y_binary among rule triggers (default 0.65)",
    )
    parser.add_argument(
        "--min-is-triggers",
        type=int,
        default=100,
        help="Minimum in-sample trigger count (default 100)",
    )
    parser.add_argument(
        "--max-oos-relative-drop",
        type=float,
        default=0.20,
        help="OOS win rate must be >= IS * (1 - this). Default 0.20 => max 20%% relative decay",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"[04_run_wfo] input not found: {args.input}")
        sys.exit(1)

    df = pd.read_parquet(args.input)
    if df.empty:
        print("[04_run_wfo] empty parquet; abort.")
        sys.exit(1)

    n_dates = int(df["date"].nunique())
    need = int(args.train_days) + int(args.test_days)
    if n_dates < need:
        print(
            f"[04_run_wfo] unique_dates={n_dates} < train+test={need}. "
            f"請降低 --train-days / --test-days 或產生更長區間的訓練集。"
        )
        sys.exit(1)

    rules = run_wfo_rule_mining(
        df,
        forward_return_days=int(args.forward_return_days),
        train_trading_days=int(args.train_days),
        test_trading_days=int(args.test_days),
        market_excess=float(args.market_excess),
        random_state=int(args.random_state),
        tree_max_depth=int(args.tree_depth),
        min_samples_leaf=int(args.min_samples_leaf),
        min_is_win_rate=float(args.min_is_win_rate),
        min_is_triggers=int(args.min_is_triggers),
        max_oos_relative_drop=float(args.max_oos_relative_drop),
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    dump_rules_json(rules, str(args.output))
    print(f"[04_run_wfo] surviving_rules={len(rules)} -> {args.output}")
    if not rules:
        print(
            "[04_run_wfo] 提示：若長期為 0 條，代表目前門檻過嚴或標的過難。"
            "可暫時調降 --min-is-win-rate / --min-is-triggers 做探索式掃描。"
        )


if __name__ == "__main__":
    main()
