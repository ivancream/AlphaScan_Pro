import sys
import duckdb
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 將專案根目錄與 backend 目錄加入 sys.path，解決 ModuleNotFoundError: No module named 'api'
root_path = Path(__file__).parent.parent.absolute()
import sys
import duckdb
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 將專案根目錄與 backend 目錄加入 sys.path，解決 ModuleNotFoundError: No module named 'api'
root_path = Path(__file__).parent.parent.absolute()
backend_path = Path(__file__).parent.absolute()
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

# 載入專案根目錄 .env（永豐金 API 等）
from backend import settings  # noqa: F401

from backend.api.v1 import (
    market_data, sentiment, global_market, fundamental,
    technical, swing, etfs, floor_bounce, dividend,
    cb_tracker, chips, correlation, disposition, intraday, watchlist, backtest,
    heatmap, live_quotes, all_around, intraday_scanner, notifier as notifier_api
)
from backend.engines.engine_live_quotes import live_quote_engine
from backend.engines.engine_all_around import all_around_engine
from backend.engines.engine_symbol_pool import get_symbol_pool
from backend.engines.sinopac_session import sinopac_session

import google.generativeai as genai

# -------- 全局關閉 AI 分析 (Mock) --------
# 若未來想要恢復 AI 功能，請將此段程式碼註解或刪除
def mocked_generate_content(self, *args, **kwargs):
    if kwargs.get('stream'):
        class MockChunk:
            text = "⚠️ AI 輔助分析功能已暫時關閉，目前僅顯示純數據結果。若要重新啟用，請至 backend/main.py 移除 Mock 設定。"
        def mockup_stream():
            yield MockChunk()
        return mockup_stream()
    else:
        class MockResponse:
            text = "⚠️ AI 輔助分析功能已暫時關閉，目前僅顯示純數據結果。若要重新啟用，請至 backend/main.py 移除 Mock 設定。"
        return MockResponse()

genai.GenerativeModel.generate_content = mocked_generate_content
# ----------------------------------------

app = FastAPI(title="AlphaScan Quant-Qual API", version="1.0.0")

# 設定 CORS 允許前端 (Next.js 預設 3000 port) 存取
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",    # Next.js 舊開發環境（保留相容）
        "http://localhost:1420",    # Vite 開發伺服器
        "tauri://localhost",        # Tauri 正式 App (Windows)
        "https://tauri.localhost",  # Tauri 正式 App (macOS / Linux)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化 DuckDB 資料庫
