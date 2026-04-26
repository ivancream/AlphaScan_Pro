"""Prepare tabular data from DuckDB for ML experiments."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd


def export_duckdb_to_parquet(db_path: Path, query: str, output_path: Path) -> None:
    """Run a DuckDB query and export the result as a Parquet file."""
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(query).fetch_df()
    finally:
        con.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    print(f"Exported {len(df)} rows to: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="DuckDB -> Pandas/Parquet data prep")
    parser.add_argument("--db-path", required=True, help="Path to DuckDB file")
    parser.add_argument("--query", required=True, help="SQL query for feature extraction")
    parser.add_argument("--output-path", required=True, help="Output parquet path")
    args = parser.parse_args()

    export_duckdb_to_parquet(
        db_path=Path(args.db_path),
        query=args.query,
        output_path=Path(args.output_path),
    )


if __name__ == "__main__":
    main()
