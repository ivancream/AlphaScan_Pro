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

    訊息格式（JSON）:
    {
        "ts":         "2024-03-15T09:05:01Z",
        "symbol":     "2330",
        "name":       "台積電",
        "asset_type": "STOCK",   // STOCK | WARRANT | FUTURES
        "price":      850.0,
        "volume":     5,          // 張 (股票) / 口 (期貨)
        "tick_type":  "BUY_UP"   // BUY_UP | SELL_DOWN | NEUTRAL
    }
    """
    await websocket.accept()
    raw_symbols = websocket.query_params.get("symbols", "")
    include_futures = websocket.query_params.get("include_futures", "false").lower() in ("1", "true", "yes")
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
            if stock_symbols and tick.get("symbol") in stock_symbols:
                await websocket.send_json(tick)
                continue

            if include_futures and tick.get("asset_type") == "FUTURES":
                await websocket.send_json(tick)
                continue

            if not stock_symbols and not include_futures:
                await websocket.send_json(tick)
                continue
    except WebSocketDisconnect:
        return
    finally:
        all_around_engine.unsubscribe(subscription)
