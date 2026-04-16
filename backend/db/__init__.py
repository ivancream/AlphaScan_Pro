"""
backend.db — unified database access layer for AlphaScan Pro.

DuckDB  (data/market.duckdb) : all market & analysis data
SQLite  (data/user.db)       : user-specific data (watchlist, signals)
"""

from .connection import (
    init_all,
    init_duckdb,
    init_user_db,
    close_duckdb,
    duck_read,
    duck_write,
    user_db,
    DUCKDB_PATH,
    USER_DB_PATH,
)
from . import queries
from . import writer
from . import user_db as user_db_ops

__all__ = [
    "init_all",
    "init_duckdb",
    "init_user_db",
    "close_duckdb",
    "duck_read",
    "duck_write",
    "user_db",
    "DUCKDB_PATH",
    "USER_DB_PATH",
    "queries",
    "writer",
    "user_db_ops",
]
