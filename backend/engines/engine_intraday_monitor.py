from __future__ import annotations

import datetime as dt
import math
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Deque, Dict, Iterable, List, Optional, Set, Tuple

from backend.db.connection import duck_read
from backend.db import queries as db_queries
from backend.engines.engine_all_around import all_around_engine
from backend.engines.engine_scalp_trigger import (
    IntradayScalpEngine,
    ScalpSignal,
    ScalpTriggerConfig,
)
from backend.engines.sinopac_session import sinopac_session

_TZ = dt.timezone(dt.timedelta(hours=8))


def _normalize_symbol(raw: Any) -> str:
    return str(raw or "").strip().upper().replace(".TW", "").replace(".TWO", "")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, Decimal):
            return float(value)
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def _now_hms_ms() -> str:
    return dt.datetime.now(_TZ).strftime("%H:%M:%S.%f")[:-3]


def _is_put_warrant(cp: Any, name: Any = "") -> bool:
    text = f"{cp or ''} {name or ''}".upper()
    return "售" in text or "PUT" in text


@dataclass(frozen=True)
class MonitorThresholds:
    stock_lot_threshold: int = 50
    warrant_lot_threshold: int = 100
    move_window_sec: int = 60
    move_pct_threshold: float = 1.5
    continuous_window_sec: int = 3
    continuous_min_count: int = 3
    scalp_enabled: bool = True
    scalp_consecutive_window_sec: int = 5
    scalp_consecutive_min_count: int = 30
    scalp_consecutive_min_volume: int = 300
    scalp_reversal_min_lots: int = 20
    scalp_vwap_deviation_pct: float = 2.0
    scalp_wall_lots: int = 500
    scalp_wall_avg_volume_multiple: float = 2.0
    scalp_no_new_extreme_sec: float = 2.0
    scalp_spoof_min_lots: int = 200
    scalp_spoof_drop_pct: float = 0.65


WarrantMap = Dict[str, Dict[str, str]]
BranchTagMap = Dict[str, List[Dict[str, Any]]]


class LiveOrderBookCache:
    def __init__(self) -> None:
        self._books: Dict[str, Dict[str, Any]] = {}
        self._subscribed: Set[str] = set()
        self._registered = False
        self._last_error: Optional[str] = None
        self._lock = threading.RLock()

    def register_handler(self) -> None:
        if self._registered:
            return
        sinopac_session.add_stk_bidask_handler(self._handle_bidask_sync)
        self._registered = True

    def ensure_symbols(self, symbols: Iterable[str]) -> None:
        self.register_handler()
        api = sinopac_session.api
        if api is None:
            return
        try:
            import shioaji.constant as sjc
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            return

        for raw in symbols:
            symbol = _normalize_symbol(raw)
            if not symbol or symbol in self._subscribed:
                continue
            contract = None
            try:
                contract = api.Contracts.Stocks[symbol]
            except Exception:
                try:
                    contract = api.Contracts.Stocks.get(symbol)
                except Exception:
                    contract = None
            if contract is None:
                continue
            try:
                api.quote.subscribe(
                    contract,
                    quote_type=sjc.QuoteType.BidAsk,
                    version=sjc.QuoteVersion.v1,
                )
                self._subscribed.add(symbol)
            except Exception as exc:  # noqa: BLE001
                self._last_error = f"{symbol}: {exc}"

    def _handle_bidask_sync(self, exchange: Any, bidask: Any) -> None:
        code = _normalize_symbol(getattr(bidask, "code", ""))
        if not code:
            return
        bid_prices = self._coerce_levels(bidask, ["bid_price", "buy_price", "bid_prices", "bids"])
        ask_prices = self._coerce_levels(bidask, ["ask_price", "sell_price", "ask_prices", "asks"])
        bid_volumes = self._coerce_levels(bidask, ["bid_volume", "buy_volume", "bid_volumes", "bid_size"])
        ask_volumes = self._coerce_levels(bidask, ["ask_volume", "sell_volume", "ask_volumes", "ask_size"])
        if not bid_prices and not ask_prices:
            return

        ts_raw = getattr(bidask, "datetime", None)
        if isinstance(ts_raw, dt.datetime):
            ts = ts_raw.strftime("%H:%M:%S.%f")[:-3]
        else:
            ts = _now_hms_ms()

        with self._lock:
            self._books[code] = {
                "bid": self._pack_levels(bid_prices, bid_volumes),
                "ask": self._pack_levels(ask_prices, ask_volumes),
                "ts": ts,
                "source": "live_bidask",
            }

    @staticmethod
    def _coerce_levels(obj: Any, names: Iterable[str]) -> List[float]:
        for name in names:
            try:
                value = getattr(obj, name, None)
            except Exception:
                continue
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                return [_safe_float(v) for v in value if _safe_float(v) > 0]
            val = _safe_float(value)
            if val > 0:
                return [val]
        return []

    @staticmethod
    def _pack_levels(prices: List[float], volumes: List[float]) -> List[Dict[str, float]]:
        levels: List[Dict[str, float]] = []
        for i, price in enumerate(prices[:5]):
            volume = volumes[i] if i < len(volumes) else 0.0
            levels.append({"price": round(price, 4), "volume": volume})
        return levels

    def get(self, symbol: str) -> Optional[Dict[str, Any]]:
        code = _normalize_symbol(symbol)
        with self._lock:
            book = self._books.get(code)
            if not book:
                return None
            return {
                "bid": list(book.get("bid") or []),
                "ask": list(book.get("ask") or []),
                "ts": book.get("ts"),
                "source": book.get("source", "live_bidask"),
            }

    def health(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "registered": self._registered,
                "subscribed": len(self._subscribed),
                "cached_books": len(self._books),
                "last_error": self._last_error,
            }


