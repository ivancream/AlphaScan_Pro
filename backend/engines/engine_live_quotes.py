"""
即時報價引擎 (LiveQuoteEngine)

行情來源優先順序:
  1. 永豐金 Shioaji WebSocket — tick 回調，真正即時 (盤中 ~100ms 級)
  2. yfinance 輪詢           — Shioaji 未設定或登入失敗時自動降級 (8 秒輪詢)

架構重點:
- QuoteSnapshot: 每檔股票的最新快照 (in-memory)
- _subscribers: 一組 asyncio.Queue，每條 WebSocket 連線各持一個
- Shioaji 的 tick callback 在 tornado/sinopac thread 呼叫，用
  run_coroutine_threadsafe 跨執行緒投遞到 asyncio event loop
"""
from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import asdict, dataclass
from typing import Dict, List, Literal

import yfinance as yf

from backend.engines.engine_symbol_pool import get_symbol_pool, get_symbol_profile
from backend.settings import get_sinopac_env, sinopac_credentials_configured

Provider = Literal["shioaji", "yfinance"]


@dataclass
class QuoteSnapshot:
    stock_id: str
    ticker: str
    name: str
    last_price: float
    change_pct: float
    volume: int
    provider: Provider
    ts: str


# ──────────────────────────────────────────────────────────────────────────────
# Shioaji 介面層
# ──────────────────────────────────────────────────────────────────────────────

class ShioajiAdapter:
    """
    封裝永豐 Shioaji 的行情訂閱。

    【架構改動】
    不再自行 login；改用 sinopac_session（全域共享連線）取得 api 物件，
    並透過 sinopac_session.add_stk_handler() 注冊 Tick 分發器，
    避免多引擎各自 login 互踢的問題。
    """

    def __init__(self) -> None:
        self._api = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_quote_callback = None
        self._subscribed: set[str] = set()
        self._stock_to_ref: Dict[str, float] = {}

    def connect(
        self,
        loop: asyncio.AbstractEventLoop,
        on_quote_callback,
    ) -> bool:
        """
        取得共享 Shioaji Session 並注冊 Tick 處理器。
        - loop: asyncio 主迴圈，tick callback 需要跨執行緒投遞
        - on_quote_callback: async def(stock_id, price, volume, ts) 協程
        """
        from backend.engines.sinopac_session import sinopac_session

        api = sinopac_session.api
        if api is None:
            print("[ShioajiAdapter] 共享 Session 未連線，LiveQuotes 降級至 yfinance")
            return False

        self._api = api
        self._loop = loop
        self._on_quote_callback = on_quote_callback

        # 注冊 Tick 處理器到共享分發器（不覆蓋其他引擎的 callback）
        sinopac_session.add_stk_handler(self._handle_tick_sync)
        print("[ShioajiAdapter] 已注冊 STK Tick 處理器（共享 Session）")
        return True

    def _handle_tick_sync(self, exchange, tick) -> None:
        """同步 Tick 處理器（在 Shioaji 執行緒中被呼叫）。"""
        if self._loop is None or self._on_quote_callback is None:
            return
        try:
            ts = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
            price = float(tick.close) if tick.close else 0.0
            # tick.total_volume: 當日累積成交量（張）；用於顯示今日總量
            volume = int(tick.total_volume) if tick.total_volume else 0
            stock_id = str(tick.code)
            asyncio.run_coroutine_threadsafe(
                self._on_quote_callback(
                    stock_id=stock_id, price=price, volume=volume, ts=ts
                ),
                self._loop,
            )
        except Exception:  # noqa: BLE001
            pass

    def subscribe_pool(self, symbol_pool: List[dict]) -> None:
        """訂閱 symbol_pool 中尚未訂閱的標的。"""
        if self._api is None:
            return

        import shioaji as sj
        import shioaji.constant as sjc

        for item in symbol_pool:
            stock_id = item["stock_id"]
            if stock_id in self._subscribed:
                continue
            try:
                contract = self._api.Contracts.Stocks.get(stock_id)
                if contract is None:
                    continue
                self._api.quote.subscribe(
                    contract,
                    quote_type=sjc.QuoteType.Tick,
                    version=sjc.QuoteVersion.v1,
                )
                self._subscribed.add(stock_id)
                ref_close = item.get("reference_close")
                if ref_close:
                    self._stock_to_ref[stock_id] = float(ref_close)
            except Exception as exc:  # noqa: BLE001
                print(f"[Shioaji] 訂閱 {stock_id} 失敗: {exc}")

    def get_ref_close(self, stock_id: str) -> float | None:
        return self._stock_to_ref.get(stock_id)

    def disconnect(self) -> None:
        if self._api is not None:
            try:
                self._api.logout()
            except Exception:  # noqa: BLE001
                pass
            self._api = None
            print("[Shioaji] 已登出")


