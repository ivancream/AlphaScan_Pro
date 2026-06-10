from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple


ACTIVE_SIDES = {"OUTER", "INNER"}


def normalize_symbol(raw: Any) -> str:
    return str(raw or "").strip().upper().replace(".TW", "").replace(".TWO", "")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        out = float(value)
        return out if out == out and out not in (float("inf"), float("-inf")) else default
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def price_tick_size(price: float) -> float:
    """TWSE/TPEX common stock tick-size table."""
    p = abs(float(price or 0))
    if p < 5:
        return 0.01
    if p < 10:
        return 0.01
    if p < 50:
        return 0.05
    if p < 100:
        return 0.1
    if p < 500:
        return 0.5
    if p < 1000:
        return 1.0
    return 5.0


def wall_side_for_signal(signal_side: str) -> str:
    return "ask" if signal_side == "sell" else "bid"


@dataclass(frozen=True)
class ScalpTriggerConfig:
    consecutive_window_sec: int = 5
    consecutive_min_count: int = 30
    consecutive_min_volume: int = 300
    reversal_min_lots: int = 20
    block_trade_lots: int = 50
    mega_trade_lots: int = 100
    vwap_deviation_pct: float = 2.0
    no_new_extreme_sec: float = 2.0
    wall_lots_absolute: int = 500
    wall_avg_volume_multiple: float = 2.0
    wall_avg_window_sec: int = 300
    wall_price_tolerance_ticks: int = 1
    spoof_min_lots: int = 200
    spoof_drop_pct: float = 0.65
    spoof_cooldown_sec: float = 5.0
    signal_cooldown_sec: float = 8.0
    tick_size: Optional[float] = None


@dataclass
class TapeRun:
    side: str = "NONE"
    count: int = 0
    volume: int = 0
    started_at: float = 0.0
    last_at: float = 0.0
    high: float = 0.0
    low: float = 0.0

    def reset(self, side: str, ts: float, price: float, volume: int) -> None:
        self.side = side
        self.count = 1
        self.volume = volume
        self.started_at = ts
        self.last_at = ts
        self.high = price
        self.low = price

    def append(self, ts: float, price: float, volume: int) -> None:
        self.count += 1
        self.volume += volume
        self.last_at = ts
        self.high = max(self.high, price)
        self.low = min(self.low or price, price)

    @property
    def duration_sec(self) -> float:
        if not self.started_at or not self.last_at:
            return 0.0
        return max(0.0, self.last_at - self.started_at)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "side": self.side,
            "count": self.count,
            "volume": self.volume,
            "duration_sec": round(self.duration_sec, 3),
            "high": self.high,
            "low": self.low,
        }


@dataclass
class SymbolMicroState:
    open_price: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    day_amount: float = 0.0
    day_volume: int = 0
    last_price: float = 0.0
    last_high_at: float = 0.0
    last_low_at: float = 0.0
    ticks: Deque[Tuple[float, float, int, str]] = field(default_factory=lambda: deque(maxlen=5000))
    current_run: TapeRun = field(default_factory=TapeRun)
    prev_run: Optional[Dict[str, Any]] = None
    order_book: Dict[str, Any] = field(default_factory=dict)
    last_book_by_price: Dict[str, Dict[float, float]] = field(
        default_factory=lambda: {"bid": {}, "ask": {}}
    )
    last_spoof_at: Dict[str, float] = field(default_factory=dict)

    @property
    def vwap(self) -> float:
        if self.day_volume <= 0:
            return 0.0
        return self.day_amount / self.day_volume


@dataclass(frozen=True)
class ScalpSignal:
    kind: str
    symbol: str
    side: str
    price: float
    volume: int
    label: str
    message: str
    severity: str = "high"
    related_symbol: Optional[str] = None
    warrant_symbol: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)

    def to_event_fragment(self) -> Dict[str, Any]:
        return {
            "event_type": self.kind,
            "event_label": self.label,
            "side": self.side,
            "severity": self.severity,
            "message": self.message,
            "related_symbol": self.related_symbol or self.symbol,
            "warrant_symbol": self.warrant_symbol,
            "scalp_context": self.context,
        }