live_order_book_cache = LiveOrderBookCache()


def load_warrant_underlying_map() -> WarrantMap:
    try:
        with duck_read() as conn:
            rows = conn.execute(
                """
                SELECT warrant_code, warrant_name, underlying_symbol, underlying_name, cp
                FROM warrant_master
                """
            ).fetchall()
    except Exception:
        return {}

    out: WarrantMap = {}
    for code, name, underlying, underlying_name, cp in rows:
        c = _normalize_symbol(code)
        u = _normalize_symbol(underlying)
        if not c or not u:
            continue
        out[c] = {
            "warrant_code": c,
            "warrant_name": str(name or c),
            "underlying_symbol": u,
            "underlying_name": str(underlying_name or u),
            "cp": str(cp or ""),
        }
    return out


def load_overnight_branch_tags() -> BranchTagMap:
    tags: BranchTagMap = defaultdict(list)

    try:
        with duck_read() as conn:
            rows = conn.execute(
                """
                SELECT stock_id, branch_name, side
                FROM key_branch_trades
                WHERE trade_date = (SELECT MAX(trade_date) FROM key_branch_trades)
                LIMIT 500
                """
            ).fetchall()
        for stock_id, branch_name, side in rows:
            sid = _normalize_symbol(stock_id)
            if not sid:
                continue
            raw_side = str(side or "").upper()
            direction = "sell" if raw_side.startswith("S") else "buy"
            tags[sid].append(
                {
                    "label": "隔日沖倒貨警戒" if direction == "sell" else "隔日沖買超警戒",
                    "branch": str(branch_name or ""),
                    "side": direction,
                    "net_lots": None,
                }
            )
    except Exception:
        pass

    if tags:
        return {k: v[:3] for k, v in tags.items()}

    try:
        with duck_read() as conn:
            rows = conn.execute(
                """
                SELECT stock_id, branch_name, net_shares
                FROM branch_trading
                WHERE trade_date = (SELECT MAX(trade_date) FROM branch_trading)
                ORDER BY ABS(COALESCE(net_shares, 0)) DESC
                LIMIT 800
                """
            ).fetchall()
    except Exception:
        return {}

    for stock_id, branch_name, net_shares in rows:
        sid = _normalize_symbol(stock_id)
        net = _safe_int(net_shares)
        if not sid or net == 0:
            continue
        direction = "buy" if net > 0 else "sell"
        lots = int(round(abs(net) / 1000)) if abs(net) >= 1000 else abs(net)
        tags[sid].append(
            {
                "label": "隔日沖倒貨警戒" if direction == "sell" else "隔日沖買超警戒",
                "branch": str(branch_name or ""),
                "side": direction,
                "net_lots": lots,
            }
        )

    return {k: v[:3] for k, v in tags.items()}


