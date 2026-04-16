"""
Centralized schema DDL for AlphaScan Pro.

Market / analysis data  →  data/market.duckdb  (DuckDB)
User-specific data      →  data/user.db         (SQLite)
"""

# ──────────────────────────────────────────────────────────────────────────────
# DuckDB DDL  ─  data/market.duckdb
# ──────────────────────────────────────────────────────────────────────────────

DUCKDB_DDL = """
-- ─── Core Market Data ────────────────────────────────────────────────────────

-- Single source of truth for stock names + market type
CREATE TABLE IF NOT EXISTS stock_info (
    stock_id   VARCHAR PRIMARY KEY,   -- pure number: '2330'
    name       VARCHAR NOT NULL,
    market     VARCHAR,               -- 'TSE' (上市) / 'OTC' (上櫃)
    is_active  BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

    -- Daily OHLCV K-bars (the largest table)
    -- disposition_mins = 0 means normal trading
    -- disposition_mins > 0 means under disposition, matched every N minutes
    CREATE TABLE IF NOT EXISTS daily_prices (
    stock_id         VARCHAR NOT NULL,
    date             DATE    NOT NULL,
    open             DOUBLE,
    high             DOUBLE,
    low              DOUBLE,
    close            DOUBLE,
    volume           BIGINT,
    disposition_mins INTEGER DEFAULT 0,
    PRIMARY KEY (stock_id, date)
);

CREATE INDEX IF NOT EXISTS idx_daily_prices_date
    ON daily_prices (date DESC);

-- Dividends  (updated once a year via yfinance)
CREATE TABLE IF NOT EXISTS dividends (
    stock_id VARCHAR NOT NULL,
    ex_date  DATE    NOT NULL,
    amount   DOUBLE,
    PRIMARY KEY (stock_id, ex_date)
);

-- Update audit log  (one row per logical dataset)
CREATE TABLE IF NOT EXISTS update_log (
    table_name  VARCHAR PRIMARY KEY,
    last_update TIMESTAMP,
    row_count   BIGINT,
    status      VARCHAR,   -- 'success' | 'failed'
    message     VARCHAR
);

-- ─── Chips / Ownership ───────────────────────────────────────────────────────

-- TDCC 集保 weekly distribution
CREATE TABLE IF NOT EXISTS tdcc_distribution (
    stock_id       VARCHAR NOT NULL,
    date           DATE    NOT NULL,
    total_holders  BIGINT,
    retail_pct     DOUBLE,
    whale_400_pct  DOUBLE,
    whale_1000_pct DOUBLE,
    PRIMARY KEY (stock_id, date)
);

-- 券商分點進出  (was previously missing from main DDL)
CREATE TABLE IF NOT EXISTS branch_trading (
    trade_date  DATE    NOT NULL,
    stock_id    VARCHAR NOT NULL,
    stock_name  VARCHAR,
    branch_name VARCHAR NOT NULL,
    buy_shares  BIGINT  DEFAULT 0,
    sell_shares BIGINT  DEFAULT 0,
    net_shares  BIGINT  DEFAULT 0,
    side        VARCHAR,   -- 'B' | 'S' | 'NET'
    PRIMARY KEY (trade_date, stock_id, branch_name)
);

-- 權證部位
CREATE TABLE IF NOT EXISTS warrant_positions (
    snapshot_date   DATE    NOT NULL,
    stock_id        VARCHAR NOT NULL,
    stock_name      VARCHAR,
    branch_name     VARCHAR NOT NULL,
    position_shares BIGINT,
    est_pnl         DOUBLE,
    est_pnl_pct     DOUBLE,
    amount_k        DOUBLE,
    type            VARCHAR,   -- '認購' | '認售'
    PRIMARY KEY (snapshot_date, stock_id, branch_name, type)
);

-- 內部人持股異動
CREATE TABLE IF NOT EXISTS insider_transfers (
    declare_date DATE    NOT NULL,
    stock_id     VARCHAR NOT NULL,
    stock_name   VARCHAR,
    shares       BIGINT,
    role         VARCHAR,
    method       VARCHAR,
    note         VARCHAR,
    PRIMARY KEY (declare_date, stock_id)
);

-- ─── Derived / Analysis ──────────────────────────────────────────────────────

-- Pearson correlation pairs  (weekly rebuild)
CREATE TABLE IF NOT EXISTS correlations (
    stock_id    VARCHAR NOT NULL,
    peer_id     VARCHAR NOT NULL,
    correlation DOUBLE,
    calc_date   DATE,
    PRIMARY KEY (stock_id, peer_id)
);

CREATE TABLE IF NOT EXISTS correlation_meta (
    key   VARCHAR PRIMARY KEY,
    value VARCHAR
);

-- Disposition events  (historical archive)
CREATE TABLE IF NOT EXISTS disposition_events (
    stock_id   VARCHAR NOT NULL,
    disp_start DATE    NOT NULL,
    disp_end   DATE,
    reason     VARCHAR,
    minutes    INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_id, disp_start)
);

-- Industry / sector mapping (TWSE CSV + optional theme micro)
CREATE TABLE IF NOT EXISTS stock_sectors (
    stock_id     VARCHAR PRIMARY KEY,
    macro        VARCHAR,
    meso         VARCHAR,
    micro        VARCHAR,
    industry_raw VARCHAR,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Key branch trades used by chips API (image-ingested data)
CREATE TABLE IF NOT EXISTS key_branch_trades (
    trade_date  DATE    NOT NULL,
    stock_id    VARCHAR NOT NULL,
    stock_name  VARCHAR,
    branch_name VARCHAR NOT NULL,
    side        VARCHAR,
    PRIMARY KEY (trade_date, stock_id, branch_name)
);

CREATE INDEX IF NOT EXISTS idx_key_branch_trades_date_stock
    ON key_branch_trades (trade_date, stock_id);
"""

# ──────────────────────────────────────────────────────────────────────────────
# Backward-compat views  (none currently needed — all callers migrated)
# ──────────────────────────────────────────────────────────────────────────────

DUCKDB_COMPAT_VIEWS = ""  # no-op; kept as extension point

# ──────────────────────────────────────────────────────────────────────────────
# SQLite DDL  ─  data/user.db
# ──────────────────────────────────────────────────────────────────────────────

USER_DB_DDL = """
CREATE TABLE IF NOT EXISTS watchlist (
    stock_id  TEXT PRIMARY KEY,
    added_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intraday_signals (
    scan_id     TEXT    NOT NULL,
    scan_time   TEXT    NOT NULL,
    strategy    TEXT    NOT NULL,
    stock_id    TEXT    NOT NULL,
    name        TEXT,
    market_type TEXT,
    close       REAL,
    change_pct  REAL,
    volume_k    INTEGER,
    signal_json TEXT,
    PRIMARY KEY (scan_time, strategy, stock_id)
);

CREATE INDEX IF NOT EXISTS idx_signals_strategy_time
    ON intraday_signals (strategy, scan_time DESC);
"""
