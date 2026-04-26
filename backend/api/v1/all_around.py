from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from backend.engines.engine_tick_analysis import analyze_large_players
from backend.engines.engine_all_around import all_around_engine
from backend.engines.sinopac_session import sinopac_session

router = APIRouter()


def _norm_symbol(raw: str) -> str:
    s = str(raw or "").strip().upper()
    s = s.replace(".TW", "").replace(".TWO", "")
    return s


def _symbol_match(a: str, b: str) -> bool:
    na = _norm_symbol(a)
    nb = _norm_symbol(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    da = "".join(ch for ch in na if ch.isdigit())
    db = "".join(ch for ch in nb if ch.isdigit())
    return bool(da and db and da == db)


def _tick_dir_from_type(value: Any) -> str:
    try:
        v = int(value)
    except Exception:  # noqa: BLE001
        return "NONE"
    if v == 1:
        return "OUTER"
    if v == 2:
        return "INNER"
    return "NONE"


def _format_hms_from_ns(ts_ns: Any) -> str:
    try:
        ns = int(ts_ns)
        sec = ns / 1_000_000_000
        return __import__("datetime").datetime.fromtimestamp(sec).strftime("%H:%M:%S")
    except Exception:  # noqa: BLE001
        return ""


def _fetch_historical_ticks(symbol: str, lookback_days: int = 7) -> List[Dict[str, Any]]:
    api = sinopac_session.api or sinopac_session.connect()
    if api is None:
        return []

    try:
        contract = api.Contracts.Stocks.get(symbol) or api.Contracts.Stocks[symbol]
    except Exception:  # noqa: BLE001
        return []

    # Choose the latest trade date that has non-empty ticks.
    ticks_obj = None
    for i in range(lookback_days):
        d = str(date.today() - timedelta(days=i))
        try:
            t = api.ticks(contract=contract, date=d)
            if len(getattr(t, "close", []) or []) > 0:
                ticks_obj = t
                break
        except Exception:  # noqa: BLE001
            continue
    if ticks_obj is None:
        return []

    ts_list = list(getattr(ticks_obj, "ts", []) or [])
    close_list = list(getattr(ticks_obj, "close", []) or [])
    volume_list = list(getattr(ticks_obj, "volume", []) or [])
    tick_type_list = list(getattr(ticks_obj, "tick_type", []) or [])
    size = min(len(ts_list), len(close_list), len(volume_list), len(tick_type_list))
    out: List[Dict[str, Any]] = []
    for i in range(size):
        out.append(
            {
                "ts": _format_hms_from_ns(ts_list[i]),
                "symbol": symbol,
                "asset_type": "現貨",
                "price": float(close_list[i] or 0),
                "volume": int(volume_list[i] or 0),
                "tick_dir": _tick_dir_from_type(tick_type_list[i]),
            }
        )
    return out


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
        _norm_symbol(item)
        for item in raw_symbols.split(",")
        if item.strip()
    }
    if stock_symbols:
        all_around_engine.add_stk_symbols(sorted(stock_symbols))

    subscription = all_around_engine.subscribe()
    history = all_around_engine.get_recent_ticks(
        stock_symbols=None,
        include_futures=include_futures,
        limit=max(0, min(history_limit, 500)),
    )
    try:
        for tick in history:
            sym = tick.get("symbol", "")
            asset = tick.get("asset_type", "")
            if stock_symbols and any(_symbol_match(sym, s) for s in stock_symbols):
                await websocket.send_json(tick)
                continue
            if include_futures and asset == "期貨":
                await websocket.send_json(tick)
                continue
            if not stock_symbols and not include_futures:
                await websocket.send_json(tick)
                continue

        while True:
            tick = await subscription.get()
            sym = tick.get("symbol", "")
            asset = tick.get("asset_type", "")

            if stock_symbols and any(_symbol_match(sym, s) for s in stock_symbols):
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


@router.get("/api/v1/ticks/large_players/{symbol}")
async def get_large_players(symbol: str, pr: int = Query(97, ge=50, le=99)):
    """
    大單進出：依成交金額分位（PR）+ 100 萬元保底門檻。
    query: pr=97 表示第 97 百分位數（quantile 0.97）。
    """
    normalized = _norm_symbol(symbol)
    empty_payload = {
        "symbol": normalized,
        "source": "live_cache",
        "threshold": None,
        "buy_lots": 0,
        "sell_lots": 0,
        "net_lots": 0,
        "details": [],
    }
    if not normalized:
        return {
            **empty_payload,
            "message": "Invalid symbol",
        }

    try:
        rows = all_around_engine.get_recent_ticks(
            stock_symbols={normalized},
            include_futures=False,
            limit=5000,
        )

        stock_rows: List[Dict[str, Any]] = [
            r for r in rows
            if str(r.get("asset_type", "")) == "現貨" and _symbol_match(str(r.get("symbol", "")), normalized)
        ]
        source = "live_cache"
        if not stock_rows:
            stock_rows = _fetch_historical_ticks(normalized, lookback_days=7)
            source = "historical_ticks" if stock_rows else source

        if not stock_rows:
            return {
                **empty_payload,
                "source": source,
                "message": "No recent ticks available for this symbol",
            }

        analysis = analyze_large_players(stock_rows, normalized, percentile=pr / 100.0)
        analysis["source"] = source
        analysis["sample_size"] = len(stock_rows)
        return analysis
    except Exception as exc:  # noqa: BLE001
        return {
            **empty_payload,
            "message": f"Large players calculation failed: {exc}",
        }
