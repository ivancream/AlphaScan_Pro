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
import json
from pathlib import Path
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel

from backend.settings import sinopac_credentials_configured

try:
    from backend.db.connection import DUCKDB_PATH
    _DATA_ROOT = DUCKDB_PATH.parent
except Exception:
    _DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


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

    # Keep a larger in-memory tick window so downstream APIs can still
    # derive intraday metrics shortly after market close.
    HISTORY_SIZE = 100_000

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
        self._futures_underlying_map: Dict[str, str] = {}
        self._tick_count      = 0
        self._last_tick_ts:   Optional[str] = None
        self._last_error:     Optional[str] = None
        self._recent_ticks:   List[dict] = []
        self._loaded_history_date: Optional[str] = None

    # ── 持久化快取 ──────────────────────────────────────────────────────────

    @staticmethod
    def _today_key() -> str:
        return dt.datetime.now().strftime("%Y-%m-%d")

    def _history_path(self, day: str | None = None) -> Path:
        cache_dir = _DATA_ROOT / "all_around_ticks"
        return cache_dir / f"{day or self._today_key()}.jsonl"

    def _load_today_history(self) -> None:
        day = self._today_key()
        if self._loaded_history_date == day:
            return
        path = self._history_path(day)
        self._loaded_history_date = day
        if not path.exists():
            return

        rows: List[dict] = []
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(row, dict):
                        rows.append(row)
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"load tick history failed: {exc}"
            return

        if rows:
            self._recent_ticks = rows[-self.HISTORY_SIZE:]
            self._tick_count = max(self._tick_count, len(self._recent_ticks))
            self._last_tick_ts = str(self._recent_ticks[-1].get("ts") or self._last_tick_ts or "")
            print(f"[AllAround] 載入今日 tick 記錄 {len(self._recent_ticks)} 筆")

    def _persist_tick(self, payload: dict) -> None:
        try:
            path = self._history_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                fh.write("\n")
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"persist tick failed: {exc}"

    # ── 生命週期 ──────────────────────────────────────────────────────────────

    async def start(
        self,
        stk_symbols:      List[str] | None = None,
        futures_prefixes: List[str] | None = None,
        stock_future_underlyings: List[str] | None = None,
        stock_future_names: Dict[str, str] | None = None,
    ) -> None:
        if self._running:
            return

        self._load_today_history()

        if not sinopac_credentials_configured():
            self._last_error = "永豐金 API Key 未設定，全方位監控未啟動"
            print(f"[AllAround] {self._last_error}")
            return

        self._running = True
        self._loop = asyncio.get_event_loop()

        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._bootstrap_shared_session(
                    stk_symbols=stk_symbols or [],
                    futures_prefixes=futures_prefixes or _DEFAULT_FUTURES_PREFIX,
                    stock_future_underlyings=stock_future_underlyings or [],
                    stock_future_names=stock_future_names or {},
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            self._shioaji_active = False
            self._running = False
            print(f"[AllAround] 連線失敗: {exc}")

    async def stop(self) -> None:
        self._running = False
        # 共享 Session 由 sinopac_session.disconnect() 登出；此處不可 logout，否則會踢掉 LiveQuote／Scanner。
        self._api = None
        self._shioaji_active = False
        print("[AllAround] 已停止")

    # ── 共享 Shioaji Session（與 LiveQuote／Scanner 同一登入）──────────────────

    def _bootstrap_shared_session(
        self,
        stk_symbols:      List[str],
        futures_prefixes: List[str],
        stock_future_underlyings: List[str],
        stock_future_names: Dict[str, str],
    ) -> None:
        """
        使用 sinopac_session 已登入的 api，透過 add_stk_handler / add_fop_handler
        接收 master tick 分發。禁止在此另建 Shioaji()，否則會覆蓋 callback 或互踢 Session。
        """
        from backend.engines.sinopac_session import sinopac_session

        import shioaji.constant as sjc

        api = sinopac_session.api
        if api is None:
            self._last_error = "永豐金共享 Session 未連線（startup 登入失敗或未設定金鑰）"
            self._shioaji_active = False
            self._running = False
            print(f"[AllAround] {self._last_error}")
            return

        self._api = api
        sinopac_session.add_stk_handler(self._dispatch_stk_sync)
        sinopac_session.add_fop_handler(self._dispatch_fop_sync)
        print("[AllAround] 已註冊 STK/FOP Tick 分發器（共享 Session）")

        for symbol in stk_symbols:
            self._subscribe_stk(symbol, api, sjc)

        for prefix in futures_prefixes:
            self._subscribe_fop_by_prefix(prefix, api, sjc)

        self._subscribe_stock_futures_for_underlyings(
            stock_future_underlyings,
            api,
            sjc,
            stock_future_names,
        )

        self._shioaji_active = True
        print(
            f"[AllAround] 啟動完成 | "
            f"STK={len(self._subscribed_stk)} FOP={len(self._subscribed_fop)}"
        )

    def _dispatch_stk_sync(self, exchange, tick) -> None:
        """由 sinopac_session master callback 呼叫（同步、非 asyncio 執行緒）。"""
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._handle_stk_tick(tick), self._loop)
        except Exception:  # noqa: BLE001
            pass

    def _dispatch_fop_sync(self, exchange, tick) -> None:
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._handle_fop_tick(tick), self._loop)
        except Exception:  # noqa: BLE001
            pass

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

    def _subscribe_fop_by_prefix(
        self,
        prefix: str,
        api,
        sjc,
        *,
        underlying_symbol: str | None = None,
    ) -> str | None:
        try:
            ns = getattr(api.Contracts.Futures, prefix, None)
            if ns is None:
                return None
            contracts = sorted(
                [c for c in ns],
                key=lambda c: getattr(c, "delivery_date", "9999"),
            )
            if not contracts:
                return None
            contract = contracts[0]
            code = contract.code
            if code in self._subscribed_fop:
                if underlying_symbol:
                    self._futures_underlying_map[code] = self._normalize_symbol(underlying_symbol)
                return code
            api.quote.subscribe(
                contract,
                quote_type=sjc.QuoteType.Tick,
                version=sjc.QuoteVersion.v1,
            )
            self._subscribed_fop.add(code)
            self._name_map[code] = getattr(contract, "name", prefix)
            self._asset_map[code] = AssetType.FUTURES
            if underlying_symbol:
                self._futures_underlying_map[code] = self._normalize_symbol(underlying_symbol)
            print(f"[AllAround] FOP 訂閱: {code}")
            return code
        except Exception as exc:  # noqa: BLE001
            print(f"[AllAround] FOP {prefix} 失敗: {exc}")
            return None

    @staticmethod
    def _normalize_symbol(raw: Any) -> str:
        return str(raw or "").strip().upper().replace(".TW", "").replace(".TWO", "")

    @staticmethod
    def _contract_text(contract: Any) -> str:
        parts = []
        for attr in (
            "code",
            "symbol",
            "name",
            "target_code",
            "target_symbol",
            "underlying_code",
            "underlying_symbol",
            "underlying_name",
        ):
            try:
                value = getattr(contract, attr, None)
            except Exception:
                value = None
            if value:
                parts.append(str(value))
        return " ".join(parts).upper()

    def _contract_matches_underlying(
        self,
        contract: Any,
        underlying: str,
        underlying_name: str,
    ) -> bool:
        sid = self._normalize_symbol(underlying)
        if not sid:
            return False

        for attr in ("target_code", "target_symbol", "underlying_code", "underlying_symbol"):
            try:
                value = self._normalize_symbol(getattr(contract, attr, ""))
            except Exception:
                value = ""
            if value == sid:
                return True

        text = self._contract_text(contract)
        if sid in text:
            return True
        name = str(underlying_name or "").strip().upper()
        return bool(name and name in text)

    def _iter_futures_contracts(self, api) -> List[Any]:
        futures_root = getattr(api.Contracts, "Futures", None)
        if futures_root is None:
            return []

        out: List[Any] = []
        seen: Set[int] = set()

        def walk(obj: Any, depth: int = 0) -> None:
            if obj is None or depth > 5:
                return
            oid = id(obj)
            if oid in seen:
                return
            seen.add(oid)

            code = getattr(obj, "code", None)
            if code and getattr(obj, "delivery_date", None):
                out.append(obj)
                return

            if isinstance(obj, dict):
                for child in obj.values():
                    walk(child, depth + 1)
                return

            if isinstance(obj, (list, tuple, set)):
                for child in obj:
                    walk(child, depth + 1)
                return

            try:
                keys = obj.keys()
            except Exception:
                keys = None
            if keys is not None:
                for key in list(keys):
                    try:
                        walk(obj[key], depth + 1)
                    except Exception:
                        try:
                            walk(obj.get(key), depth + 1)
                        except Exception:
                            continue

            try:
                for child in obj:
                    if isinstance(child, (str, bytes)):
                        continue
                    walk(child, depth + 1)
            except Exception:
                pass

            for name in dir(obj):
                if name.startswith("_"):
                    continue
                try:
                    child = getattr(obj, name)
                except Exception:
                    continue
                if callable(child) or isinstance(child, (str, bytes, int, float, bool)):
                    continue
                walk(child, depth + 1)

        walk(futures_root)
        unique: Dict[str, Any] = {}
        for contract in out:
            code = str(getattr(contract, "code", "") or "")
            if code:
                unique[code] = contract
        return list(unique.values())

    def _subscribe_fop_contract(
        self,
        contract: Any,
        api,
        sjc,
        *,
        underlying_symbol: str | None = None,
    ) -> str | None:
        try:
            code = str(getattr(contract, "code", "") or "")
            if not code or code in self._subscribed_fop:
                if code and underlying_symbol:
                    self._futures_underlying_map[code] = self._normalize_symbol(underlying_symbol)
                return code if code else None
            api.quote.subscribe(
                contract,
                quote_type=sjc.QuoteType.Tick,
                version=sjc.QuoteVersion.v1,
            )
            self._subscribed_fop.add(code)
            self._name_map[code] = getattr(contract, "name", code)
            self._asset_map[code] = AssetType.FUTURES
            if underlying_symbol:
                self._futures_underlying_map[code] = self._normalize_symbol(underlying_symbol)
            print(f"[AllAround] FOP 訂閱: {code}")
            return code
        except Exception as exc:  # noqa: BLE001
            print(f"[AllAround] FOP 合約訂閱失敗: {exc}")
            return None

    def _subscribe_stock_futures_for_underlyings(
        self,
        underlyings: List[str],
        api,
        sjc,
        names: Dict[str, str] | None = None,
        *,
        max_contracts_per_underlying: int = 1,
    ) -> List[str]:
        symbols = [self._normalize_symbol(s) for s in underlyings]
        symbols = [s for s in dict.fromkeys(symbols) if s]
        if not symbols or max_contracts_per_underlying <= 0:
            return []

        name_map = {self._normalize_symbol(k): str(v or "") for k, v in (names or {}).items()}
        all_contracts = self._iter_futures_contracts(api)
        subscribed: List[str] = []

        for sid in symbols:
            matches = [
                c for c in all_contracts
                if self._contract_matches_underlying(c, sid, name_map.get(sid, ""))
            ]
            matches = sorted(
                matches,
                key=lambda c: (
                    str(getattr(c, "delivery_date", "9999") or "9999"),
                    str(getattr(c, "code", "") or ""),
                ),
            )
            for contract in matches[:max_contracts_per_underlying]:
                code = self._subscribe_fop_contract(
                    contract,
                    api,
                    sjc,
                    underlying_symbol=sid,
                )
                if code:
                    subscribed.append(code)

        return [c for c in dict.fromkeys(subscribed) if c]

    def add_stock_futures_for_underlyings(
        self,
        underlyings: List[str],
        names: Dict[str, str] | None = None,
    ) -> List[str]:
        """Dynamically subscribe nearest stock futures for underlying stocks."""
        from backend.engines.sinopac_session import sinopac_session

        api = self._api or sinopac_session.api
        if api is None:
            return []

        if self._loop is None:
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                return []

        self._api = api
        sinopac_session.add_fop_handler(self._dispatch_fop_sync)

        try:
            import shioaji.constant as sjc

            return self._subscribe_stock_futures_for_underlyings(
                underlyings,
                self._api,
                sjc,
                names or {},
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[AllAround] 股票期貨動態訂閱失敗: {exc}")
            return []

    def add_stock_futures_by_product_codes(
        self,
        stock_to_product_code: Dict[str, str],
    ) -> List[str]:
        """Subscribe nearest stock futures using TAIFEX product codes."""
        from backend.engines.sinopac_session import sinopac_session

        api = self._api or sinopac_session.api
        if api is None:
            return []

        if self._loop is None:
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                return []

        self._api = api
        sinopac_session.add_fop_handler(self._dispatch_fop_sync)

        try:
            import shioaji.constant as sjc

            out: List[str] = []
            for stock_id, product_code in stock_to_product_code.items():
                raw_code = str(product_code or "").strip().upper()
                if not raw_code:
                    continue
                candidates = [raw_code] if raw_code.endswith("F") else [f"{raw_code}F", raw_code]
                for prefix in candidates:
                    code = self._subscribe_fop_by_prefix(
                        prefix,
                        self._api,
                        sjc,
                        underlying_symbol=stock_id,
                    )
                    if code:
                        out.append(code)
                        break
            return [c for c in dict.fromkeys(out) if c]
        except Exception as exc:  # noqa: BLE001
            print(f"[AllAround] 期交所商品代碼訂閱股票期貨失敗: {exc}")
            return []

    def add_stk_symbols(self, symbols: List[str]) -> None:
        """個股頁 WS 連線時動態訂閱；即使 start() 未成功，仍嘗試使用共享 Session。"""
        from backend.engines.sinopac_session import sinopac_session

        api = self._api or sinopac_session.api
        if api is None:
            return

        if self._loop is None:
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                return

        self._api = api
        sinopac_session.add_stk_handler(self._dispatch_stk_sync)
        sinopac_session.add_fop_handler(self._dispatch_fop_sync)

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
        self._persist_tick(payload)

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
        self._load_today_history()
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

    def get_stock_futures_underlying_map(self) -> Dict[str, str]:
        return dict(self._futures_underlying_map)

    # ── 健康狀態 ──────────────────────────────────────────────────────────────

    def get_health(self) -> dict:
        return {
            "running":        self._running,
            "shioaji_active": self._shioaji_active,
            "subscribed_stk": len(self._subscribed_stk),
            "subscribed_fop": len(self._subscribed_fop),
            "stock_futures_mapped": len(self._futures_underlying_map),
            "ws_subscribers": len(self._subscribers),
            "tick_count":     self._tick_count,
            "last_tick_ts":   self._last_tick_ts,
            "last_error":     self._last_error,
            "history_file":    str(self._history_path()),
            "history_loaded_date": self._loaded_history_date,
        }


all_around_engine = AllAroundEngine()
