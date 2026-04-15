"""
全方位報價引擎 (AllAroundEngine)

串接 Shioaji v1 Tick API：
  - @api.on_tick_stk_v1()  → 現股 / ETF / 權證（認購 & 認售）
  - @api.on_tick_fop_v1()  → 期貨 / 選擇權

欄位來源（TickSTKv1 / TickFOPv1）：
  code        商品代碼
  datetime    時間戳
  close       成交價
  volume      單筆量（張/口）
  tick_type   1=外盤  2=內盤  0=無法判定
  chg_type    1=漲停  2=漲  3=平盤  4=跌  5=跌停
  pct_chg     漲跌幅%

權證辨識：代碼 6 碼數字；認購/認售依 contract.option_right 或 name 包含「售」判斷。
"""
from __future__ import annotations

import asyncio
import datetime as dt
from enum import Enum
from typing import Dict, List, Optional, Set

from pydantic import BaseModel

from backend.settings import get_sinopac_env, sinopac_credentials_configured


# ──────────────────────────────────────────────────────────────────────────────
# 統一資料模型
# ──────────────────────────────────────────────────────────────────────────────

class AssetType(str, Enum):
    STOCK        = "現貨"
    FUTURES      = "期貨"
    CALL_WARRANT = "認購"
    PUT_WARRANT  = "認售"


class TickDirection(str, Enum):
    """外內盤：對應 Shioaji tick_type {1:外盤, 2:內盤, 0:無法判定}"""
    OUTER = "OUTER"   # 外盤（主動買）→ 紅
    INNER = "INNER"   # 內盤（主動賣）→ 綠
    NONE  = "NONE"


class ChgType(str, Enum):
    """漲跌註記：對應 Shioaji chg_type {1:漲停, 2:漲, 3:平盤, 4:跌, 5:跌停}"""
    LIMIT_UP   = "LIMIT_UP"
    UP         = "UP"
    FLAT       = "FLAT"
    DOWN       = "DOWN"
    LIMIT_DOWN = "LIMIT_DOWN"


class UnifiedTick(BaseModel):
    ts:         str          # HH:MM:SS（台灣時間，盤面顯示用）
    symbol:     str          # 商品代碼
    name:       str          # 中文名稱
    asset_type: AssetType    # 現貨 / 期貨 / 認購 / 認售
    price:      float        # 成交價
    volume:     int          # 單筆量（張 or 口）
    tick_dir:   TickDirection  # 外盤 / 內盤
    chg_type:   ChgType        # 漲跌註記（決定價格顏色）
    pct_chg:    float          # 漲跌幅 %


# ── 映射表 ────────────────────────────────────────────────────────────────────

_SJ_TICK_DIR: Dict[int, TickDirection] = {
    0: TickDirection.NONE,
    1: TickDirection.OUTER,
    2: TickDirection.INNER,
}

_SJ_CHG_TYPE: Dict[int, ChgType] = {
    1: ChgType.LIMIT_UP,
    2: ChgType.UP,
    3: ChgType.FLAT,
    4: ChgType.DOWN,
    5: ChgType.LIMIT_DOWN,
}

_DEFAULT_FUTURES_PREFIX = ["TXF", "MXF"]


# ──────────────────────────────────────────────────────────────────────────────
# 引擎
# ──────────────────────────────────────────────────────────────────────────────

