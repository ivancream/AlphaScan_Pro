"""
Shioaji 全域共享連線管理器 (Singleton)

設計原則
─────────────────────────────────────────────────────────────────────────────
Shioaji 同一組 API Key **只允許一個活躍登入 Session**。
本模組提供 thread-safe 的 singleton，所有引擎（LiveQuote / AllAround / Scanner）
共用同一個 api 物件，避免多次 login 互踢造成行情斷線。

使用方式
─────────────────────────────────────────────────────────────────────────────
    from backend.engines.sinopac_session import sinopac_session

    # 在 executor / 同步執行緒中登入（fetch_contract=True 需要 5-15 秒）
    api = sinopac_session.connect()

    # 取得已連線的 api（不重新登入）
    api = sinopac_session.api

    # 批次取得 OHLCV 快照（返回 {stock_id: {Open,High,Low,Close,Volume,ChangeRate}}）
    ohlcv = sinopac_session.get_ohlcv_map(["2330", "2317"])

Tick 回調注意事項
─────────────────────────────────────────────────────────────────────────────
Shioaji 的 @api.on_tick_stk_v1() 與 @api.on_tick_fop_v1() 每次呼叫都會
**覆蓋**前一個 callback（非堆疊）。
若多個引擎需同時接收 Tick，應改用「單一 master callback + 分發」模式：

    @api.on_tick_stk_v1()
    def _master_tick(exchange, tick):
        sinopac_session.dispatch_stk_tick(exchange, tick)

    sinopac_session.add_stk_handler(live_quote_engine._on_tick_handler)
    sinopac_session.add_stk_handler(all_around_engine._on_tick_handler)

本模組已實作此 dispatch 機制，引擎只需呼叫 add_stk_handler / add_fop_handler
即可安全地共享同一個 Tick 推播流。
"""
from __future__ import annotations

import threading
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from backend.settings import get_sinopac_env, sinopac_credentials_configured

_SNAPSHOT_BATCH = 450


