from __future__ import annotations

import asyncio
import math
import time
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.db import queries as db_queries
from backend.db.writer import upsert_warrant_master
from backend.engines.sinopac_session import sinopac_session
from backend.engines.warrant_calculator import compute_warrant_metrics
from backend.engines.warrant_master_build import build_warrant_master_rows

router = APIRouter()
CACHE_TTL_SECONDS = 8.0
_SNAPSHOT_BATCH = 450
_WARRANTS_CACHE: Dict[str, Tuple[float, "WarrantsByUnderlyingResponse"]] = {}


def _clear_warrants_cache() -> None:
    _WARRANTS_CACHE.clear()


def _sync_refresh_warrant_master() -> int:
    rows = build_warrant_master_rows()
    if not rows:
        return 0
    return upsert_warrant_master(rows)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _to_opt_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        val = float(value)
        if not math.isfinite(val):
            return None
        return val
    except Exception:
        return None


def _pick_attr(obj: Any, names: List[str], default: Any = None) -> Any:
    for name in names:
        try:
            val = getattr(obj, name, None)
            if val is not None:
                return val
        except Exception:
            continue
    return default


def _extract_quote_from_snapshot(snap: Any) -> Dict[str, float]:
    bid = _to_float(_pick_attr(snap, ["buy_price", "bid_price", "bid"]))
    ask = _to_float(_pick_attr(snap, ["sell_price", "ask_price", "ask"]))
    last = _to_float(_pick_attr(snap, ["close", "last_price", "trade_price"]))
    return {"bid": bid, "ask": ask, "last": last}


def _extract_extras_from_snapshot(snap: Any) -> Dict[str, Optional[float]]:
    """漲跌幅、五檔買賣量（欄位名依 Shioaji 版本可能不同，取得到才填）。"""
    out: Dict[str, Optional[float]] = {
        "change_pct": None,
        "bid_size": None,
        "ask_size": None,
    }
    if snap is None:
        return out
    out["change_pct"] = _to_opt_float(
        _pick_attr(snap, ["change_rate", "change_percentage", "pct_change"])
    )
    out["bid_size"] = _to_opt_float(
        _pick_attr(
            snap,
            [
                "buy_volume",
                "bid_volume",
                "fix_buy_volume",
                "bid_size",
                "bidsize",
            ],
        )
    )
    out["ask_size"] = _to_opt_float(
        _pick_attr(
            snap,
            [
                "sell_volume",
                "ask_volume",
                "fix_sell_volume",
                "ask_size",
                "asksiz",
            ],
        )
    )
    return out


def _volume_zhang_from_snap(snap: Any) -> Optional[float]:
    """永豐快照常見欄位：total_volume 為當日累積成交張數（張）。"""
    if snap is None:
        return None
    raw = _pick_attr(
        snap,
        ["total_volume", "accumulate_trade_volume", "acc_volume", "volume"],
    )
    v = _to_opt_float(raw)
    if v is None or v < 0:
        return None
    return float(v)


def _resolve_underlying_quote(api: Any, sid: str, contract: Any) -> Tuple[float, Optional[float]]:
    """
    優先使用與 heatmap 相同的 get_ohlcv_map（較穩），再回退 raw snapshot 欄位。
    """
    price = 0.0
    reference: Optional[float] = None
    ohlcv = sinopac_session.get_ohlcv_map([sid])
    row = ohlcv.get(sid)
    if row and float(row.get("Close") or 0) > 0:
        price = float(row["Close"])
    try:
        snaps = api.snapshots([contract]) or []
    except Exception:
        snaps = []
    snap0 = snaps[0] if snaps else None
    if snap0 is not None:
        reference = _to_opt_float(
            _pick_attr(snap0, ["reference", "reference_price", "yesterday_close"])
        )
        if price <= 0:
            price = _to_float(
                _pick_attr(
                    snap0,
                    ["close", "last_price", "trade_price", "price", "open", "fixing_price"],
                )
            )
    return price, reference


