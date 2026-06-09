from __future__ import annotations

import asyncio
from typing import Any, Dict, Set

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from backend.db.user_db import get_recent_monitor_events, write_monitor_event
from backend.engines.engine_all_around import all_around_engine
from backend.engines.engine_intraday_monitor import (
    IntradaySignalDetector,
    MonitorThresholds,
    build_monitor_subscription_symbols,
    get_monitor_health,
    get_monitor_micro_snapshot,
    live_order_book_cache,
)

router = APIRouter()


def _parse_symbols(raw: str) -> Set[str]:
    out = {
        item.strip().upper().replace(".TW", "").replace(".TWO", "")
        for item in str(raw or "").replace("\n", ",").replace(" ", ",").split(",")
        if item.strip()
    }
    return {s for s in out if s}


def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(lo, min(hi, n))


def _clamp_float(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        n = float(value)
    except Exception:
        n = default
    return max(lo, min(hi, n))


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


@router.get("/api/v1/intraday-monitor/health")
async def intraday_monitor_health() -> Dict[str, Any]:
    return get_monitor_health()


@router.get("/api/v1/intraday-monitor/micro/{symbol}")
async def intraday_monitor_micro(symbol: str) -> Dict[str, Any]:
    return get_monitor_micro_snapshot(symbol)


@router.get("/api/v1/intraday-monitor/events")
async def intraday_monitor_events(
    symbol: str = Query(default=""),
    limit: int = Query(default=300, ge=1, le=2000),
) -> Dict[str, Any]:
    normalized = next(iter(_parse_symbols(symbol)), "") if symbol else ""
    events = get_recent_monitor_events(symbol=normalized or None, limit=limit)
    return {
        "count": len(events),
        "symbol": normalized or None,
        "items": events,
        "source": "user_db",
    }


@router.websocket("/ws/intraday-monitor")
async def intraday_monitor_ws(websocket: WebSocket):
    await websocket.accept()

    raw_symbols = websocket.query_params.get("symbols", "")
    watch_symbols = _parse_symbols(raw_symbols)
    include_warrants = websocket.query_params.get("include_warrants", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    max_warrants_per_stock = _clamp_int(
        websocket.query_params.get("max_warrants_per_stock"),
        40,
        0,
        120,
    )

    thresholds = MonitorThresholds(
        stock_lot_threshold=_clamp_int(websocket.query_params.get("stock_lot_threshold"), 50, 1, 5000),
        warrant_lot_threshold=_clamp_int(websocket.query_params.get("warrant_lot_threshold"), 100, 1, 10000),
        move_window_sec=_clamp_int(websocket.query_params.get("move_window_sec"), 60, 5, 600),
        move_pct_threshold=_clamp_float(websocket.query_params.get("move_pct_threshold"), 1.5, 0.1, 10.0),
        continuous_window_sec=_clamp_int(websocket.query_params.get("continuous_window_sec"), 3, 1, 60),
        continuous_min_count=_clamp_int(websocket.query_params.get("continuous_min_count"), 3, 2, 50),
        scalp_enabled=_parse_bool(websocket.query_params.get("scalp_enabled"), True),
        scalp_consecutive_window_sec=_clamp_int(
            websocket.query_params.get("scalp_consecutive_window_sec"),
            5,
            1,
            30,
        ),
        scalp_consecutive_min_count=_clamp_int(
            websocket.query_params.get("scalp_consecutive_min_count"),
            30,
            2,
            300,
        ),
        scalp_consecutive_min_volume=_clamp_int(
            websocket.query_params.get("scalp_consecutive_min_volume"),
            300,
            1,
            10000,
        ),
        scalp_reversal_min_lots=_clamp_int(
            websocket.query_params.get("scalp_reversal_min_lots"),
            20,
            1,
            5000,
        ),
        scalp_vwap_deviation_pct=_clamp_float(
            websocket.query_params.get("scalp_vwap_deviation_pct"),
            2.0,
            0.1,
            20.0,
        ),
        scalp_wall_lots=_clamp_int(websocket.query_params.get("scalp_wall_lots"), 500, 1, 50000),
        scalp_wall_avg_volume_multiple=_clamp_float(
            websocket.query_params.get("scalp_wall_avg_volume_multiple"),
            2.0,
            0.1,
            100.0,
        ),
        scalp_no_new_extreme_sec=_clamp_float(
            websocket.query_params.get("scalp_no_new_extreme_sec"),
            2.0,
            0.1,
            30.0,
        ),
        scalp_spoof_min_lots=_clamp_int(
            websocket.query_params.get("scalp_spoof_min_lots"),
            200,
            1,
            50000,
        ),
        scalp_spoof_drop_pct=_clamp_float(
            websocket.query_params.get("scalp_spoof_drop_pct"),
            0.65,
            0.05,
            1.0,
        ),
    )

    subscription_symbols = build_monitor_subscription_symbols(
        watch_symbols,
        include_warrants=include_warrants,
        max_warrants_per_stock=max_warrants_per_stock,
    )
    if subscription_symbols:
        all_around_engine.add_stk_symbols(subscription_symbols)
        live_order_book_cache.ensure_symbols(subscription_symbols)

    detector = IntradaySignalDetector(
        thresholds=thresholds,
        watch_symbols=watch_symbols,
    )
    subscription = all_around_engine.subscribe()

    await websocket.send_json(
        {
            "type": "ready",
            "payload": {
                "watch_symbols": sorted(watch_symbols),
                "subscribed_symbols": subscription_symbols,
                "thresholds": thresholds.__dict__,
                "health": get_monitor_health(),
            },
        }
    )

    try:
        while True:
            tick = await subscription.get()
            events = detector.process_tick(tick)
            if not events:
                continue
            for event in events:
                try:
                    write_monitor_event(event, source="shioaji")
                except Exception:
                    pass
                await websocket.send_json({"type": "signal", "payload": event})
            await asyncio.sleep(0)
    except WebSocketDisconnect:
        return
    finally:
        all_around_engine.unsubscribe(subscription)