@app.on_event("startup")
async def startup_db_client():
    data_dir = root_path / 'data'
    data_dir.mkdir(exist_ok=True)
    db_path = data_dir / 'market.duckdb'
    
    print(f"[*] Starting AlphaScan API...")
    print(f"[*] Project Root: {root_path}")
    print(f"[*] Database Path: {db_path}")

    with duckdb.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS historical_prices (
                symbol VARCHAR,
                date DATE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                PRIMARY KEY (symbol, date)
            );
            CREATE INDEX IF NOT EXISTS idx_symbol_date ON historical_prices (symbol, date DESC);

            CREATE TABLE IF NOT EXISTS key_branch_trades (
                trade_date DATE,
                stock_id VARCHAR,
                stock_name VARCHAR,
                branch_name VARCHAR,
                side VARCHAR, -- 'B' or 'S'
                PRIMARY KEY (trade_date, stock_id, branch_name)
            );
            CREATE INDEX IF NOT EXISTS idx_key_branch_trades_date_stock
                ON key_branch_trades (trade_date, stock_id);

            CREATE TABLE IF NOT EXISTS warrant_branch_positions (
                snapshot_date DATE,
                stock_id VARCHAR,
                stock_name VARCHAR,
                branch_name VARCHAR,
                position_shares BIGINT,   -- 持有張數
                est_pnl DOUBLE,           -- 損益推估 (金額，可為負)
                est_pnl_pct DOUBLE,       -- 損益率 (%), 可為 NULL
                amount_k DOUBLE,          -- 買超金額 (萬)
                type VARCHAR,             -- 型態 (認購/認售)
                PRIMARY KEY (snapshot_date, stock_id, branch_name, type)
            );
            CREATE INDEX IF NOT EXISTS idx_warrant_positions_date_stock
                ON warrant_branch_positions (snapshot_date, stock_id);

            CREATE TABLE IF NOT EXISTS insider_transfers (
                declare_date DATE,        -- 申報日期
                stock_id VARCHAR,         -- 股票代號
                stock_name VARCHAR,       -- 股票名稱 (如有)
                shares BIGINT,            -- 轉讓張數
                role VARCHAR,             -- 身分 (董事/大股東等，可為 NULL)
                method VARCHAR,           -- 轉讓方式 (信託/一般交易等，可為 NULL)
                note VARCHAR,             -- 備註或原始片段，可為 NULL
                PRIMARY KEY (declare_date, stock_id)
            );
            CREATE INDEX IF NOT EXISTS idx_insider_transfers_date_stock
                ON insider_transfers (declare_date, stock_id);

            CREATE TABLE IF NOT EXISTS stock_sector_map (
                ticker VARCHAR PRIMARY KEY,
                name VARCHAR,
                macro VARCHAR,
                meso VARCHAR,
                micro VARCHAR,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

    # ── Step 1: 優先完成 Shioaji 共享 Session 登入（所有引擎共用此連線） ──────
    # 在 executor 中執行（fetch_contract=True 需要 5~15 秒阻塞，不能在 event loop 中直接跑）
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, sinopac_session.connect)
        if sinopac_session.is_connected:
            print("[Startup] Shioaji 共享 Session 登入成功")
        else:
            print(f"[Startup] Shioaji 未連線（{sinopac_session.last_error}），各引擎將降級至 yfinance")
    except Exception as exc:
        print(f"[Startup] Shioaji 登入例外: {exc}")

    # ── Step 2: 啟動盤中更新排程 ───────────────────────────────────────────────
    intraday.start_scheduler()

    # ── Step 3: 啟動盤中 30 分鐘技術面掃描排程器 ─────────────────────────────
    from backend.engines.engine_intraday_scanner import start_scanner as start_intraday_scanner
    start_intraday_scanner()

    # ── Step 4: 啟動即時報價引擎（Shioaji handler 注冊 / yfinance fallback）──
    try:
        loop.create_task(live_quote_engine.start())
    except Exception as exc:
        print(f"[LiveQuotes] Failed to start engine: {exc}")

    # ── Step 5: 啟動全方位報價引擎（STK + FOP ticks）────────────────────────
    try:
        pool = get_symbol_pool(top_n=50)
        stk_symbols = [item["stock_id"] for item in pool]
        loop.create_task(
            all_around_engine.start(stk_symbols=stk_symbols)
        )
    except Exception as exc:
        print(f"[AllAround] Failed to start engine: {exc}")


@app.on_event("shutdown")
async def shutdown_engines():
    await live_quote_engine.stop()
    await all_around_engine.stop()
    sinopac_session.disconnect()  # 最後統一登出共享 Session

# 註冊 API 路由 (Controllers)
app.include_router(market_data.router, tags=["Market Data"])
app.include_router(sentiment.router, tags=["Qualitative Analysis"])
app.include_router(global_market.router, tags=["Global Market"])
app.include_router(fundamental.router, tags=["Fundamental Analysis"])
app.include_router(technical.router, tags=["Technical Analysis"])
app.include_router(swing.router, tags=["Swing Strategy"])
app.include_router(etfs.router, tags=["ETF Tracking"])
app.include_router(floor_bounce.router, tags=["Floor Bounce"])
app.include_router(dividend.router, tags=["Dividend Analysis"])
app.include_router(cb_tracker.router, tags=["CB Tracker"])
app.include_router(chips.router, tags=["Chips Analysis"])
app.include_router(correlation.router, tags=["Correlation Strategy"])
app.include_router(disposition.router, tags=["Disposition Analysis"])
app.include_router(intraday.router, tags=["Intraday Refresh"])
app.include_router(watchlist.router, tags=["Watchlist"])
app.include_router(backtest.router, tags=["Backtesting"])
app.include_router(heatmap.router, tags=["Heatmap"])
app.include_router(live_quotes.router, tags=["Live Quotes"])
app.include_router(all_around.router, tags=["All-Around Ticker"])
app.include_router(intraday_scanner.router, tags=["Intraday Scanner"])
app.include_router(notifier_api.router, tags=["Notifications"])

@app.get("/")
def read_root():
    return {"status": "AlphaScan API is running."}
