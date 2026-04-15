from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.engines.engine_all_around import all_around_engine

router = APIRouter()


@router.get("/api/v1/all-around/health")
async def get_all_around_health():
    """全方位監控引擎健康狀態。"""
    return all_around_engine.get_health()


@router.websocket("/ws/all-around-ticker")
async def all_around_ticker_ws(websocket: WebSocket):
    """
    全方位即時 Tick 串流。

    Query params:
      symbols        逗號分隔的股票代碼（可選）
      include_futures 是否包含期貨 tick（true/false）
      history_limit   回補歷史筆數上限（預設 120，最大 500）

    訊息格式（JSON）:
    {
        "ts":         "09:05:01",
        "symbol":     "2330",
        "name":       "台積電",
        "asset_type": "現貨",    // 現貨 | 期貨 | 認購 | 認售
        "price":      850.0,
        "volume":     5,
        "tick_dir":   "OUTER",   // OUTER | INNER | NONE
        "chg_type":   "UP",      // LIMIT_UP | UP | FLAT | DOWN | LIMIT_DOWN
        "pct_chg":    1.23
    }
    """
    await websocket.accept()
    raw_symbols = websocket.query_params.get("symbols", "")
    include_futures = websocket.query_params.get("include_futures", "false").lower() in (
        "1", "true", "yes",
    )
    history_limit = int(websocket.query_params.get("history_limit", "120") or 120)

    stock_symbols = {
        item.strip().upper()
        for item in raw_symbols.split(",")
        if item.strip()
    }
    if stock_symbols:
        all_around_engine.add_stk_symbols(sorted(stock_symbols))

    subscription = all_around_engine.subscribe()
    history = all_around_engine.get_recent_ticks(
        stock_symbols=stock_symbols,
        include_futures=include_futures,
        limit=max(0, min(history_limit, 500)),
    )
    try:
        for tick in history:
            await websocket.send_json(tick)

        while True:
            tick = await subscription.get()
            sym = tick.get("symbol", "")
            asset = tick.get("asset_type", "")

            if stock_symbols and sym in stock_symbols:
                await websocket.send_json(tick)
                continue

            if include_futures and asset == "期貨":
                await websocket.send_json(tick)
                continue

            if not stock_symbols and not include_futures:
                await websocket.send_json(tick)
                continue
    except WebSocketDisconnect:
        return
    finally:
        all_around_engine.unsubscribe(subscription)
