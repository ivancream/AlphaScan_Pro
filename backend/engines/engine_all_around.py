"""
全方位報價引擎 (AllAroundEngine)

類似「權證小哥全方位監控」：
- 每一筆撮合 Tick（股票/ETF/權證/期貨）即時推送給所有連線的 WebSocket 客戶端
- 來源：Shioaji TickSTKv1 + TickFOPv1
- 判斷外/內盤 (BUY_UP / SELL_DOWN / NEUTRAL)
- 純記憶體操作，零資料庫寫入
"""
from __future__ import annotations

import asyncio
import datetime as dt
from collections import deque
from enum import Enum
from typing import Dict, List, Optional, Set

from pydantic import BaseModel

from backend.settings import get_sinopac_env, sinopac_credentials_configured


# ──────────────────────────────────────────────────────────────────────────────
# 統一資料模型 (Pydantic)
# ──────────────────────────────────────────────────────────────────────────────

class AssetType(str, Enum):
    STOCK   = "STOCK"
    FUTURES = "FUTURES"
    WARRANT = "WARRANT"


class TickType(str, Enum):
    BUY_UP    = "BUY_UP"     # 外盤，主動買方成交，紅色
    SELL_DOWN = "SELL_DOWN"  # 內盤，主動賣方成交，綠色
    NEUTRAL   = "NEUTRAL"    # 無法判斷方向


class UnifiedTick(BaseModel):
    ts:         str        # UTC ISO-8601
    symbol:     str        # 股票代號或期貨代碼
    name:       str        # 中文名稱
    asset_type: AssetType
    price:      float      # 成交價
    volume:     int        # 單筆成交量（張 / 口）
    tick_type:  TickType


# Shioaji tick_type 整數 → 本系統 TickType
_SJ_TICK_TYPE: Dict[int, TickType] = {
    0: TickType.NEUTRAL,
    1: TickType.BUY_UP,
    2: TickType.SELL_DOWN,
}

# 預設期貨代碼（前綴，自動取近月合約）
_DEFAULT_FUTURES_PREFIX = ["TXF", "MXF"]


def _detect_asset_type(code: str) -> AssetType:
    """
    台灣市場代碼判斷:
    - 6 位純數字 → 權證（如 073XXX）
    - 4~5 位純數字 → 股票 / ETF
    - 含英文 → 期貨/選擇權
    """
    if code.isdigit():
        return AssetType.WARRANT if len(code) >= 6 else AssetType.STOCK
    return AssetType.FUTURES


def _utc_now() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


# ──────────────────────────────────────────────────────────────────────────────
# 全方位引擎
# ──────────────────────────────────────────────────────────────────────────────