def load_related_warrant_codes(
    underlying_symbols: Iterable[str],
    *,
    max_per_underlying: int = 40,
) -> List[str]:
    symbols = [_normalize_symbol(s) for s in underlying_symbols]
    symbols = [s for s in dict.fromkeys(symbols) if s]
    if not symbols:
        return []

    out: List[str] = []
    try:
        with duck_read() as conn:
            for sid in symbols:
                rows = conn.execute(
                    """
                    SELECT warrant_code
                    FROM warrant_master
                    WHERE trim(cast(underlying_symbol AS VARCHAR)) = ?
                    ORDER BY expiry_date ASC, warrant_code ASC
                    LIMIT ?
                    """,
                    [sid, max_per_underlying],
                ).fetchall()
                out.extend(_normalize_symbol(r[0]) for r in rows if r and r[0])
    except Exception:
        return []
    return [c for c in dict.fromkeys(out) if c]


def build_monitor_subscription_symbols(
    raw_symbols: Iterable[str],
    *,
    include_warrants: bool = True,
    max_warrants_per_stock: int = 40,
) -> List[str]:
    base = [_normalize_symbol(s) for s in raw_symbols]
    base = [s for s in dict.fromkeys(base) if s]
    if not include_warrants:
        return base
    warrant_codes = load_related_warrant_codes(
        base,
        max_per_underlying=max_warrants_per_stock,
    )
    return [s for s in dict.fromkeys([*base, *warrant_codes]) if s]


