from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.engines.engine_live_quotes import live_quote_engine

router = APIRouter()


@router.get("/api/v1/live-quotes/health")
async def get_live_quotes_health():
    return live_quote_engine.get_health()


@router.get("/api/v1/live-quotes/snapshot")
async def get_live_quotes_snapshot():
    return {
        "type": "snapshot",
        "payload": live_quote_engine.get_latest_quotes(),
    }


@router.post("/api/v1/live-quotes/ensure/{stock_id}")
async def ensure_live_quote_symbol(stock_id: str):
    ensured = live_quote_engine.ensure_symbol(stock_id)
    return {
        "stock_id": stock_id,
        "ensured": ensured,
        "provider": live_quote_engine.get_health().get("provider"),
    }


@router.websocket("/ws/live-quotes")
async def live_quotes_websocket(websocket: WebSocket):
    await websocket.accept()
    raw_symbols = websocket.query_params.get("symbols", "")
    if raw_symbols:
        for symbol in [item.strip().upper() for item in raw_symbols.split(",") if item.strip()]:
            live_quote_engine.ensure_symbol(symbol)
    subscription = live_quote_engine.subscribe()

    initial = {
        "type": "snapshot",
        "payload": live_quote_engine.get_latest_quotes(),
    }
    await websocket.send_json(initial)

    try:
        while True:
            event = await subscription.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        return
    finally:
        live_quote_engine.unsubscribe(subscription)
