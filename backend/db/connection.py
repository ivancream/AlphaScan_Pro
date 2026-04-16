"""
Database connection management for AlphaScan Pro.

DuckDB (data/market.duckdb)
  - Windows: DuckDB 對同一檔案通常只允許一個作用中連線；反覆 connect/close 容易在
    並發或殘留控制代碼下觸發「檔案正由另一個程序使用」。因此採用 **程序內單一長連線**
    (_global_duck_conn)，由 threading.RLock 序列化所有讀寫。
  - thread-local depth：巢狀 duck_read/duck_write 僅追蹤深度；commit/rollback 仍依
    duck_write 語意處理。
  - 關閉 API 時請呼叫 close_duckdb() 釋放連線。獨立腳本仍可在 **未** 佔用該檔時
    自行 connect。

SQLite (data/user.db)
  - Per-call connections in WAL mode (lightweight)
"""

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import duckdb

from .schema import DUCKDB_DDL, DUCKDB_COMPAT_VIEWS, USER_DB_DDL

# ──────────────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
DUCKDB_PATH = _PROJECT_ROOT / "data" / "market.duckdb"
USER_DB_PATH = _PROJECT_ROOT / "data" / "user.db"

# DuckDB: serialize access; RLock allows nested duck_read/duck_write same thread
_duck_lock = threading.RLock()

# Single process-wide DuckDB handle (see module docstring — Windows single-file access)
_global_duck_conn: Optional[duckdb.DuckDBPyConnection] = None

# Thread-local: nested depth only (connection is global)
_tls = threading.local()


def _tls_depth() -> int:
    return getattr(_tls, "depth", 0)


def _set_tls_depth(v: int) -> None:
    _tls.depth = v


def _connect_duckdb_with_retry() -> duckdb.DuckDBPyConnection:
    """Open DuckDB; retry on transient Windows file lock / contention."""
    last: Optional[BaseException] = None
    for i in range(10):
        try:
            return duckdb.connect(str(DUCKDB_PATH))
        except Exception as exc:
            last = exc
            time.sleep(0.1 * (i + 1))
    assert last is not None
    raise last


def _ensure_global_duck_conn_unlocked() -> duckdb.DuckDBPyConnection:
    """Return process-wide DuckDB connection; caller must hold _duck_lock."""
    global _global_duck_conn
    if _global_duck_conn is None:
        _global_duck_conn = _connect_duckdb_with_retry()
    return _global_duck_conn


def _exec_ddl(conn: duckdb.DuckDBPyConnection, ddl_block: str) -> None:
    """Execute a DDL block containing multiple semicolon-separated statements."""
    stmts = [s.strip() for s in ddl_block.split(";") if s.strip()]
    for stmt in stmts:
        try:
            conn.execute(stmt)
        except Exception as exc:
            print(f"[DB DDL] Non-fatal: {exc!s:.120}")


def _migrate_duckdb_stock_sectors(conn: duckdb.DuckDBPyConnection) -> None:
    """Add columns introduced after first deploy (idempotent)."""
    try:
        rows = conn.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = 'stock_sectors'
            """
        ).fetchall()
        have = {r[0].lower() for r in rows}
        if "industry_raw" not in have:
            conn.execute("ALTER TABLE stock_sectors ADD COLUMN industry_raw VARCHAR")
    except Exception as exc:
        print(f"[DB] stock_sectors migration non-fatal: {exc!s:.120}")


def init_duckdb() -> None:
    """Initialize DuckDB schema; keeps one global connection for the process."""
    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _duck_lock:
        conn = _ensure_global_duck_conn_unlocked()
        _exec_ddl(conn, DUCKDB_DDL)
        _exec_ddl(conn, DUCKDB_COMPAT_VIEWS)
        _migrate_duckdb_stock_sectors(conn)
        conn.commit()
    print(f"[DB] DuckDB initialized at {DUCKDB_PATH}")


def close_duckdb() -> None:
    """Close the process-wide DuckDB connection (e.g. FastAPI shutdown)."""
    global _global_duck_conn
    with _duck_lock:
        if _global_duck_conn is not None:
            try:
                _global_duck_conn.close()
            except Exception:
                pass
            _global_duck_conn = None


@contextmanager
def duck_write():
    """
    Context manager for DuckDB writes.
    Serializes with RLock; commits on success; global connection stays open.
    """
    with _duck_lock:
        d = _tls_depth() + 1
        _set_tls_depth(d)
        conn = _ensure_global_duck_conn_unlocked()
        try:
            yield conn
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        else:
            conn.commit()
        finally:
            _set_tls_depth(d - 1)


@contextmanager
def duck_read():
    """
    Context manager for DuckDB reads.
    Nested calls in the same thread only adjust depth; one global connection is used.
    """
    with _duck_lock:
        d = _tls_depth() + 1
        _set_tls_depth(d)
        conn = _ensure_global_duck_conn_unlocked()
        try:
            yield conn
        finally:
            _set_tls_depth(d - 1)


# ──────────────────────────────────────────────────────────────────────────────
# SQLite user.db
# ──────────────────────────────────────────────────────────────────────────────

def init_user_db() -> None:
    """Initialize SQLite user.db. Call once at app startup."""
    USER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(USER_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(USER_DB_DDL)
    conn.commit()
    conn.close()
    print(f"[DB] User DB initialized at {USER_DB_PATH}")


@contextmanager
def user_db():
    """
    Context manager for SQLite user.db.
    WAL mode, auto-commit on success.
    """
    conn = sqlite3.connect(str(USER_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Combined init
# ──────────────────────────────────────────────────────────────────────────────

def init_all() -> None:
    """Initialize all databases. Call once at FastAPI startup."""
    init_duckdb()
    init_user_db()