class IntradaySignalDetector:
    def __init__(
        self,
        *,
        thresholds: MonitorThresholds,
        watch_symbols: Optional[Set[str]] = None,
    ) -> None:
        self.thresholds = thresholds
        self.watch_symbols = {_normalize_symbol(s) for s in (watch_symbols or set()) if s}
        self.warrant_map = load_warrant_underlying_map()
        self.branch_tags = load_overnight_branch_tags()
        self._price_windows: Dict[str, Deque[Tuple[float, float]]] = defaultdict(deque)
        self._side_windows: Dict[str, Dict[str, Deque[Tuple[float, int, float]]]] = defaultdict(
            lambda: {"OUTER": deque(), "INNER": deque()}
        )
        self._scalp_engine = IntradayScalpEngine(
            ScalpTriggerConfig(
                consecutive_window_sec=thresholds.scalp_consecutive_window_sec,
                consecutive_min_count=thresholds.scalp_consecutive_min_count,
                consecutive_min_volume=thresholds.scalp_consecutive_min_volume,
                reversal_min_lots=thresholds.scalp_reversal_min_lots,
                block_trade_lots=thresholds.stock_lot_threshold,
                mega_trade_lots=max(thresholds.stock_lot_threshold * 2, 100),
                vwap_deviation_pct=thresholds.scalp_vwap_deviation_pct,
                no_new_extreme_sec=thresholds.scalp_no_new_extreme_sec,
                wall_lots_absolute=thresholds.scalp_wall_lots,
                wall_avg_volume_multiple=thresholds.scalp_wall_avg_volume_multiple,
                spoof_min_lots=thresholds.scalp_spoof_min_lots,
                spoof_drop_pct=thresholds.scalp_spoof_drop_pct,
            )
        )
        self._last_fired: Dict[str, float] = {}
        self._last_reference_reload = time.time()

    def process_tick(self, tick: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._refresh_reference_data_if_needed()

        symbol = _normalize_symbol(tick.get("symbol"))
        if not symbol:
            return []

        warrant_info = self.warrant_map.get(symbol)
        related_symbol = _normalize_symbol(warrant_info.get("underlying_symbol")) if warrant_info else symbol
        if self.watch_symbols and symbol not in self.watch_symbols and related_symbol not in self.watch_symbols:
            return []

        price = _safe_float(tick.get("price"))
        volume = _safe_int(tick.get("volume"))
        tick_dir = str(tick.get("tick_dir") or "NONE").upper()
        if price <= 0 or volume <= 0:
            return []

        now = time.time()
        if warrant_info is not None:
            events = self._detect_warrant_linkage(tick, warrant_info, now)
            if self.thresholds.scalp_enabled:
                events.extend(self._detect_warrant_scalp_signals(tick, warrant_info, now))
            return events

        events: List[Dict[str, Any]] = []
        if self.thresholds.scalp_enabled:
            order_book = live_order_book_cache.get(symbol)
            for signal in self._scalp_engine.process_tick(tick, order_book=order_book, now=now):
                events.append(self._make_scalp_event(tick, signal, now))

        large = self._detect_single_large_stock_order(tick, now)
        if large:
            events.append(large)

        continuous = self._detect_continuous_stock_orders(tick, now)
        if continuous:
            events.append(continuous)

        move = self._detect_rapid_move(tick, now)
        if move:
            events.append(move)

        return events

    def _refresh_reference_data_if_needed(self) -> None:
        now = time.time()
        if now - self._last_reference_reload < 600:
            return
        self.warrant_map = load_warrant_underlying_map()
        self.branch_tags = load_overnight_branch_tags()
        self._last_reference_reload = now

    def _detect_single_large_stock_order(self, tick: Dict[str, Any], now: float) -> Optional[Dict[str, Any]]:
        volume = _safe_int(tick.get("volume"))
        tick_dir = str(tick.get("tick_dir") or "NONE").upper()
        if volume < self.thresholds.stock_lot_threshold or tick_dir not in {"OUTER", "INNER"}:
            return None

        side = "buy" if tick_dir == "OUTER" else "sell"
        return self._make_event(
            tick=tick,
            event_type="stock_large_buy" if side == "buy" else "stock_large_sell",
            event_label="現貨大單買" if side == "buy" else "現貨大單賣",
            side=side,
            severity="high" if volume >= self.thresholds.stock_lot_threshold * 2 else "normal",
            message=f"單筆 {volume:,} 張{'外盤買進' if side == 'buy' else '內盤賣出'}",
            now=now,
        )

    def _detect_continuous_stock_orders(self, tick: Dict[str, Any], now: float) -> Optional[Dict[str, Any]]:
        symbol = _normalize_symbol(tick.get("symbol"))
        tick_dir = str(tick.get("tick_dir") or "NONE").upper()
        if tick_dir not in {"OUTER", "INNER"}:
            return None

        window = self._side_windows[symbol][tick_dir]
        window.append((now, _safe_int(tick.get("volume")), _safe_float(tick.get("price"))))
        cutoff = now - max(1, self.thresholds.continuous_window_sec)
        while window and window[0][0] < cutoff:
            window.popleft()

        count = len(window)
        cum_volume = sum(item[1] for item in window)
        if count < self.thresholds.continuous_min_count or cum_volume < self.thresholds.stock_lot_threshold:
            return None

        side = "buy" if tick_dir == "OUTER" else "sell"
        key = f"continuous:{symbol}:{side}"
        if not self._passes_cooldown(key, now, max(2.0, self.thresholds.continuous_window_sec)):
            return None

        return self._make_event(
            tick=tick,
            event_type="continuous_buy" if side == "buy" else "continuous_sell",
            event_label="連續大單買" if side == "buy" else "連續大單賣",
            side=side,
            severity="high",
            message=(
                f"{self.thresholds.continuous_window_sec} 秒內 {count} 筆，"
                f"累計 {cum_volume:,} 張"
            ),
            count=count,
            cum_volume=cum_volume,
            window_sec=self.thresholds.continuous_window_sec,
            now=now,
        )

    def _detect_rapid_move(self, tick: Dict[str, Any], now: float) -> Optional[Dict[str, Any]]:
        symbol = _normalize_symbol(tick.get("symbol"))
        price = _safe_float(tick.get("price"))
        if price <= 0:
            return None

        window = self._price_windows[symbol]
        window.append((now, price))
        cutoff = now - max(1, self.thresholds.move_window_sec)
        while window and window[0][0] < cutoff:
            window.popleft()
        if len(window) < 2:
            return None

        base_price = window[0][1]
        if base_price <= 0:
            return None
        pct = (price - base_price) / base_price * 100.0
        if abs(pct) < self.thresholds.move_pct_threshold:
            return None

        side = "buy" if pct > 0 else "sell"
        key = f"move:{symbol}:{side}"
        if not self._passes_cooldown(key, now, max(10.0, self.thresholds.move_window_sec / 2)):
            return None

        return self._make_event(
            tick=tick,
            event_type="rapid_rise" if pct > 0 else "rapid_drop",
            event_label="急拉突破" if pct > 0 else "急殺跌破",
            side=side,
            severity="high",
            message=f"{self.thresholds.move_window_sec} 秒內 {pct:+.2f}%",
            pct_move=round(pct, 2),
            window_sec=self.thresholds.move_window_sec,
            now=now,
        )

    def _detect_warrant_linkage(
        self,
        tick: Dict[str, Any],
        warrant_info: Dict[str, str],
        now: float,
    ) -> List[Dict[str, Any]]:
        volume = _safe_int(tick.get("volume"))
        tick_dir = str(tick.get("tick_dir") or "NONE").upper()
        if volume < self.thresholds.warrant_lot_threshold or tick_dir not in {"OUTER", "INNER"}:
            return []

        symbol = _normalize_symbol(tick.get("symbol"))
        is_put = _is_put_warrant(warrant_info.get("cp"), warrant_info.get("warrant_name"))
        underlying = _normalize_symbol(warrant_info.get("underlying_symbol"))
        underlying_name = str(warrant_info.get("underlying_name") or underlying)

        if tick_dir == "OUTER":
            hedge_side = "sell" if is_put else "buy"
            action = "買進"
        else:
            hedge_side = "buy" if is_put else "sell"
            action = "賣出"

        hedge_text = "避險買盤" if hedge_side == "buy" else "避險賣盤"
        label = "權證大單敲進" if tick_dir == "OUTER" else "權證大單倒出"
        key = f"warrant:{symbol}:{tick_dir}"
        if not self._passes_cooldown(key, now, 1.5):
            return []

        event = self._make_event(
            tick=tick,
            event_type="warrant_spot_link",
            event_label=label,
            side=hedge_side,
            severity="high",
            message=(
                f"{symbol} {action} {volume:,} 張，留意現貨 "
                f"{underlying} {underlying_name} {hedge_text}"
            ),
            related_symbol=underlying,
            related_name=underlying_name,
            warrant_symbol=symbol,
            warrant_name=str(warrant_info.get("warrant_name") or tick.get("name") or symbol),
            now=now,
        )
        return [event]

    def _detect_warrant_scalp_signals(
        self,
        tick: Dict[str, Any],
        warrant_info: Dict[str, str],
        now: float,
    ) -> List[Dict[str, Any]]:
        underlying = _normalize_symbol(warrant_info.get("underlying_symbol"))
        if not underlying:
            return []
        signals = self._scalp_engine.process_warrant_tick(
            tick,
            underlying_symbol=underlying,
            is_put=_is_put_warrant(warrant_info.get("cp"), warrant_info.get("warrant_name")),
            now=now,
        )
        events: List[Dict[str, Any]] = []
        for signal in signals:
            events.append(
                self._make_scalp_event(
                    tick,
                    signal,
                    now,
                    related_name=str(warrant_info.get("underlying_name") or underlying),
                    warrant_name=str(warrant_info.get("warrant_name") or tick.get("name") or ""),
                )
            )
        return events

    def _make_scalp_event(
        self,
        tick: Dict[str, Any],
        signal: ScalpSignal,
        now: float,
        *,
        related_name: Optional[str] = None,
        warrant_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        target_symbol = _normalize_symbol(signal.related_symbol or signal.symbol)
        event_tick = dict(tick)
        event_tick["symbol"] = signal.warrant_symbol or _normalize_symbol(signal.symbol)
        event_tick["price"] = signal.price
        event_tick["volume"] = signal.volume
        event = self._make_event(
            tick=event_tick,
            event_type=signal.kind,
            event_label=signal.label,
            side=signal.side,
            severity=signal.severity,
            message=signal.message,
            related_symbol=target_symbol,
            related_name=related_name or db_queries.get_stock_name(target_symbol),
            warrant_symbol=signal.warrant_symbol,
            warrant_name=warrant_name,
            count=(signal.context.get("run") or {}).get("count"),
            cum_volume=(signal.context.get("run") or {}).get("volume"),
            now=now,
        )
        event["scalp_context"] = signal.context
        return event

    def _passes_cooldown(self, key: str, now: float, cooldown_sec: float) -> bool:
        prev = self._last_fired.get(key)
        if prev is not None and now - prev < cooldown_sec:
            return False
        self._last_fired[key] = now
        return True

    def _make_event(
        self,
        *,
        tick: Dict[str, Any],
        event_type: str,
        event_label: str,
        side: str,
        severity: str,
        message: str,
        now: float,
        related_symbol: Optional[str] = None,
        related_name: Optional[str] = None,
        warrant_symbol: Optional[str] = None,
        warrant_name: Optional[str] = None,
        count: Optional[int] = None,
        cum_volume: Optional[int] = None,
        pct_move: Optional[float] = None,
        window_sec: Optional[int] = None,
    ) -> Dict[str, Any]:
        symbol = _normalize_symbol(tick.get("symbol"))
        target_symbol = _normalize_symbol(related_symbol or symbol)
        tag_items = self.branch_tags.get(target_symbol, [])
        tag = ""
        if tag_items:
            first = tag_items[0]
            branch = str(first.get("branch") or "")
            tag = f"{first.get('label')}{f'：{branch}' if branch else ''}"

        return {
            "id": f"{int(now * 1000)}-{uuid.uuid4().hex[:6]}",
            "time": _now_hms_ms(),
            "symbol": symbol,
            "name": str(tick.get("name") or symbol),
            "instrument_type": "warrant" if warrant_symbol else "stock",
            "event_type": event_type,
            "event_label": event_label,
            "side": side,
            "severity": severity,
            "price": round(_safe_float(tick.get("price")), 4),
            "volume": _safe_int(tick.get("volume")),
            "tag": tag,
            "tag_items": tag_items,
            "message": message,
            "related_symbol": target_symbol,
            "related_name": related_name or db_queries.get_stock_name(target_symbol),
            "warrant_symbol": warrant_symbol,
            "warrant_name": warrant_name,
            "count": count,
            "cum_volume": cum_volume,
            "pct_move": pct_move,
            "window_sec": window_sec,
        }


def get_monitor_health() -> Dict[str, Any]:
    warrant_map = load_warrant_underlying_map()
    branch_tags = load_overnight_branch_tags()
    health = all_around_engine.get_health()
    return {
        "all_around": health,
        "shioaji_connected": bool(sinopac_session.is_connected),
        "shioaji_error": sinopac_session.last_error,
        "warrant_mapping_count": len(warrant_map),
        "overnight_branch_symbol_count": len(branch_tags),
        "order_book": live_order_book_cache.health(),
    }


def _coerce_list_attr(obj: Any, names: Iterable[str]) -> List[float]:
    for name in names:
        try:
            value = getattr(obj, name, None)
        except Exception:
            continue
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            return [_safe_float(v) for v in value if _safe_float(v) > 0]
        val = _safe_float(value)
        if val > 0:
            return [val]
    return []


def _snapshot_order_book(symbol: str) -> Dict[str, List[Dict[str, float]]]:
    live_book = live_order_book_cache.get(symbol)
    if live_book and (live_book.get("bid") or live_book.get("ask")):
        return live_book

    api = sinopac_session.api
    if api is None:
        return {"bid": [], "ask": []}

    contract = None
    try:
        contract = api.Contracts.Stocks[symbol]
    except Exception:
        try:
            contract = api.Contracts.Stocks.get(symbol)
        except Exception:
            contract = None
    if contract is None:
        return {"bid": [], "ask": []}

    try:
        snaps = api.snapshots([contract]) or []
    except Exception:
        return {"bid": [], "ask": []}
    if not snaps:
        return {"bid": [], "ask": []}

    snap = snaps[0]
    bid_prices = _coerce_list_attr(snap, ["bid_price", "buy_price", "bids", "bid"])
    ask_prices = _coerce_list_attr(snap, ["ask_price", "sell_price", "asks", "ask"])
    bid_volumes = _coerce_list_attr(snap, ["bid_volume", "buy_volume", "bid_size", "bidsize"])
    ask_volumes = _coerce_list_attr(snap, ["ask_volume", "sell_volume", "ask_size", "asksize"])

    def pack(prices: List[float], volumes: List[float]) -> List[Dict[str, float]]:
        levels: List[Dict[str, float]] = []
        for i, price in enumerate(prices[:5]):
            volume = volumes[i] if i < len(volumes) else 0
            levels.append({"price": round(price, 4), "volume": volume})
        return levels

    return {
        "bid": pack(bid_prices, bid_volumes),
        "ask": pack(ask_prices, ask_volumes),
        "source": "snapshot",
        "ts": _now_hms_ms(),
    }


def get_monitor_micro_snapshot(symbol: str) -> Dict[str, Any]:
    target = _normalize_symbol(symbol)
    if not target:
        return {
            "symbol": "",
            "name": "",
            "order_book": {"bid": [], "ask": []},
            "tape": [],
            "related_warrants": [],
        }

    warrant_map = load_warrant_underlying_map()
    warrant_info = warrant_map.get(target)
    underlying = _normalize_symbol(warrant_info.get("underlying_symbol")) if warrant_info else target
    name = (
        str(warrant_info.get("warrant_name"))
        if warrant_info
        else db_queries.get_stock_name(target)
    )

    recent_target = all_around_engine.get_recent_ticks(
        stock_symbols={target},
        include_futures=False,
        limit=80,
    )
    tape = list(reversed(recent_target[-40:]))

    recent_all = all_around_engine.get_recent_ticks(limit=5000)
    aggregate: Dict[str, Dict[str, Any]] = {}
    for tick in recent_all:
        code = _normalize_symbol(tick.get("symbol"))
        info = warrant_map.get(code)
        if not info or _normalize_symbol(info.get("underlying_symbol")) != underlying:
            continue
        bucket = aggregate.setdefault(
            code,
            {
                "symbol": code,
                "name": info.get("warrant_name") or code,
                "cp": "put" if _is_put_warrant(info.get("cp"), info.get("warrant_name")) else "call",
                "last_price": 0.0,
                "volume": 0,
                "last_time": "",
                "tick_dir": "NONE",
            },
        )
        bucket["last_price"] = _safe_float(tick.get("price"))
        bucket["volume"] += _safe_int(tick.get("volume"))
        bucket["last_time"] = str(tick.get("ts") or "")
        bucket["tick_dir"] = str(tick.get("tick_dir") or "NONE")

    related = sorted(aggregate.values(), key=lambda item: int(item["volume"]), reverse=True)[:5]

    return {
        "symbol": target,
        "name": name,
        "underlying_symbol": underlying,
        "underlying_name": db_queries.get_stock_name(underlying),
        "order_book": _snapshot_order_book(target),
        "tape": tape,
        "related_warrants": related,
    }