class WarrantResponse(BaseModel):
    code: str
    name: str
    cp: Literal["認購", "認售"]
    strike: float
    exercise_ratio: float
    bid: float
    ask: float
    last: float
    volume: Optional[float] = Field(
        default=None,
        description="當日累積成交量（張，來自快照 total_volume 等欄位）",
    )
    change_pct: Optional[float] = Field(
        default=None,
        description="漲跌幅（%，快照 change_rate 等）",
    )
    bid_size: Optional[float] = Field(
        default=None,
        description="委買量（張或口，依券商快照）",
    )
    ask_size: Optional[float] = Field(
        default=None,
        description="委賣量（張或口，依券商快照）",
    )
    underlying_symbol: str
    underlying_price: float
    underlying_reference: Optional[float] = None
    expiry_date: str
    dte_days: int = Field(ge=0)
    moneyness_pct: Optional[float] = None
    spread_pct: Optional[float] = None
    bid_iv: Optional[float] = None
    ask_iv: Optional[float] = None
    bid_delta: Optional[float] = None
    ask_delta: Optional[float] = None
    bid_effective_gearing: Optional[float] = None
    ask_effective_gearing: Optional[float] = None
    spread_gearing_ratio_bid: Optional[float] = None
    spread_gearing_ratio_ask: Optional[float] = None


class WarrantsByUnderlyingResponse(BaseModel):
    """權證列表＋標的報價；主檔為空時仍可能帶入標的即時價供畫面顯示。"""

    underlying_symbol: str
    underlying_price: Optional[float] = None
    underlying_reference: Optional[float] = None
    warrants: List[WarrantResponse]


class WarrantMasterRefreshResult(BaseModel):
    upserted: int
    message: str


def _resolve_stock_contract(api: Any, code: str) -> Any:
    """以權證／股票代號取得 Shioaji 合約（與 sinopac_session.get_ohlcv_map 相同策略）。"""
    sid = (code or "").strip()
    if not sid:
        return None
    try:
        return api.Contracts.Stocks[sid]
    except Exception:
        try:
            return api.Contracts.Stocks.get(sid)
        except Exception:
            return None


def _normalize_cp(raw: object) -> Literal["認購", "認售"]:
    s = str(raw or "")
    if "售" in s:
        return "認售"
    return "認購"


def _coerce_expiry(value: object) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    txt = str(value).strip()
    if not txt:
        return None
    txt = txt[:10].replace("/", "-")
    try:
        return date.fromisoformat(txt)
    except Exception:
        return None


@router.post(
    "/api/v1/warrants/refresh-master",
    response_model=WarrantMasterRefreshResult,
)
async def refresh_warrant_master():
    """
    從 MOPS 下載權證主檔 CSV 並寫入 DuckDB（與執行 ingest 腳本相同）。
    可在後端已佔用 DuckDB 時呼叫，無需另開程序。
    """
    loop = asyncio.get_event_loop()
    try:
        n = await loop.run_in_executor(None, _sync_refresh_warrant_master)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"權證主檔更新失敗: {exc}",
        ) from exc
    if n <= 0:
        raise HTTPException(
            status_code=502,
            detail="未取得可寫入的權證主檔資料（網路或 CSV 格式異常）",
        )
    _clear_warrants_cache()
    return WarrantMasterRefreshResult(
        upserted=n,
        message=f"已寫入 {n} 筆權證主檔，快取已清空。",
    )