class AllAroundEngine:

    HISTORY_SIZE = 500

    def __init__(self) -> None:
        self._subscribers:    Set[asyncio.Queue] = set()
        self._loop:           Optional[asyncio.AbstractEventLoop] = None
        self._api             = None
        self._running         = False
        self._shioaji_active  = False
        self._subscribed_stk: Set[str] = set()
        self._subscribed_fop: Set[str] = set()
        self._name_map:       Dict[str, str] = {}
        self._asset_map:      Dict[str, AssetType] = {}
        self._tick_count      = 0
        self._last_tick_ts:   Optional[str] = None
        self._last_error:     Optional[str] = None
        self._recent_ticks:   List[dict] = []

    # ── 生命週期 ──────────────────────────────────────────────────────────────

    async def start(
        self,
        stk_symbols:      List[str] | None = None,
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

    # ── Shioaji 連線 ─────────────────────────────────────────────────────────

    def _connect_shioaji(
        self,
        stk_symbols:      List[str],
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

        # ── 股票 / ETF / 權證 Tick v1 回調 ───────────────────────────────────
        @api.on_tick_stk_v1()
        def _on_stk(exchange, tick):
            asyncio.run_coroutine_threadsafe(self._handle_stk_tick(tick), loop)

        # ── 期貨 / 選擇權 Tick v1 回調 ───────────────────────────────────────
        @api.on_tick_fop_v1()
        def _on_fop(exchange, tick):
            asyncio.run_coroutine_threadsafe(self._handle_fop_tick(tick), loop)

        # 訂閱股票
        for symbol in stk_symbols:
            self._subscribe_stk(symbol, api, sjc)

        # 訂閱期貨（近月）
        for prefix in futures_prefixes:
            self._subscribe_fop_by_prefix(prefix, api, sjc)

        self._shioaji_active = True
        print(
            f"[AllAround] 啟動完成 | "
            f"STK={len(self._subscribed_stk)} FOP={len(self._subscribed_fop)}"
        )

    # ── 訂閱邏輯 ─────────────────────────────────────────────────────────────

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

            name = getattr(contract, "name", symbol)
            self._name_map[symbol] = name

            # 判斷認購 / 認售 / 現貨
            if len(symbol) >= 6 and symbol.isdigit():
                option_right = getattr(contract, "option_right", None)
                if option_right and "Put" in str(option_right):
                    self._asset_map[symbol] = AssetType.PUT_WARRANT
                elif "售" in name:
                    self._asset_map[symbol] = AssetType.PUT_WARRANT
                else:
                    self._asset_map[symbol] = AssetType.CALL_WARRANT
            else:
                self._asset_map[symbol] = AssetType.STOCK
        except Exception as exc:  # noqa: BLE001
            print(f"[AllAround] STK 訂閱 {symbol} 失敗: {exc}")

    def _subscribe_fop_by_prefix(self, prefix: str, api, sjc) -> None:
        try:
            ns = getattr(api.Contracts.Futures, prefix, None)
            if ns is None:
                return
            contracts = sorted(
                [c for c in ns],
                key=lambda c: getattr(c, "delivery_date", "9999"),
            )
            if not contracts:
                return
            contract = contracts[0]
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
            self._asset_map[code] = AssetType.FUTURES
            print(f"[AllAround] FOP 訂閱: {code}")
        except Exception as exc:  # noqa: BLE001
            print(f"[AllAround] FOP {prefix} 失敗: {exc}")

    def add_stk_symbols(self, symbols: List[str]) -> None:
        if self._api is None:
            return
        try:
            import shioaji.constant as sjc
            for symbol in symbols:
                self._subscribe_stk(symbol, self._api, sjc)
        except Exception as exc:  # noqa: BLE001
            print(f"[AllAround] 動態訂閱失敗: {exc}")

    # ── Tick 處理（TickSTKv1）────────────────────────────────────────────────

    async def _handle_stk_tick(self, tick) -> None:
        try:
            code  = str(tick.code)
            price = float(tick.close) if tick.close else 0.0
            if price == 0.0:
                return

            ts_str = self._format_time(tick.datetime)
            await self._broadcast(UnifiedTick(
                ts=ts_str,
                symbol=code,
                name=self._name_map.get(code, code),
                asset_type=self._asset_map.get(code, AssetType.STOCK),
                price=price,
                volume=int(tick.volume or 0),
                tick_dir=_SJ_TICK_DIR.get(int(tick.tick_type or 0), TickDirection.NONE),
                chg_type=_SJ_CHG_TYPE.get(int(tick.chg_type or 3), ChgType.FLAT),
                pct_chg=float(tick.pct_chg or 0),
            ))
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)

    # ── Tick 處理（TickFOPv1）────────────────────────────────────────────────

    async def _handle_fop_tick(self, tick) -> None:
        try:
            code  = str(tick.code)
            price = float(tick.close) if tick.close else 0.0
            if price == 0.0:
                return

            ts_str = self._format_time(tick.datetime)
            chg_int = int(getattr(tick, "chg_type", 3) or 3)
            pct = float(getattr(tick, "pct_chg", 0) or 0)

            await self._broadcast(UnifiedTick(
                ts=ts_str,
                symbol=code,
                name=self._name_map.get(code, code),
                asset_type=AssetType.FUTURES,
                price=price,
                volume=int(tick.volume or 0),
                tick_dir=_SJ_TICK_DIR.get(int(tick.tick_type or 0), TickDirection.NONE),
                chg_type=_SJ_CHG_TYPE.get(chg_int, ChgType.FLAT),
                pct_chg=pct,
            ))
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)

    # ── 工具 ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_time(dt_val) -> str:
        """將 Shioaji datetime 轉為台灣盤面時間字串 HH:MM:SS"""
        if dt_val is None:
            return dt.datetime.now().strftime("%H:%M:%S")
        if isinstance(dt_val, dt.datetime):
            return dt_val.strftime("%H:%M:%S")
        return str(dt_val)[:8]

    # ── 廣播 ──────────────────────────────────────────────────────────────────

    async def _broadcast(self, tick: UnifiedTick) -> None:
        self._tick_count += 1
        self._last_tick_ts = tick.ts
        payload = tick.model_dump()

        self._recent_ticks.append(payload)
        if len(self._recent_ticks) > self.HISTORY_SIZE:
            self._recent_ticks = self._recent_ticks[-self.HISTORY_SIZE:]

        stale: List[asyncio.Queue] = []
        for queue in self._subscribers:
            try:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(payload)
            except Exception:  # noqa: BLE001
                stale.append(queue)
        for q in stale:
            self._subscribers.discard(q)

    # ── 訂閱者 ────────────────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    # ── 歷史快照 ─────────────────────────────────────────────────────────────

    def get_recent_ticks(
        self,
        stock_symbols: Set[str] | None = None,
        include_futures: bool = False,
        limit: int = 120,
    ) -> List[dict]:
        """傳回最近 N 筆 tick（給新連線的 WS 客戶端回補）。"""
        result: List[dict] = []
        for t in reversed(self._recent_ticks):
            sym = t.get("symbol", "")
            asset = t.get("asset_type", "")
            if stock_symbols and sym in stock_symbols:
                result.append(t)
            elif include_futures and asset == AssetType.FUTURES.value:
                result.append(t)
            elif not stock_symbols and not include_futures:
                result.append(t)
            if len(result) >= limit:
                break
        result.reverse()
        return result

    # ── 健康狀態 ──────────────────────────────────────────────────────────────

    def get_health(self) -> dict:
        return {
            "running":        self._running,
            "shioaji_active": self._shioaji_active,
            "subscribed_stk": len(self._subscribed_stk),
            "subscribed_fop": len(self._subscribed_fop),
            "ws_subscribers": len(self._subscribers),
            "tick_count":     self._tick_count,
            "last_tick_ts":   self._last_tick_ts,
            "last_error":     self._last_error,
        }


all_around_engine = AllAroundEngine()
