"""
Safe DB housekeeping for AlphaScan Pro.

Purpose:
- Keep DB files compact and query stats fresh.
- Avoid schema/data-model changes.

Usage:
    python -m backend.scripts.db_maintenance
"""

from __future__ import annotations

import sqlite3

from backend.db.connection import DUCKDB_PATH, USER_DB_PATH, duck_write


def maintain_duckdb() -> None:
    """Run lightweight DuckDB maintenance commands."""
    print(f"[DuckDB] target: {DUCKDB_PATH}")
    with duck_write() as conn:
        conn.execute("ANALYZE")
        conn.execute("CHECKPOINT")
        conn.execute("VACUUM")
    print("[DuckDB] ANALYZE + CHECKPOINT + VACUUM done")


def maintain_user_db() -> None:
    """Run safe SQLite maintenance on user.db."""
    print(f"[SQLite] target: {USER_DB_PATH}")
    with sqlite3.connect(str(USER_DB_PATH)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA optimize")
        conn.execute("VACUUM")
    print("[SQLite] WAL checkpoint + optimize + vacuum done")


def run() -> None:
    print("=" * 60)
    print(" AlphaScan DB Maintenance")
    print("=" * 60)
    maintain_duckdb()
    maintain_user_db()
    print("=" * 60)
    print(" Maintenance complete")
    print("=" * 60)


if __name__ == "__main__":
    run()
