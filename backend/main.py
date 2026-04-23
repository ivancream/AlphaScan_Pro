import sys
import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

# 將專案根目錄與 backend 目錄加入 sys.path
root_path = Path(__file__).parent.parent.absolute()
backend_path = Path(__file__).parent.absolute()
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

# 載入專案根目錄 .env（永豐金 API 等）
from backend import settings  # noqa: F401

# ── 新統一 DB 層 ────────────────────────────────────────────────────────────
from backend.db.connection import init_all as _init_all_dbs, close_duckdb
from backend.scheduler import start_scheduler, stop_scheduler

from backend.api.v1 import (
    market_data, market_brief, sentiment, global_market, fundamental,
    technical, swing, floor_bounce, dividend,
    cb_tracker, chips, correlation, disposition, intraday, watchlist, backtest,
    heatmap, live_quotes, all_around, intraday_scanner, warrants, notifier as notifier_api,
    system as system_api,
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

# 初始化資料庫（新統一架構 + 舊相容表）
@app.on_event("startup")
async def startup_db_client():
    print(f"[*] Starting AlphaScan API...")
    print(f"[*] Project Root: {root_path}")

    # Step 0: 初始化新統一 DB 層（DuckDB + user.db）
    _init_all_dbs()

    # ── Step 1: 優先完成 Shioaji 共享 Session 登入 ────────────────────────────
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, sinopac_session.connect)
        if sinopac_session.is_connected:
            print("[Startup] Shioaji 共享 Session 登入成功")
        else:
            print(f"[Startup] Shioaji 未連線（{sinopac_session.last_error}），降級至 yfinance")
    except Exception as exc:
        print(f"[Startup] Shioaji 登入例外: {exc}")

    # ── Step 2: 啟動統一排程器（取代舊的 intraday.start_scheduler + start_scanner） ──
    start_scheduler()

    # ── Step 3: 資料完整性檢查 — 如果今日收盤資料不齊，用 yfinance 回補 ─────
    try:
        from backend.api.v1.intraday import run_startup_catchup
        await loop.run_in_executor(None, run_startup_catchup)
    except Exception as exc:
        print(f"[StartupCatchup] Failed: {exc}")

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
    stop_scheduler()
    await live_quote_engine.stop()
    await all_around_engine.stop()
    sinopac_session.disconnect()
    close_duckdb()

# 註冊 API 路由 (Controllers)
app.include_router(market_data.router, tags=["Market Data"])
app.include_router(market_brief.router, tags=["Market Brief"])
app.include_router(sentiment.router, tags=["Qualitative Analysis"])
app.include_router(global_market.router, tags=["Global Market"])
app.include_router(fundamental.router, tags=["Fundamental Analysis"])
app.include_router(technical.router, tags=["Technical Analysis"])
app.include_router(swing.router, tags=["Swing Strategy"])
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
app.include_router(warrants.router, tags=["Warrants"])
app.include_router(notifier_api.router, tags=["Notifications"])
app.include_router(system_api.router, tags=["System"])

@app.get("/")
def open_frontend(request: Request):
    """
    瀏覽器開啟 http://127.0.0.1:8000 或 http://localhost:8000 時，自動導向 Vite 前端 (:1420)。
    REST/WebSocket 仍為 /api、/ws；文件見 /docs。
    """
    host = request.headers.get("host", "127.0.0.1:8000")
    hostname = host.split(":")[0]
    return RedirectResponse(url=f"http://{hostname}:1420/", status_code=302)