class AllAroundEngine:
    """
    全方位即時 Tick 引擎。

    架構：
    - Shioaji callback（非同步執行緒）→ run_coroutine_threadsafe
      → asyncio 主迴圈 _handle_xxx → _broadcast → 各連線 queue
    - subscribe() 給每個 WebSocket 連線一個獨立 asyncio.Queue（max 2000）
    """

    def __init__(self) -> None:
        self._subscribers:    Set[asyncio.Queue] = set()
        self._loop:           Optional[asyncio.AbstractEventLoop] = None
        self._api             = None
        self._running         = False
        self._shioaji_active  = False
        self._subscribed_stk: Set[str] = set()
        self._subscribed_fop: Set[str] = set()
        self._name_map:       Dict[str, str] = {}
        self._tick_count      = 0
        self._last_tick_ts:   Optional[str] = None
        self._last_error:     Optional[str] = None
        # 保留最近一段 tick，供新開頁面 / 盤後回放使用
        self._recent_ticks:   deque[dict] = deque(maxlen=5000)

    # ── 生命週期 ──────────────────────────────────────────────────────────────

    async def start(
        self,
        stk_symbols:     List[str] | None = None,
        futures_prefixes: List[str] | None = None,
    ) -> None:
        if self._running:
            return
        self._running = True
        self._loop = asyncio.get_event_loop()

        if not sinopac_credentials_configured():
            self._last_error = "永豐金 API Key 未設定，全方位監控未啟動"
            print(f"[AllAround] {self._last_error}")
            return

        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._connect_shioaji(
                    stk_symbols=stk_symbols or [],
                    futures_prefixes=futures_prefixes or _DEFAULT_FUTURES_PREFIX,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            self._shioaji_active = False
            print(f"[AllAround] 連線失敗: {exc}")

    async def stop(self) -> None:
        self._running = False
        if self._api is not None:
            try:
                self._api.logout()
            except Exception:  # noqa: BLE001
                pass
            self._api = None
        print("[AllAround] 已停止")

    # ── Shioaji 連線（在 executor 執行，避免阻塞 asyncio loop）───────────────

    def _connect_shioaji(
        self,
        stk_symbols:     List[str],
        futures_prefixes: List[str],
    ) -> None:
        import shioaji as sj
        import shioaji.constant as sjc

        creds = get_sinopac_env()
        api = sj.Shioaji(simulation=creds["simulation"])
        api.login(
            api_key=creds["api_key"],
            secret_key=creds["secret_key"],
            fetch_contract=True,
        )
        self._api = api
        loop = self._loop

        # ── 股票 / ETF / 權證 Tick 回調 ──────────────────────────────────────
        @api.on_tick_stk_v1()
        def _on_stk(exchange, tick):
            asyncio.run_coroutine_threadsafe(
                self._handle_stk_tick(tick), loop
            )

        # ── 期貨 / 選擇權 Tick 回調 ───────────────────────────────────────────
        @api.on_tick_fop_v1()
        def _on_fop(exchange, tick):
            asyncio.run_coroutine_threadsafe(
                self._handle_fop_tick(tick), loop
            )

        # ── 訂閱股票 ──────────────────────────────────────────────────────────
        for symbol in stk_symbols:
            self._subscribe_stk(symbol, api, sjc)

        # ── 訂閱期貨（依前綴取近月合約）──────────────────────────────────────
        for prefix in futures_prefixes:
            self._subscribe_fop_by_prefix(prefix, api, sjc)

        self._shioaji_active = True
        print(
            f"[AllAround] 啟動完成 | "
            f"STK={len(self._subscribed_stk)} | "
            f"FOP={len(self._subscribed_fop)}"
        )

    def _subscribe_stk(self, symbol: str, api, sjc) -> None:
        if symbol in self._subscribed_stk:
            return
        try:
            contract = api.Contracts.Stocks.get(symbol)
            if contract is None:
                return
            api.quote.subscribe(
                contract,
                quote_type=sjc.QuoteType.Tick,
                version=sjc.QuoteVersion.v1,
            )
            self._subscribed_stk.add(symbol)
            self._name_map[symbol] = getattr(contract, "name", symbol)
        except Exception as exc:  # noqa: BLE001
            print(f"[AllAround] STK 訂閱 {symbol} 失敗: {exc}")

    def _subscribe_fop_by_prefix(self, prefix: str, api, sjc) -> None:
        """取期貨近月合約（到期日最近者）並訂閱。"""
        try:
            ns = getattr(api.Contracts.Futures, prefix, None)
            if ns is None:
                print(f"[AllAround] 找不到期貨命名空間: {prefix}")
                return
            contracts = sorted(
                [c for c in ns],
                key=lambda c: getattr(c, "delivery_date", "9999"),
            )
            if not contracts:
                return
            contract = contracts[0]  # 近月
            code = contract.code
            if code in self._subscribed_fop:
                return
            api.quote.subscribe(
                contract,
                quote_type=sjc.QuoteType.Tick,
                version=sjc.QuoteVersion.v1,
            )
            self._subscribed_fop.add(code)
            self._name_map[code] = getattr(contract, "name", prefix)
            print(f"[AllAround] FOP 訂閱近月合約: {code}")
        except Exception as exc:  # noqa: BLE001
            print(f"[AllAround] FOP 訂閱 {prefix} 失敗: {exc}")

    def add_stk_symbols(self, symbols: List[str]) -> None:
        """執行期間動態追加股票訂閱。"""
        if self._api is None:
            return
        try:
            import shioaji.constant as sjc
            for symbol in symbols:
                self._subscribe_stk(symbol, self._api, sjc)
        except Exception as exc:  # noqa: BLE001
            print(f"[AllAround] 動態訂閱失敗: {exc}")

    # ── Tick 處理（asyncio 主執行緒）─────────────────────────────────────────

    async def _handle_stk_tick(self, tick) -> None:
        try:
            code  = str(tick.code)
            price = float(tick.close) if tick.close else 0.0
            if price == 0.0:
                return
            volume    = int(tick.volume or 0)
            tick_type = _SJ_TICK_TYPE.get(int(tick.tick_type or 0), TickType.NEUTRAL)

            await self._broadcast(UnifiedTick(
                ts=_utc_now(),
                symbol=code,
                name=self._name_map.get(code, code),
                asset_type=_detect_asset_type(code),
                price=price,
                volume=volume,
                tick_type=tick_type,
            ))
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)

    async def _handle_fop_tick(self, tick) -> None:
        try:
            code  = str(tick.code)
            price = float(tick.close) if tick.close else 0.0
            if price == 0.0:
                return
            volume    = int(tick.volume or 0)
            tick_type = _SJ_TICK_TYPE.get(int(tick.tick_type or 0), TickType.NEUTRAL)

            await self._broadcast(UnifiedTick(
                ts=_utc_now(),
                symbol=code,
                name=self._name_map.get(code, code),
                asset_type=AssetType.FUTURES,
                price=price,
                volume=volume,
                tick_type=tick_type,
            ))
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)

    # ── 廣播（fan-out 給所有訂閱者 queue）────────────────────────────────────

    async def _broadcast(self, tick: UnifiedTick) -> None:
        self._tick_count += 1
        self._last_tick_ts = tick.ts
        payload = tick.model_dump()
        self._recent_ticks.append(payload)

        stale: List[asyncio.Queue] = []
        for queue in self._subscribers:
            try:
                if queue.full():
                    queue.get_nowait()  # 丟掉最舊的，不阻塞
                queue.put_nowait(payload)
            except Exception:  # noqa: BLE001
                stale.append(queue)
        for q in stale:
            self._subscribers.discard(q)

    # ── 訂閱者管理 ────────────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        """每個 WebSocket 連線呼叫一次，取得獨立 queue。"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def get_recent_ticks(
        self,
        *,
        stock_symbols: Set[str] | None = None,
        include_futures: bool = False,
        limit: int = 120,
    ) -> List[dict]:
        """
        取最近 tick 歷史，供 WebSocket 初始回放。
        - stock_symbols: 指定股票代號集合
        - include_futures: 是否連同期貨 ticks 一起回放
        - limit: 最多回傳幾筆（按時間由舊到新）
        """
        if limit <= 0:
            return []

        matched: List[dict] = []
        stock_symbols = stock_symbols or set()

        # 由新到舊掃描，再翻轉回舊到新，前端 prepend 才會得到 newest-first
        for tick in reversed(self._recent_ticks):
            if stock_symbols and tick.get("symbol") in stock_symbols:
                matched.append(tick)
            elif include_futures and tick.get("asset_type") == "FUTURES":
                matched.append(tick)
            elif not stock_symbols and not include_futures:
                matched.append(tick)

            if len(matched) >= limit:
                break

        matched.reverse()
        return matched

    # ── 健康狀態 ──────────────────────────────────────────────────────────────

    def get_health(self) -> dict:
        return {
            "running":          self._running,
            "shioaji_active":   self._shioaji_active,
            "subscribed_stk":   len(self._subscribed_stk),
            "subscribed_fop":   len(self._subscribed_fop),
            "ws_subscribers":   len(self._subscribers),
            "tick_count":       self._tick_count,
            "recent_tick_buffer": len(self._recent_ticks),
            "last_tick_ts":     self._last_tick_ts,
            "last_error":       self._last_error,
        }


all_around_engine = AllAroundEngine()