# ──────────────────────────────────────────────────────────────────────────────
# 行情主引擎
# ──────────────────────────────────────────────────────────────────────────────

class LiveQuoteEngine:
    """
    行情引擎入口。
    - start() 時嘗試 Shioaji 登入；成功則以 Shioaji push 為主
    - 失敗或盤後時段，退回 yfinance 8 秒輪詢
    - 訂閱者透過 subscribe() 拿到各自的 asyncio.Queue
    """

    def __init__(self, top_n: int = 50, poll_interval_sec: int = 8) -> None:
        self.top_n = top_n
        self.poll_interval_sec = poll_interval_sec

        self._symbol_pool: List[dict] = []
        self._latest: Dict[str, QuoteSnapshot] = {}
        self._event_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=5000)
        self._subscribers: set[asyncio.Queue] = set()

        self._running = False
        self._loop_task: asyncio.Task | None = None
        self._connected_provider: Provider = "yfinance"

        self._last_error: str | None = None
        self._last_event_ts: str | None = None
        self._reload_pool_interval = 60          # 秒：每 60s 重載 symbol pool
        self._ticks_since_reload = 0

        self._shioaji = ShioajiAdapter()
        self._shioaji_active = False             # Shioaji 連線是否成功

    # ── 生命週期 ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._refresh_symbol_pool()

        loop = asyncio.get_event_loop()
        if sinopac_credentials_configured():
            # connect() 不再阻塞（僅從共享 Session 取 api 物件並注冊 handler）
            self._shioaji_active = self._shioaji.connect(
                loop=loop,
                on_quote_callback=self._on_shioaji_tick,
            )
            if self._shioaji_active:
                self._connected_provider = "shioaji"
                self._shioaji.subscribe_pool(self._symbol_pool)

        self._loop_task = asyncio.create_task(self._run(), name="live-quote-engine")

    async def stop(self) -> None:
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        self._shioaji.disconnect()

    # ── 主迴圈 ────────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        while self._running:
            try:
                if not self._shioaji_active:
                    # 沒有 Shioaji → 主動 yfinance 輪詢
                    await self._poll_yfinance()
                else:
                    # 有 Shioaji → 只需重載 symbol pool 並補訂新標的
                    self._maybe_refresh_symbol_pool()
                    self._shioaji.subscribe_pool(self._symbol_pool)

                self._last_error = None
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                await self._broadcast_event({
                    "type": "error",
                    "code": "LIVE_FEED_ERROR",
                    "message": self._last_error,
                    "ts": self._now_iso(),
                })

            await self._broadcast_event({
                "type": "heartbeat",
                "ts": self._now_iso(),
                "provider": self._connected_provider,
                "symbol_count": len(self._symbol_pool),
            })
            await asyncio.sleep(self.poll_interval_sec)

    # ── Shioaji Tick 回調（跨執行緒，run_coroutine_threadsafe 投遞） ───────────

    async def _on_shioaji_tick(
        self, *, stock_id: str, price: float, volume: int, ts: str
    ) -> None:
        profile = next(
            (p for p in self._symbol_pool if p["stock_id"] == stock_id), None
        )
        if profile is None:
            return

        ref_close = self._shioaji.get_ref_close(stock_id) or profile.get("reference_close")
        change_pct = 0.0
        if ref_close and ref_close != 0:
            change_pct = round(((price - ref_close) / ref_close) * 100.0, 2)

        quote = QuoteSnapshot(
            stock_id=stock_id,
            ticker=profile["ticker"],
            name=profile["name"],
            last_price=round(price, 2),
            change_pct=change_pct,
            volume=volume,
            provider="shioaji",
            ts=ts,
        )

        previous = self._latest.get(stock_id)
        self._latest[stock_id] = quote
        if previous is None or (
            previous.last_price != quote.last_price or previous.volume != quote.volume
        ):
            await self._broadcast_event({
                "type": "quote",
                "payload": asdict(quote),
            })
            self._last_event_ts = ts

    # ── yfinance 輪詢（降級路徑）──────────────────────────────────────────────

    async def _poll_yfinance(self) -> None:
        self._maybe_refresh_symbol_pool()
        if not self._symbol_pool:
            await self._broadcast_event({
                "type": "empty",
                "message": "symbol pool is empty",
                "ts": self._now_iso(),
            })
            return

        symbols = [item["ticker"] for item in self._symbol_pool]
        ticker_to_profile = {item["ticker"]: item for item in self._symbol_pool}

        batch = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: yf.download(
                " ".join(symbols),
                period="1d",
                interval="1m",
                progress=False,
                group_by="ticker",
                threads=True,
            ),
        )

        if batch is None or batch.empty:
            return

        events = []
        many = len(symbols) > 1
        for ticker in symbols:
            profile = ticker_to_profile[ticker]
            close = self._extract_close(batch, ticker=ticker, many=many)
            volume = self._extract_volume(batch, ticker=ticker, many=many)
            if close is None:
                continue

            ref_close = profile.get("reference_close")
            change_pct = 0.0
            if ref_close and ref_close != 0:
                change_pct = round(((close - ref_close) / ref_close) * 100.0, 2)

            quote = QuoteSnapshot(
                stock_id=profile["stock_id"],
                ticker=ticker,
                name=profile["name"],
                last_price=round(float(close), 2),
                change_pct=change_pct,
                volume=int(volume or 0),
                provider="yfinance",
                ts=self._now_iso(),
            )

            previous = self._latest.get(quote.stock_id)
            self._latest[quote.stock_id] = quote
            if previous is None or (
                previous.last_price != quote.last_price
                or previous.volume != quote.volume
            ):
                events.append(quote)

        for quote in events:
            await self._broadcast_event({"type": "quote", "payload": asdict(quote)})
            self._last_event_ts = quote.ts

    # ── Symbol Pool ───────────────────────────────────────────────────────────

    def _refresh_symbol_pool(self) -> None:
        self._symbol_pool = get_symbol_pool(top_n=self.top_n)
        self._ticks_since_reload = 0

    def _maybe_refresh_symbol_pool(self) -> None:
        self._ticks_since_reload += self.poll_interval_sec
        if self._ticks_since_reload >= self._reload_pool_interval:
            self._refresh_symbol_pool()

    def ensure_symbol(self, stock_id: str) -> bool:
        """
        確保指定 stock_id 已在 symbol pool 中。
        個股頁開啟時會呼叫，避免非熱門股永遠收不到即時報價。
        """
        sid = str(stock_id).strip()
        if not sid:
            return False

        exists = next((item for item in self._symbol_pool if item["stock_id"] == sid), None)
        if exists is not None:
            return True

        profile = get_symbol_profile(sid)
        if profile is None:
            return False

        self._symbol_pool.append(profile)

        # 若 Shioaji 已連線，立即補訂新標的；yfinance 模式則下輪輪詢自動涵蓋
        if self._shioaji_active:
            self._shioaji.subscribe_pool(self._symbol_pool)
        return True

    # ── 廣播 ──────────────────────────────────────────────────────────────────

    async def _broadcast_event(self, event: dict) -> None:
        if self._event_queue.full():
            self._event_queue.get_nowait()
        self._event_queue.put_nowait(event)

        stale = []
        for queue in self._subscribers:
            try:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(event)
            except Exception:  # noqa: BLE001
                stale.append(queue)
        for queue in stale:
            self._subscribers.discard(queue)

    # ── 對外 API ──────────────────────────────────────────────────────────────

    def get_latest_quotes(self) -> List[dict]:
        return [asdict(item) for item in self._latest.values()]

    def get_health(self) -> dict:
        return {
            "running": self._running,
            "provider": self._connected_provider,
            "shioaji_active": self._shioaji_active,
            "symbol_count": len(self._symbol_pool),
            "subscribed_via_shioaji": len(self._shioaji._subscribed),
            "latest_quote_count": len(self._latest),
            "last_event_ts": self._last_event_ts,
            "last_error": self._last_error,
            "sinopac_env_configured": sinopac_credentials_configured(),
        }

    async def next_event(self) -> dict:
        return await self._event_queue.get()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    # ── 工具 ──────────────────────────────────────────────────────────────────

    def _now_iso(self) -> str:
        return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    def _extract_close(self, frame, ticker: str, many: bool) -> float | None:
        try:
            series = frame[ticker]["Close"].dropna() if many else frame["Close"].dropna()
            return float(series.iloc[-1]) if not series.empty else None
        except Exception:  # noqa: BLE001
            return None

    def _extract_volume(self, frame, ticker: str, many: bool) -> int | None:
        try:
            series = frame[ticker]["Volume"].dropna() if many else frame["Volume"].dropna()
            return int(series.iloc[-1]) if not series.empty else None
        except Exception:  # noqa: BLE001
            return None


live_quote_engine = LiveQuoteEngine()
