from __future__ import annotations

from datetime import date, timedelta
import math
from typing import Any, Dict, List

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from backend.engines.engine_tick_analysis import analyze_large_players
from backend.engines.engine_all_around import AssetType, all_around_engine
from backend.engines.engine_symbol_pool import (
    get_taifex_stock_future_codes_for_symbols,
    get_all_around_subscription_symbols,
    get_all_around_symbol_pool,
)
from backend.engines.sinopac_session import sinopac_session

router = APIRouter()

ALL_AROUND_TOP_N = 300
ALL_AROUND_MAX_WARRANTS_PER_STOCK = 80
DEFAULT_MIN_STOCK_AMOUNT = 1_000_000.0
DEFAULT_MIN_FUTURES_VOLUME = 10
DEFAULT_MIN_STOCK_FUTURES_VOLUME = 1
DEFAULT_MIN_WARRANT_VOLUME = 100
DEFAULT_MIN_WARRANT_AMOUNT = 100_000.0
ALL_AROUND_FUTURES_PREFIXES = ("TXF", "MXF")


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


def _parse_bool(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


def _parse_float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except Exception:  # noqa: BLE001
        return default


def _parse_int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return default


def _all_around_scope(
    top_n: int = ALL_AROUND_TOP_N,
    *,
    max_warrants_per_stock: int = ALL_AROUND_MAX_WARRANTS_PER_STOCK,
) -> tuple[set[str], List[str], Dict[str, str], set[str]]:
    profiles = get_all_around_symbol_pool(top_n=top_n)
    underlyings = [
        _norm_symbol(item.get("stock_id", ""))
        for item in profiles
        if item.get("stock_id")
    ]
    underlying_names = {
        _norm_symbol(item.get("stock_id", "")): str(item.get("name") or item.get("stock_id") or "")
        for item in profiles
        if item.get("stock_id")
    }
    stock_side_symbols = {
        _norm_symbol(symbol)
        for symbol in get_all_around_subscription_symbols(
            top_n=top_n,
            max_warrants_per_stock=max_warrants_per_stock,
        )
        if symbol
    }
    stock_future_symbols = set(
        all_around_engine.add_stock_futures_by_product_codes(
            get_taifex_stock_future_codes_for_symbols(underlyings)
        )
    )
    if not stock_future_symbols:
        stock_future_symbols = set(
            all_around_engine.add_stock_futures_for_underlyings(
                underlyings,
                underlying_names,
            )
        )
    return stock_side_symbols, underlyings, underlying_names, stock_future_symbols


def _is_allowed_all_around_future(symbol: str) -> bool:
    normalized = _norm_symbol(symbol)
    return any(normalized.startswith(prefix) for prefix in ALL_AROUND_FUTURES_PREFIXES)


def _percentile(values: List[float], pct: float) -> float:
    clean = sorted(v for v in values if math.isfinite(v) and v > 0)
    if not clean:
        return 0.0
    if len(clean) == 1:
        return clean[0]

    p = max(0.0, min(1.0, pct))
    pos = (len(clean) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return clean[lo]
    return clean[lo] + (clean[hi] - clean[lo]) * (pos - lo)


def _stock_large_order_floor(price: float, base_amount_floor: float) -> tuple[int, float]:
    """
    Price-band floors prevent high-priced stocks from treating one lot as large.
    The rolling percentile below can only raise these floors, not lower them.
    """
    if price >= 1000:
        return 3, max(base_amount_floor, 3_000_000.0)
    if price >= 500:
        return 5, max(base_amount_floor, 2_500_000.0)
    if price >= 200:
        return 10, max(base_amount_floor, 2_000_000.0)
    if price >= 100:
        return 20, max(base_amount_floor, 2_000_000.0)
    if price >= 50:
        return 30, max(base_amount_floor, 2_000_000.0)
    return 50, max(base_amount_floor, 2_000_000.0)


def _recent_stock_thresholds(
    symbol: str,
    *,
    base_amount_floor: float,
    price: float,
) -> tuple[int, float]:
    lot_floor, amount_floor = _stock_large_order_floor(price, base_amount_floor)
    rows = all_around_engine.get_recent_ticks(
        stock_symbols={_norm_symbol(symbol)},
        include_futures=False,
        limit=300,
    )
    samples = [
        r for r in rows
        if _symbol_match(str(r.get("symbol", "")), symbol)
        and str(r.get("asset_type", "")) == AssetType.STOCK.value
        and float(r.get("price") or 0) > 0
        and int(r.get("volume") or 0) > 0
    ]
    if len(samples) < 30:
        return lot_floor, amount_floor

    amounts = [
        float(r.get("price") or 0) * int(r.get("volume") or 0) * 1000.0
        for r in samples
    ]
    volumes = [float(int(r.get("volume") or 0)) for r in samples]
    dynamic_amount = _percentile(amounts, 0.95)
    dynamic_lots = int(math.ceil(_percentile(volumes, 0.80)))
    return max(lot_floor, dynamic_lots), max(amount_floor, dynamic_amount)


def _is_large_tick(
    tick: Dict[str, Any],
    *,
    min_stock_amount: float,
    min_futures_volume: int,
) -> bool:
    try:
        price = float(tick.get("price") or 0)
        volume = int(tick.get("volume") or 0)
    except Exception:  # noqa: BLE001
        return False

    if price <= 0 or volume <= 0:
        return False

    asset = str(tick.get("asset_type", ""))
    if asset == AssetType.FUTURES.value:
        if not _is_allowed_all_around_future(str(tick.get("symbol", ""))):
            return volume >= DEFAULT_MIN_STOCK_FUTURES_VOLUME
        return volume >= min_futures_volume

    amount = price * volume * 1000.0
    if asset in (AssetType.CALL_WARRANT.value, AssetType.PUT_WARRANT.value):
        return volume >= DEFAULT_MIN_WARRANT_VOLUME and amount >= DEFAULT_MIN_WARRANT_AMOUNT

    lot_threshold, amount_threshold = _recent_stock_thresholds(
        str(tick.get("symbol", "")),
        base_amount_floor=min_stock_amount,
        price=price,
    )
    return volume >= lot_threshold and amount >= amount_threshold


def _should_send_tick(
    tick: Dict[str, Any],
    *,
    stock_symbols: set[str],
    futures_symbols: set[str],
    include_futures: bool,
    large_only: bool,
    min_stock_amount: float,
    min_futures_volume: int,
) -> bool:
    sym = str(tick.get("symbol", ""))
    asset = str(tick.get("asset_type", ""))

    in_stock_scope = bool(
        stock_symbols and any(_symbol_match(sym, s) for s in stock_symbols)
    )
    in_futures_scope = (
        include_futures
        and asset == AssetType.FUTURES.value
        and (
            _norm_symbol(sym) in futures_symbols
            or _is_allowed_all_around_future(sym)
        )
    )
    in_unscoped_feed = not stock_symbols and not include_futures

    if not (in_stock_scope or in_futures_scope or in_unscoped_feed):
        return False

    if large_only and not _is_large_tick(
        tick,
        min_stock_amount=min_stock_amount,
        min_futures_volume=min_futures_volume,
    ):
        return False

    return True


def _latest_ticks_by_symbol(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        sym = _norm_symbol(str(row.get("symbol", "")))
        if sym:
            latest[sym] = row
    return latest


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


@router.get("/api/v1/all-around/scope")
async def get_all_around_scope(top_n: int = Query(ALL_AROUND_TOP_N, ge=1, le=500)):
    symbols = get_all_around_symbol_pool(top_n=top_n)
    stock_side_symbols = get_all_around_subscription_symbols(
        top_n=top_n,
        max_warrants_per_stock=ALL_AROUND_MAX_WARRANTS_PER_STOCK,
    )
    return {
        "top_n": top_n,
        "symbols": symbols,
        "stock_side_symbol_count": len(stock_side_symbols),
        "max_warrants_per_stock": ALL_AROUND_MAX_WARRANTS_PER_STOCK,
        "taifex_stock_future_product_codes": len(
            get_taifex_stock_future_codes_for_symbols(
                [_norm_symbol(item.get("stock_id", "")) for item in symbols]
            )
        ),
        "futures_prefixes": list(ALL_AROUND_FUTURES_PREFIXES),
        "large_order_defaults": {
            "method": "stock: price-band lot floor + amount floor + rolling P95 amount/P80 lots",
            "min_stock_amount_floor": DEFAULT_MIN_STOCK_AMOUNT,
            "min_futures_volume": DEFAULT_MIN_FUTURES_VOLUME,
            "min_stock_futures_volume": DEFAULT_MIN_STOCK_FUTURES_VOLUME,
            "min_warrant_volume": DEFAULT_MIN_WARRANT_VOLUME,
            "min_warrant_amount": DEFAULT_MIN_WARRANT_AMOUNT,
        },
    }


@router.get("/api/v1/all-around/futures-spreads")
async def get_all_around_futures_spreads(
    top_n: int = Query(ALL_AROUND_TOP_N, ge=1, le=500),
    limit: int = Query(80, ge=1, le=300),
):
    stock_symbols, underlyings, underlying_names, futures_symbols = _all_around_scope(top_n=top_n)
    futures_map = all_around_engine.get_stock_futures_underlying_map()
    futures_codes = set(futures_map.keys()) | futures_symbols
    rows = all_around_engine.get_recent_ticks(
        stock_symbols=stock_symbols,
        include_futures=True,
        limit=10_000,
    )
    latest = _latest_ticks_by_symbol(rows)

    out: List[Dict[str, Any]] = []
    for fut_code, underlying in futures_map.items():
        fcode = _norm_symbol(fut_code)
        sid = _norm_symbol(underlying)
        if fcode not in futures_codes or sid not in underlyings:
            continue

        spot = latest.get(sid)
        fut = latest.get(fcode)
        if not spot or not fut:
            continue

        spot_price = float(spot.get("price") or 0)
        fut_price = float(fut.get("price") or 0)
        if spot_price <= 0 or fut_price <= 0:
            continue

        basis = fut_price - spot_price
        out.append(
            {
                "id": fcode,
                "underlying_symbol": sid,
                "underlying_name": underlying_names.get(sid) or str(spot.get("name") or sid),
                "futures_symbol": fcode,
                "futures_name": str(fut.get("name") or fcode),
                "spot_price": spot_price,
                "futures_price": fut_price,
                "basis_points": basis,
                "basis_pct": (basis / spot_price) * 100.0,
                "spot_ts": spot.get("ts"),
                "futures_ts": fut.get("ts"),
            }
        )

    out.sort(key=lambda item: abs(float(item.get("basis_pct") or 0)), reverse=True)
    return {
        "top_n": top_n,
        "limit": limit,
        "subscribed_stock_futures": len(futures_map),
        "rows": out[:limit],
    }


@router.get("/api/v1/all-around/history")
async def get_all_around_history(
    limit: int = Query(2000, ge=1, le=100_000),
    include_futures: bool = Query(True),
):
    stock_symbols, _, _, _ = _all_around_scope()
    rows = all_around_engine.get_recent_ticks(
        stock_symbols=stock_symbols,
        include_futures=include_futures,
        limit=limit,
    )
    return {
        "limit": limit,
        "count": len(rows),
        "rows": rows,
        "health": all_around_engine.get_health(),
    }


@router.websocket("/ws/all-around-ticker")
async def all_around_ticker_ws(websocket: WebSocket):
    """
    全方位即時 Tick 串流。

    Query params:
      symbols        逗號分隔的股票代碼（可選）
      scope          all_around 時使用指定市值前 300 股票、關聯權證、股票期貨 + TXF/MXF
      include_futures 是否包含期貨 tick（true/false）
      large_only     true 時只推送大單
      min_stock_amount 現貨大單成交金額門檻，預設 1000000
      min_futures_volume 期貨大單口數門檻，預設 10
      history_limit   回補歷史筆數上限（預設 120，最大 2000）

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
    scope = websocket.query_params.get("scope", "")
    include_futures = _parse_bool(websocket.query_params.get("include_futures"), False)
    large_only = _parse_bool(websocket.query_params.get("large_only"), False)
    min_stock_amount = max(
        0.0,
        _parse_float(websocket.query_params.get("min_stock_amount"), DEFAULT_MIN_STOCK_AMOUNT),
    )
    min_futures_volume = max(
        1,
        _parse_int(websocket.query_params.get("min_futures_volume"), DEFAULT_MIN_FUTURES_VOLUME),
    )
    history_limit = _parse_int(websocket.query_params.get("history_limit"), 120)

    stock_symbols = {
        _norm_symbol(item)
        for item in raw_symbols.split(",")
        if item.strip()
    }
    futures_symbols: set[str] = set()
    if not stock_symbols and scope == "all_around":
        stock_symbols, _, _, futures_symbols = _all_around_scope()
        include_futures = True

    if stock_symbols:
        all_around_engine.add_stk_symbols(sorted(stock_symbols))

    subscription = all_around_engine.subscribe()
    history = all_around_engine.get_recent_ticks(
        stock_symbols=stock_symbols if stock_symbols else None,
        include_futures=include_futures,
        limit=max(0, min(history_limit, 2000)),
    )
    try:
        for tick in history:
            if _should_send_tick(
                tick,
                stock_symbols=stock_symbols,
                futures_symbols=futures_symbols,
                include_futures=include_futures,
                large_only=large_only,
                min_stock_amount=min_stock_amount,
                min_futures_volume=min_futures_volume,
            ):
                await websocket.send_json(tick)

        while True:
            tick = await subscription.get()
            if _should_send_tick(
                tick,
                stock_symbols=stock_symbols,
                futures_symbols=futures_symbols,
                include_futures=include_futures,
                large_only=large_only,
                min_stock_amount=min_stock_amount,
                min_futures_volume=min_futures_volume,
            ):
                await websocket.send_json(tick)
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