@router.get(
    "/api/v1/warrants/{symbol}",
    response_model=WarrantsByUnderlyingResponse,
)
async def get_warrants_by_underlying(symbol: str):
    sid = (symbol or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="symbol 不可為空")

    now = time.time()
    cached = _WARRANTS_CACHE.get(sid)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    master_rows = db_queries.list_warrant_master_by_underlying(sid)

    if not sinopac_session.is_connected:
        sinopac_session.connect()
    api = sinopac_session.api

    def _pack(
        warrants: List[WarrantResponse],
        up: Optional[float],
        ur: Optional[float],
    ) -> WarrantsByUnderlyingResponse:
        return WarrantsByUnderlyingResponse(
            underlying_symbol=sid,
            underlying_price=up if up is not None and up > 0 else None,
            underlying_reference=ur,
            warrants=warrants,
        )

    if api is None:
        if master_rows:
            raise HTTPException(status_code=503, detail="Shioaji 尚未連線，請先確認 API 設定")
        out = _pack([], None, None)
        _WARRANTS_CACHE[sid] = (now, out)
        return out

    underlying_contract = _resolve_stock_contract(api, sid)
    if underlying_contract is None:
        if master_rows:
            raise HTTPException(status_code=404, detail=f"找不到標的股票: {sid}")
        out = _pack([], None, None)
        _WARRANTS_CACHE[sid] = (now, out)
        return out

    underlying_price, underlying_reference = _resolve_underlying_quote(
        api, sid, underlying_contract
    )

    if not master_rows:
        out = _pack([], underlying_price, underlying_reference)
        _WARRANTS_CACHE[sid] = (now, out)
        return out

    if underlying_price <= 0:
        raise HTTPException(
            status_code=503,
            detail=f"無法取得標的 {sid} 有效即時價（盤前／未連線／行情為零）",
        )

    codes = [str(r.get("warrant_code", "") or "").strip() for r in master_rows]
    codes = [c for c in codes if c]
    contracts: List[Any] = []
    for c in codes:
        ct = _resolve_stock_contract(api, c)
        if ct is not None:
            contracts.append(ct)

    snapshot_map: Dict[str, Any] = {}
    for start in range(0, len(contracts), _SNAPSHOT_BATCH):
        chunk = contracts[start : start + _SNAPSHOT_BATCH]
        try:
            snaps = api.snapshots(chunk) or []
        except Exception:
            snaps = []
        for ct, snap in zip(chunk, snaps):
            if snap is None:
                continue
            code = str(getattr(ct, "code", "") or _pick_attr(snap, ["code"], "") or "").strip()
            if code:
                snapshot_map[code] = snap

    rows: List[WarrantResponse] = []
    today = date.today()

    for rec in master_rows:
        code = str(rec.get("warrant_code", "") or "").strip()
        if not code:
            continue

        snap = snapshot_map.get(code)
        quote = (
            _extract_quote_from_snapshot(snap)
            if snap is not None
            else {"bid": 0.0, "ask": 0.0, "last": 0.0}
        )
        vol_zhang = _volume_zhang_from_snap(snap) if snap is not None else None
        extras = (
            _extract_extras_from_snapshot(snap)
            if snap is not None
            else {"change_pct": None, "bid_size": None, "ask_size": None}
        )

        cp = _normalize_cp(rec.get("cp"))
        strike = _to_float(rec.get("strike"))
        ratio = _to_float(rec.get("exercise_ratio"), default=1.0)
        expiry = _coerce_expiry(rec.get("expiry_date"))

        if expiry is None:
            continue

        metrics = compute_warrant_metrics(
            cp=cp,
            strike=strike,
            exercise_ratio=ratio,
            bid=quote["bid"],
            ask=quote["ask"],
            last=quote["last"],
            underlying_price=underlying_price,
            expiry_date=expiry,
            risk_free_rate=0.015,
            today=today,
        )

        rows.append(
            WarrantResponse(
                code=code,
                name=str(rec.get("warrant_name", "") or ""),
                cp=cp,
                strike=strike,
                exercise_ratio=ratio,
                bid=quote["bid"],
                ask=quote["ask"],
                last=quote["last"],
                volume=vol_zhang,
                change_pct=extras["change_pct"],
                bid_size=extras["bid_size"],
                ask_size=extras["ask_size"],
                underlying_symbol=sid,
                underlying_price=underlying_price,
                underlying_reference=underlying_reference,
                expiry_date=expiry.isoformat(),
                dte_days=metrics.dte_days,
                moneyness_pct=_to_opt_float(metrics.moneyness_pct),
                spread_pct=_to_opt_float(metrics.spread_pct),
                bid_iv=_to_opt_float(metrics.bid_iv),
                ask_iv=_to_opt_float(metrics.ask_iv),
                bid_delta=_to_opt_float(metrics.bid_delta),
                ask_delta=_to_opt_float(metrics.ask_delta),
                bid_effective_gearing=_to_opt_float(metrics.bid_effective_gearing),
                ask_effective_gearing=_to_opt_float(metrics.ask_effective_gearing),
                spread_gearing_ratio_bid=_to_opt_float(metrics.spread_gearing_ratio_bid),
                spread_gearing_ratio_ask=_to_opt_float(metrics.spread_gearing_ratio_ask),
            )
        )

    out = _pack(rows, underlying_price, underlying_reference)
    _WARRANTS_CACHE[sid] = (now, out)
    return out
