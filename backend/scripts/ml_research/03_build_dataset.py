"""
One-shot ML training dataset export with batched memory usage.

Writes Parquet to data/ml_datasets/training_data.parquet (default),
joins HMM market_regime, and degrades gracefully when historical_chips is empty.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# backend/scripts/ml_research/this_file.py -> repo root is 3 levels up
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.engines.ml_pipeline.dataset_builder import (  # noqa: E402
    build_training_dataset,
    list_distinct_symbols,
    load_macro_df,
)
from backend.engines.ml_pipeline.regime_hmm import (  # noqa: E402
    predict_regime_series,
    save_regime_bundle,
    train_regime_hmm,
)


def _chunked(items: List[str], size: int) -> List[List[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _batch_to_frame(X: pd.DataFrame, y: pd.Series) -> pd.DataFrame:
    out = X.reset_index()
    out["y_future_return_t1_td"] = y.to_numpy()
    return out


def _merge_regime(df: pd.DataFrame, regime_df: pd.DataFrame) -> pd.DataFrame:
    if regime_df.empty or df.empty:
        df = df.copy()
        df["market_regime"] = pd.NA
        return df
    r = regime_df[["date", "regime_state"]].copy()
    r["date"] = pd.to_datetime(r["date"])
    r = r.rename(columns={"regime_state": "market_regime"})
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    return out.merge(r, on="date", how="left")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ML training Parquet (batched)")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "ml_datasets" / "training_data.parquet",
        help="Output Parquet path",
    )
    parser.add_argument("--batch-size", type=int, default=50, help="Symbols per batch")
    parser.add_argument("--forward-return-days", type=int, default=5)
    parser.add_argument(
        "--limit-symbols",
        type=int,
        default=0,
        help="If >0, only process first N symbols (debug/smoke test)",
    )
    parser.add_argument("--hmm-states", type=int, default=3)
    parser.add_argument("--hmm-seed", type=int, default=42)
    parser.add_argument(
        "--hmm-bundle-out",
        type=Path,
        default=PROJECT_ROOT / "data" / "ml_datasets" / "regime_hmm_bundle.joblib",
        help="Write trained HMM bundle for daily inference (joblib)",
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    symbols = list_distinct_symbols()
    if args.limit_symbols and args.limit_symbols > 0:
        symbols = symbols[: int(args.limit_symbols)]
    if not symbols:
        print("[03_build_dataset] No symbols in historical_kbars_adj; abort.")
        return

    macro_df = load_macro_df()
    if macro_df.empty:
        print("[03_build_dataset] macro_indicators is empty; HMM will be skipped.")
        regime_df = pd.DataFrame(columns=["date", "regime_state", "regime_label"])
        bundle = None
    else:
        bundle = train_regime_hmm(macro_df, n_states=int(args.hmm_states), random_state=int(args.hmm_seed))
        regime_df = predict_regime_series(bundle, macro_df)
        try:
            save_regime_bundle(bundle, args.hmm_bundle_out)
            print(f"[03_build_dataset] saved HMM bundle -> {args.hmm_bundle_out}")
        except Exception as exc:  # noqa: BLE001
            print(f"[03_build_dataset] WARN: could not save HMM bundle: {exc}")

    writer: Optional[pq.ParquetWriter] = None
    schema: Optional[pa.Schema] = None
    column_order: Optional[List[str]] = None
    total_rows = 0

    batches = _chunked(symbols, max(1, int(args.batch_size)))
    print(
        f"[03_build_dataset] symbols={len(symbols)} batches={len(batches)} "
        f"batch_size={args.batch_size} -> {args.output}"
    )

    for bi, batch in enumerate(batches, start=1):
        X, y = build_training_dataset(
            universe=batch,
            forward_return_days=int(args.forward_return_days),
            macro_df=macro_df,
        )
        if X.empty:
            print(f"[03_build_dataset] batch {bi}/{len(batches)} empty, skip")
            continue

        part = _batch_to_frame(X, y)
        part = _merge_regime(part, regime_df)

        if column_order is None:
            column_order = list(part.columns)
        else:
            for c in column_order:
                if c not in part.columns:
                    part[c] = pd.NA
            part = part[column_order]

        table = pa.Table.from_pandas(part, preserve_index=False)
        if writer is None:
            schema = table.schema
            writer = pq.ParquetWriter(str(args.output), schema)
        else:
            table = table.cast(schema)
        writer.write_table(table)
        total_rows += len(part)
        print(f"[03_build_dataset] batch {bi}/{len(batches)} rows+={len(part)} total_rows={total_rows}")

    if writer is not None:
        writer.close()
        print(f"[03_build_dataset] done total_rows={total_rows} file={args.output}")
    else:
        print("[03_build_dataset] no rows written (all batches empty).")


if __name__ == "__main__":
    main()
