"""
consolidate_db.py — one-shot migration from legacy SQLite/DuckDB files
to the new unified schema in data/market.duckdb + data/user.db.

Run once from the project root:
    python -m backend.scripts.consolidate_db

Sources migrated:
  databases/db_technical_prices.db  →  daily_prices, stock_info,
                                        disposition_events  (DuckDB)
                                        watchlist, intraday_signals  (user.db)
  databases/db_chips_ownership.db   →  tdcc_distribution  (DuckDB)
  databases/db_correlation.db       →  correlations, correlation_meta  (DuckDB)
  data/taiwan_stock.db              →  dividends  (DuckDB)
  data/market.duckdb (historical_prices) →  daily_prices  (DuckDB, backfill)
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

# ── project root on path ───────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from backend.db.connection import init_all, DUCKDB_PATH, USER_DB_PATH
from backend.db import writer

# ── legacy paths ──────────────────────────────────────────────────────────────
TECH_DB   = PROJECT_ROOT / "databases" / "db_technical_prices.db"
CHIPS_DB  = PROJECT_ROOT / "databases" / "db_chips_ownership.db"
CORR_DB   = PROJECT_ROOT / "databases" / "db_correlation.db"
LEGACY_DB = PROJECT_ROOT / "data" / "taiwan_stock.db"


def _sqlite_read(db_path: Path, query: str) -> pd.DataFrame:
    if not db_path.exists():
        print(f"  [skip] {db_path} not found")
        return pd.DataFrame()
    try:
        with sqlite3.connect(str(db_path)) as conn:
            return pd.read_sql(query, conn)
    except Exception as exc:
        print(f"  [warn] read {db_path}: {exc}")
        return pd.DataFrame()


# ──────────────────────────────────────────────────────────────────────────────
# Migration steps
# ──────────────────────────────────────────────────────────────────────────────

def migrate_stock_info() -> None:
    """Migrate stock_info from db_technical_prices.db (preferred) + taiwan_stock.db."""
    print("\n[1] stock_info …")

    df_tech = _sqlite_read(
        TECH_DB,
        "SELECT stock_id, name, market_type AS market FROM stock_info",
    )
    df_legacy = _sqlite_read(
        LEGACY_DB,
        "SELECT stock_id, name, market_type AS market FROM stock_info",
    )

    df = pd.concat([df_legacy, df_tech], ignore_index=True)  # tech wins (later rows)
    df = df.dropna(subset=["stock_id", "name"])
    df = df.drop_duplicates(subset=["stock_id"], keep="last")

    # Normalise market: '上市'→'TSE', '上櫃'→'OTC'
    df["market"] = df["market"].map(
        lambda m: "TSE" if "上市" in str(m) else ("OTC" if "上櫃" in str(m) else str(m or ""))
    )
    df["is_active"] = True

    rows = list(df[["stock_id", "name", "market", "is_active"]].itertuples(index=False, name=None))
    n = writer.upsert_stock_info(rows)
    print(f"  OK {n} rows")


def _migrate_prices_from_sqlite(db_path: Path, label: str, has_disposition: bool = False) -> int:
    """Chunked migration of daily_price from a single SQLite source."""
    if not db_path.exists():
        print(f"  [skip] {label} not found")
        return 0
    chunk_size = 50_000
    try:
        with sqlite3.connect(str(db_path)) as conn:
            total = pd.read_sql("SELECT COUNT(*) AS n FROM daily_price", conn).iloc[0]["n"]
        print(f"  {label}: {total:,} rows in source")

        disp_col = "IFNULL(disposition_mins, 0) AS disposition_mins" if has_disposition else "0 AS disposition_mins"
        offset = 0
        while offset < total:
            df = _sqlite_read(
                db_path,
                f"""
                SELECT stock_id, date, open, high, low, close, volume,
                       {disp_col}
                FROM daily_price
                ORDER BY stock_id, date
                LIMIT {chunk_size} OFFSET {offset}
                """,
            )
            if df.empty:
                break
            writer.upsert_daily_prices(df)
            offset += len(df)
            print(f"  … {offset:,}/{total:,}", end="\r")
        print(f"\n  OK Migrated {offset:,} rows from {label}")
        return offset
    except Exception as exc:
        print(f"  [warn] {label}: {exc}")
        return 0


def migrate_daily_prices() -> None:
    """
    Migrate daily_price from both SQLite sources:
      1. taiwan_stock.db — longest history (2016~), primary backfill
      2. db_technical_prices.db — more recent + today, with disposition_mins

    Order matters: taiwan_stock.db first (base), then tech DB upserts on top
    so the latest values from the more actively maintained DB win.
    """
    print("\n[2] daily_prices …")
    _migrate_prices_from_sqlite(LEGACY_DB, "taiwan_stock.db", has_disposition=False)
    _migrate_prices_from_sqlite(TECH_DB, "db_technical_prices.db", has_disposition=True)


def migrate_dividends() -> None:
    """Migrate dividends from taiwan_stock.db."""
    print("\n[3] dividends …")
    df = _sqlite_read(
        LEGACY_DB,
        "SELECT stock_id, date AS ex_date, dividend AS amount FROM dividends",
    )
    if df.empty:
        return
    rows = list(df[["stock_id", "ex_date", "amount"]].itertuples(index=False, name=None))
    n = writer.upsert_dividends(rows)
    print(f"  OK {n} rows")


def migrate_tdcc() -> None:
    """Migrate TDCC data from db_chips_ownership.db."""
    print("\n[4] tdcc_distribution …")
    df = _sqlite_read(
        CHIPS_DB,
        """
        SELECT stock_id, date,
               IFNULL(total_owners, 0)    AS total_holders,
               IFNULL(retail_pct,   0)    AS retail_pct,
               IFNULL(whale_400_pct,0)    AS whale_400_pct,
               IFNULL(whale_1000_pct,0)   AS whale_1000_pct
        FROM tdcc_dist
        """,
    )
    if df.empty:
        return
    n = writer.upsert_tdcc(df)
    print(f"  OK {n} rows")


def migrate_correlations() -> None:
    """Migrate correlations from db_correlation.db."""
    print("\n[5] correlations …")
    if not CORR_DB.exists():
        print("  [skip] db_correlation.db not found")
        return

    df = _sqlite_read(
        CORR_DB,
        "SELECT stock_id, peer_id, correlation, calc_date FROM top_correlations",
    )
    if df.empty:
        return

    calc_date = str(df["calc_date"].dropna().max()) if "calc_date" in df.columns else "unknown"
    df = df[["stock_id", "peer_id", "correlation"]]
    n = writer.upsert_correlations(df, calc_date)
    print(f"  OK {n} rows  (calc_date={calc_date})")

    # Also migrate meta
    meta_df = _sqlite_read(CORR_DB, "SELECT key, value FROM meta")
    if not meta_df.empty:
        from backend.db.connection import duck_write
        with duck_write() as conn:
            for _, row in meta_df.iterrows():
                conn.execute(
                    """
                    INSERT INTO correlation_meta (key, value) VALUES (?, ?)
                    ON CONFLICT (key) DO UPDATE SET value = excluded.value
                    """,
                    [str(row["key"]), str(row["value"])],
                )
        print(f"  OK correlation_meta: {len(meta_df)} rows")


def migrate_disposition_events() -> None:
    """Migrate disposition_events from both db_technical_prices.db and taiwan_stock.db."""
    print("\n[6] disposition_events …")
    for db_path, label in [(TECH_DB, "tech"), (LEGACY_DB, "legacy")]:
        if not db_path.exists():
            continue
        try:
            with sqlite3.connect(str(db_path)) as conn:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(disposition_events)").fetchall()]
            reason_col = "IFNULL(reason, '')" if "reason" in cols else "''"
            minutes_col = "IFNULL(minutes, 0)" if "minutes" in cols else "0"
            df = _sqlite_read(
                db_path,
                f"SELECT stock_id, disp_start, disp_end, {reason_col} AS reason, {minutes_col} AS minutes "
                "FROM disposition_events",
            )
        except Exception as exc:
            print(f"  [warn] {label}: {exc}")
            continue
        if df.empty:
            continue
        rows = [
            (
                str(r.stock_id),
                str(r.disp_start),
                str(r.disp_end) if r.disp_end and str(r.disp_end) not in ("None", "") else None,
                str(r.reason) if r.reason else "",
                int(r.minutes or 0),
            )
            for r in df.itertuples(index=False)
        ]
        n = writer.upsert_disposition_events(rows)
        print(f"  OK {n} rows from {label}")


def migrate_watchlist() -> None:
    """Migrate watchlist from db_technical_prices.db to user.db."""
    print("\n[7] watchlist (→ user.db) …")
    df = _sqlite_read(
        TECH_DB,
        "SELECT stock_id, IFNULL(added_at, datetime('now')) AS added_at FROM watchlist",
    )
    if df.empty:
        return

    with sqlite3.connect(str(USER_DB_PATH)) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO watchlist (stock_id, added_at) VALUES (?, ?)",
            list(df[["stock_id", "added_at"]].itertuples(index=False, name=None)),
        )
        conn.commit()
    print(f"  OK {len(df)} rows")


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def run_consolidation() -> None:
    print("=" * 60)
    print(" AlphaScan DB Consolidation")
    print("=" * 60)
    print(f"  Target DuckDB : {DUCKDB_PATH}")
    print(f"  Target UserDB : {USER_DB_PATH}")

    # Ensure target DBs exist with correct schema
    init_all()

    migrate_stock_info()
    migrate_daily_prices()
    migrate_dividends()
    migrate_tdcc()
    migrate_correlations()
    migrate_disposition_events()
    migrate_watchlist()

    print("\n" + "=" * 60)
    print(" Consolidation complete!")
    print("=" * 60)


if __name__ == "__main__":
    run_consolidation()