class IntradayScalpEngine:
    """Stateful tick/order-book trigger engine for intraday scalp signals.

    The engine is intentionally data-source agnostic. Feed it normalized tick
    dictionaries from Shioaji TickSTKv1 and optional five-level order books.
    """

    def __init__(self, config: Optional[ScalpTriggerConfig] = None) -> None:
        self.config = config or ScalpTriggerConfig()
        self._states: Dict[str, SymbolMicroState] = defaultdict(SymbolMicroState)
        self._reference_levels: Dict[str, Dict[str, float]] = defaultdict(dict)
        self._last_signal_at: Dict[str, float] = {}

    def set_reference_levels(
        self,
        symbol: str,
        *,
        prev_high: Optional[float] = None,
        prev_low: Optional[float] = None,
        open_price: Optional[float] = None,
    ) -> None:
        code = normalize_symbol(symbol)
        if not code:
            return
        refs = self._reference_levels[code]
        for key, value in (
            ("prev_high", prev_high),
            ("prev_low", prev_low),
            ("open", open_price),
        ):
            val = safe_float(value)
            if val > 0:
                refs[key] = val

    def process_tick(
        self,
        tick: Dict[str, Any],
        *,
        order_book: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> List[ScalpSignal]:
        ts = float(now if now is not None else time.time())
        symbol = normalize_symbol(tick.get("symbol"))
        price = safe_float(tick.get("price"))
        volume = safe_int(tick.get("volume"))
        tick_dir = str(tick.get("tick_dir") or "NONE").upper()
        if not symbol or price <= 0 or volume <= 0:
            return []

        state = self._states[symbol]
        signals: List[ScalpSignal] = []
        if order_book:
            signals.extend(self.update_order_book(symbol, order_book, last_price=price, now=ts))

        self._update_price_state(state, price, volume, tick_dir, ts)
        if tick_dir in ACTIVE_SIDES:
            block = self._detect_block_trade(symbol, price, volume, tick_dir)
            if block and self._passes_cooldown(symbol, block.kind, ts, 1.0):
                signals.append(block)
            reversal = self._update_run_and_detect_reversal(symbol, state, price, volume, tick_dir, ts)
            if reversal and self._passes_cooldown(symbol, reversal.kind, ts, self.config.signal_cooldown_sec):
                signals.append(reversal)
        return signals

    def process_warrant_tick(
        self,
        tick: Dict[str, Any],
        *,
        underlying_symbol: str,
        is_put: bool,
        now: Optional[float] = None,
    ) -> List[ScalpSignal]:
        ts = float(now if now is not None else time.time())
        symbol = normalize_symbol(tick.get("symbol"))
        underlying = normalize_symbol(underlying_symbol)
        price = safe_float(tick.get("price"))
        volume = safe_int(tick.get("volume"))
        tick_dir = str(tick.get("tick_dir") or "NONE").upper()
        if not symbol or not underlying or price <= 0 or volume <= 0 or tick_dir not in ACTIVE_SIDES:
            return []

        state = self._states[f"W:{symbol}"]
        synthetic_tick = {**tick, "symbol": f"W:{symbol}"}
        _ = synthetic_tick
        self._update_price_state(state, price, volume, tick_dir, ts)
        reversal = self._update_run_and_detect_warrant_exhaustion(
            symbol=symbol,
            underlying=underlying,
            state=state,
            price=price,
            volume=volume,
            tick_dir=tick_dir,
            is_put=is_put,
            now=ts,
        )
        if reversal and self._passes_cooldown(symbol, reversal.kind, ts, self.config.signal_cooldown_sec):
            return [reversal]
        return []

    def update_order_book(
        self,
        symbol: str,
        order_book: Dict[str, Any],
        *,
        last_price: Optional[float] = None,
        now: Optional[float] = None,
    ) -> List[ScalpSignal]:
        ts = float(now if now is not None else time.time())
        code = normalize_symbol(symbol)
        if not code:
            return []

        state = self._states[code]
        state.order_book = order_book or {}
        signals: List[ScalpSignal] = []
        price = safe_float(last_price, state.last_price)

        current_by_side = {
            "bid": self._levels_by_price(order_book.get("bid") or []),
            "ask": self._levels_by_price(order_book.get("ask") or []),
        }
        for side in ("bid", "ask"):
            for level_price, prev_lots in state.last_book_by_price[side].items():
                curr_lots = current_by_side[side].get(level_price, 0.0)
                if prev_lots < self.config.spoof_min_lots:
                    continue
                drop_ratio = 1.0 - (curr_lots / prev_lots if prev_lots else 0.0)
                if drop_ratio < self.config.spoof_drop_pct:
                    continue
                if price and not self._is_price_near(price, level_price):
                    continue
                key = f"{side}:{level_price}"
                last = state.last_spoof_at.get(key, 0.0)
                if ts - last < self.config.spoof_cooldown_sec:
                    continue
                state.last_spoof_at[key] = ts
                signals.append(
                    ScalpSignal(
                        kind="order_book_spoof_pull",
                        symbol=code,
                        side="sell" if side == "bid" else "buy",
                        price=price or level_price,
                        volume=int(prev_lots - curr_lots),
                        label="五檔抽單",
                        message=(
                            f"{side.upper()} {level_price:g} 掛單由 {prev_lots:,.0f} "
                            f"降到 {curr_lots:,.0f} 張"
                        ),
                        severity="high",
                        context={
                            "book_side": side,
                            "level_price": level_price,
                            "prev_lots": prev_lots,
                            "curr_lots": curr_lots,
                            "drop_ratio": round(drop_ratio, 3),
                        },
                    )
                )
        state.last_book_by_price = current_by_side
        return signals

    def snapshot(self, symbol: str) -> Dict[str, Any]:
        code = normalize_symbol(symbol)
        state = self._states.get(code)
        if not state:
            return {"symbol": code}
        refs = self._reference_levels.get(code, {})
        return {
            "symbol": code,
            "open": state.open_price or refs.get("open", 0.0),
            "high": state.day_high,
            "low": state.day_low,
            "vwap": state.vwap,
            "last_price": state.last_price,
            "current_run": state.current_run.snapshot(),
            "prev_high": refs.get("prev_high"),
            "prev_low": refs.get("prev_low"),
            "order_book": state.order_book,
        }

    def _update_price_state(
        self,
        state: SymbolMicroState,
        price: float,
        volume: int,
        tick_dir: str,
        now: float,
    ) -> None:
        if state.open_price <= 0:
            state.open_price = price
        if state.day_high <= 0 or price > state.day_high:
            state.day_high = price
            state.last_high_at = now
        if state.day_low <= 0 or price < state.day_low:
            state.day_low = price
            state.last_low_at = now
        state.last_price = price
        state.day_amount += price * volume
        state.day_volume += volume
        state.ticks.append((now, price, volume, tick_dir))
        cutoff = now - max(1, self.config.wall_avg_window_sec)
        while state.ticks and state.ticks[0][0] < cutoff:
            state.ticks.popleft()

    def _update_run_and_detect_reversal(
        self,
        symbol: str,
        state: SymbolMicroState,
        price: float,
        volume: int,
        tick_dir: str,
        now: float,
    ) -> Optional[ScalpSignal]:
        run = state.current_run
        if run.side == tick_dir:
            run.append(now, price, volume)
            return None

        previous_side = run.side
        previous = run.snapshot() if previous_side in ACTIVE_SIDES else None
        run.reset(tick_dir, now, price, volume)
        if not previous:
            return None
        previous = self._windowed_previous_run(state, previous_side, now) or previous
        if previous["count"] < self.config.consecutive_min_count:
            return None
        if previous["volume"] < self.config.consecutive_min_volume:
            return None
        if volume < self.config.reversal_min_lots:
            return None

        if previous["side"] == "OUTER" and tick_dir == "INNER":
            return self._build_short_exhaustion(symbol, state, price, volume, previous, now)
        if previous["side"] == "INNER" and tick_dir == "OUTER":
            return self._build_long_exhaustion(symbol, state, price, volume, previous, now)
        return None

    def _update_run_and_detect_warrant_exhaustion(
        self,
        *,
        symbol: str,
        underlying: str,
        state: SymbolMicroState,
        price: float,
        volume: int,
        tick_dir: str,
        is_put: bool,
        now: float,
    ) -> Optional[ScalpSignal]:
        run = state.current_run
        if run.side == tick_dir:
            run.append(now, price, volume)
            return None

        previous_side = run.side
        previous = run.snapshot() if previous_side in ACTIVE_SIDES else None
        run.reset(tick_dir, now, price, volume)
        if not previous:
            return None
        previous = self._windowed_previous_run(state, previous_side, now) or previous
        if previous["count"] < max(3, self.config.consecutive_min_count // 3):
            return None
        if previous["volume"] < max(self.config.reversal_min_lots, self.config.consecutive_min_volume // 2):
            return None

        if previous["side"] == "OUTER":
            hedge_side = "buy" if not is_put else "sell"
        else:
            hedge_side = "sell" if not is_put else "buy"
        reverse_side = "sell" if hedge_side == "buy" else "buy"
        return ScalpSignal(
            kind="warrant_hedge_exhaustion",
            symbol=underlying,
            related_symbol=underlying,
            warrant_symbol=symbol,
            side=reverse_side,
            price=price,
            volume=volume,
            label="權證避險竭盡",
            message=(
                f"{symbol} 權證連次 {previous['count']} 筆/{previous['volume']} 張後反向，"
                f"現貨避險方向可能由 {hedge_side} 轉弱"
            ),
            context={"run": previous, "is_put": is_put, "trigger_tick_dir": tick_dir},
        )

    def _build_short_exhaustion(
        self,
        symbol: str,
        state: SymbolMicroState,
        price: float,
        volume: int,
        run: Dict[str, Any],
        now: float,
    ) -> Optional[ScalpSignal]:
        vwap = state.vwap
        dev = ((price - vwap) / vwap * 100.0) if vwap > 0 else 0.0
        no_new_high = (now - state.last_high_at) >= self.config.no_new_extreme_sec
        wall = self._near_wall(state, "ask", price)
        refs = self._reference_hits(symbol, price)
        if dev < self.config.vwap_deviation_pct:
            return None
        if not (no_new_high or wall or refs):
            return None
        stop = max(state.day_high, run.get("high") or price) + self._price_tick_size(price)
        return ScalpSignal(
            kind="scalp_short_exhaustion",
            symbol=symbol,
            side="sell",
            price=price,
            volume=volume,
            label="連外竭盡空",
            message=(
                f"連外 {run['count']} 筆/{run['volume']} 張後出現內盤 {volume} 張；"
                f"VWAP 乖離 {dev:+.2f}%，停損參考 {stop:g}"
            ),
            context={
                "run": run,
                "vwap": round(vwap, 4),
                "vwap_deviation_pct": round(dev, 3),
                "no_new_high": no_new_high,
                "wall": wall,
                "key_levels": refs,
                "stop_price": stop,
                "take_profit": vwap,
            },
        )

    def _build_long_exhaustion(
        self,
        symbol: str,
        state: SymbolMicroState,
        price: float,
        volume: int,
        run: Dict[str, Any],
        now: float,
    ) -> Optional[ScalpSignal]:
        vwap = state.vwap
        dev = ((price - vwap) / vwap * 100.0) if vwap > 0 else 0.0
        no_new_low = (now - state.last_low_at) >= self.config.no_new_extreme_sec
        wall = self._near_wall(state, "bid", price)
        refs = self._reference_hits(symbol, price)
        if dev > -self.config.vwap_deviation_pct:
            return None
        if not (no_new_low or wall or refs):
            return None
        stop = min(state.day_low or price, run.get("low") or price) - self._price_tick_size(price)
        return ScalpSignal(
            kind="scalp_long_exhaustion",
            symbol=symbol,
            side="buy",
            price=price,
            volume=volume,
            label="連內竭盡多",
            message=(
                f"連內 {run['count']} 筆/{run['volume']} 張後出現外盤 {volume} 張；"
                f"VWAP 乖離 {dev:+.2f}%，停損參考 {stop:g}"
            ),
            context={
                "run": run,
                "vwap": round(vwap, 4),
                "vwap_deviation_pct": round(dev, 3),
                "no_new_low": no_new_low,
                "wall": wall,
                "key_levels": refs,
                "stop_price": stop,
                "take_profit": vwap,
            },
        )

    def _detect_block_trade(
        self,
        symbol: str,
        price: float,
        volume: int,
        tick_dir: str,
    ) -> Optional[ScalpSignal]:
        if volume < self.config.block_trade_lots:
            return None
        side = "buy" if tick_dir == "OUTER" else "sell"
        mega = volume >= self.config.mega_trade_lots
        return ScalpSignal(
            kind="mega_block_trade" if mega else "block_trade",
            symbol=symbol,
            side=side,
            price=price,
            volume=volume,
            label="特大單" if mega else "大單",
            message=f"{'外盤' if side == 'buy' else '內盤'}單筆 {volume:,} 張",
            severity="high" if mega else "normal",
            context={"tick_dir": tick_dir, "threshold": self.config.block_trade_lots},
        )

    def _windowed_previous_run(
        self,
        state: SymbolMicroState,
        previous_side: str,
        now: float,
    ) -> Optional[Dict[str, Any]]:
        cutoff = now - max(1, self.config.consecutive_window_sec)
        rows: List[Tuple[float, float, int, str]] = []
        for row in reversed(state.ticks):
            ts, price, volume, side = row
            if side != previous_side:
                if rows:
                    break
                continue
            if ts < cutoff:
                break
            rows.append(row)
        if not rows:
            return None
        rows.reverse()
        prices = [item[1] for item in rows]
        return {
            "side": previous_side,
            "count": len(rows),
            "volume": sum(item[2] for item in rows),
            "duration_sec": round(max(0.0, rows[-1][0] - rows[0][0]), 3),
            "high": max(prices),
            "low": min(prices),
        }

    def _near_wall(self, state: SymbolMicroState, side: str, price: float) -> Optional[Dict[str, Any]]:
        levels = state.order_book.get(side) or []
        if not levels:
            return None
        avg_lots = self._avg_tick_volume(state)
        threshold = max(
            float(self.config.wall_lots_absolute),
            avg_lots * float(self.config.wall_avg_volume_multiple),
        )
        for raw in levels[:5]:
            level_price = safe_float(raw.get("price"))
            lots = safe_float(raw.get("volume"))
            if level_price <= 0 or lots < threshold:
                continue
            if self._is_price_near(price, level_price):
                return {
                    "side": side,
                    "price": level_price,
                    "volume": lots,
                    "threshold": round(threshold, 2),
                }
        return None

    def _reference_hits(self, symbol: str, price: float) -> List[Dict[str, Any]]:
        code = normalize_symbol(symbol)
        refs = self._reference_levels.get(code, {})
        state = self._states.get(code)
        if state:
            refs = {
                **refs,
                "open": refs.get("open") or state.open_price,
                "day_high": state.day_high,
                "day_low": state.day_low,
            }
        out: List[Dict[str, Any]] = []
        for key, level in refs.items():
            val = safe_float(level)
            if val > 0 and self._is_price_near(price, val):
                out.append({"name": key, "price": val})
        return out

    def _avg_tick_volume(self, state: SymbolMicroState) -> float:
        if not state.ticks:
            return 0.0
        return sum(item[2] for item in state.ticks) / max(1, len(state.ticks))

    def _is_price_near(self, price: float, level_price: float) -> bool:
        tolerance = self._price_tick_size(price) * max(0, self.config.wall_price_tolerance_ticks)
        return abs(price - level_price) <= tolerance + 1e-9

    def _price_tick_size(self, price: float) -> float:
        override = safe_float(self.config.tick_size)
        return override if override > 0 else price_tick_size(price)

    def _levels_by_price(self, levels: Iterable[Dict[str, Any]]) -> Dict[float, float]:
        out: Dict[float, float] = {}
        for raw in levels:
            price = safe_float(raw.get("price"))
            volume = safe_float(raw.get("volume"))
            if price > 0:
                out[price] = volume
        return out

    def _passes_cooldown(self, symbol: str, kind: str, now: float, cooldown_sec: float) -> bool:
        key = f"{symbol}:{kind}"
        last = self._last_signal_at.get(key, 0.0)
        if now - last < cooldown_sec:
            return False
        self._last_signal_at[key] = now
        return True


def make_signal_id(now: Optional[float] = None) -> str:
    ts = float(now if now is not None else time.time())
    return f"{int(ts * 1000)}-{uuid.uuid4().hex[:6]}"