class SinopacSession:
    """Shioaji 全域共享連線 (Thread-safe Singleton)。"""

    def __init__(self) -> None:
        self._api: Any = None
        self._lock = threading.Lock()
        self._connected = False
        self._last_error: Optional[str] = None

        # Tick 分發器：handler list，每個引擎各自注冊
        self._stk_handlers: List[Callable] = []
        self._fop_handlers: List[Callable] = []
        self._callbacks_registered = False

    # ── 連線管理 ─────────────────────────────────────────────────────────────

    def connect(self) -> Optional[Any]:
        """
        同步登入（請在 run_in_executor 內呼叫，避免阻塞 asyncio event loop）。
        若已連線則直接回傳現有 api 物件；失敗回傳 None。
        """
        if self._connected and self._api is not None:
            return self._api

        with self._lock:
            if self._connected and self._api is not None:
                return self._api
            return self._do_login()

    def _do_login(self) -> Optional[Any]:
        if not sinopac_credentials_configured():
            self._last_error = "未設定 SINOPAC_API_KEY / SINOPAC_SECRET_KEY"
            print(f"[SinopacSession] {self._last_error}")
            return None

        creds = get_sinopac_env()
        try:
            import shioaji as sj

            api = sj.Shioaji(simulation=creds["simulation"])
            api.login(
                api_key=creds["api_key"],
                secret_key=creds["secret_key"],
                fetch_contract=True,
            )
            self._api = api
            self._connected = True
            self._last_error = None
            self._register_master_callbacks(api)
            print(f"[SinopacSession] 登入成功 (simulation={creds['simulation']})")
            return api
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            self._api = None
            self._connected = False
            print(f"[SinopacSession] 登入失敗: {exc}")
            return None

    def disconnect(self) -> None:
        """登出並釋放連線（FastAPI shutdown 時呼叫）。"""
        with self._lock:
            if self._api is not None:
                try:
                    self._api.logout()
                except Exception:  # noqa: BLE001
                    pass
                self._api = None
                self._connected = False
                print("[SinopacSession] 已登出")

    # ── Master Tick 分發器 ───────────────────────────────────────────────────

    def _register_master_callbacks(self, api: Any) -> None:
        """在共享 api 上注冊「唯一一個」master callback，再分發給各引擎。"""
        if self._callbacks_registered:
            return

        @api.on_tick_stk_v1()
        def _master_stk(exchange, tick):
            for handler in self._stk_handlers:
                try:
                    handler(exchange, tick)
                except Exception:  # noqa: BLE001
                    pass

        @api.on_tick_fop_v1()
        def _master_fop(exchange, tick):
            for handler in self._fop_handlers:
                try:
                    handler(exchange, tick)
                except Exception:  # noqa: BLE001
                    pass

        self._callbacks_registered = True
        print("[SinopacSession] Master tick callbacks 已注冊")

    def add_stk_handler(self, handler: Callable) -> None:
        """新增股票 Tick 處理器（允許多個引擎共用）。"""
        if handler not in self._stk_handlers:
            self._stk_handlers.append(handler)

    def add_fop_handler(self, handler: Callable) -> None:
        """新增期貨/選擇權 Tick 處理器。"""
        if handler not in self._fop_handlers:
            self._fop_handlers.append(handler)

    # ── Snapshot 批次查詢 ────────────────────────────────────────────────────

    def get_ohlcv_map(self, stock_ids: List[str]) -> Dict[str, Dict]:
        """
        批次取得盤中 OHLCV 快照。

        回傳格式::

            {
                "2330": {
                    "Open": 580.0, "High": 590.0, "Low": 578.0,
                    "Close": 585.0,
                    "Volume": 77_606_000.0,   # total_volume（張）× 1000 → 股
                    "ChangeRate": 2.77,
                },
                ...
            }

        量的換算說明：
        - snap.volume      = 最後一筆的成交張數（例如 48 張）← 不是要用的！
        - snap.total_volume = 當日累積成交張數（例如 77,606 張）← 日K 要用這個
        - 回傳 Volume = total_volume × 1000，與 daily_price 表（單位：股）一致。
        """
        api = self._api
        if api is None:
            return {}

        unique_ids = list(dict.fromkeys(
            str(s).strip() for s in stock_ids if str(s).strip()
        ))
        if not unique_ids:
            return {}

        out: Dict[str, Dict] = {}

        for start in range(0, len(unique_ids), _SNAPSHOT_BATCH):
            chunk = unique_ids[start: start + _SNAPSHOT_BATCH]
            contracts = []
            for sid in chunk:
                try:
                    c = api.Contracts.Stocks[sid]
                except Exception:  # noqa: BLE001
                    try:
                        c = api.Contracts.Stocks.get(sid)
                    except Exception:  # noqa: BLE001
                        c = None
                if c is not None:
                    contracts.append(c)

            if not contracts:
                continue

            try:
                snapshots = api.snapshots(contracts)
            except Exception as exc:  # noqa: BLE001
                print(f"[SinopacSession] snapshots 批次失敗: {exc}")
                continue

            if not snapshots:
                continue

            for c, snap in zip(contracts, snapshots):
                if snap is None:
                    continue
                code = str(
                    getattr(snap, "code", None) or getattr(c, "code", "")
                ).strip()
                if not code:
                    continue

                try:
                    o   = float(getattr(snap, "open",  0) or 0)
                    h   = float(getattr(snap, "high",  0) or 0)
                    lo  = float(getattr(snap, "low",   0) or 0)
                    cl  = float(getattr(snap, "close", 0) or 0)
                    # total_volume（張）× 1000 → 股，與 daily_price 表保持一致
                    vol = float(getattr(snap, "total_volume", 0) or 0) * 1000
                    chg = float(getattr(snap, "change_rate",  0) or 0)
                except (TypeError, ValueError):
                    continue

                if cl <= 0:
                    continue

                out[code] = {
                    "Open":       o  if o  > 0 else cl,
                    "High":       h  if h  > 0 else cl,
                    "Low":        lo if lo > 0 else cl,
                    "Close":      cl,
                    "Volume":     vol,
                    "ChangeRate": chg,
                }

        if out:
            print(f"[SinopacSession] 批次快照完成，共 {len(out)} 檔")
        return out

    def get_change_pct_map(self, stock_ids: List[str]) -> Dict[str, float]:
        """只取漲跌幅，供 merge_sinopac_change_pct_into_rows 使用。"""
        ohlcv = self.get_ohlcv_map(stock_ids)
        return {code: d["ChangeRate"] for code, d in ohlcv.items()}

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def api(self) -> Optional[Any]:
        return self._api

    @property
    def is_connected(self) -> bool:
        return self._connected and self._api is not None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error


# ── 全域單例 ─────────────────────────────────────────────────────────────────
sinopac_session = SinopacSession()
