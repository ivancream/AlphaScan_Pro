"""
波段選股海選 API

回應速度優先順序（三層快速路徑）：
  1. StaticCache (12h in-memory)     → < 1 ms
  2. _SCAN_CACHE (盤中 30 分鐘排程)  → < 1 ms，欄位格式與前端完全相容
  3. BollingerStrategy.screen_from_db → 原始全市場掃描，1~3 分鐘

若 1、2 皆無快取（例如系統剛重啟、盤前），才走路徑 3；
路徑 3 完成後同步寫入 StaticCache，後續讀取瞬間回傳。
"""
import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response
from pydantic import BaseModel
from typing import Any, Dict, List

from engines.engine_intraday_scanner import (
    _SCAN_CACHE,
    _run_scan as _intraday_run_scan,
    get_last_signals_from_db,
)
from backend.engines.cache_store import StaticCache, TTL_12H
from backend.engines.disposition_overlay import enrich_scan_rows_disposition

router = APIRouter()

_CACHE_CONTROL = f"public, max-age={TTL_12H}, stale-while-revalidate=600"


class ScanTargetResponse(BaseModel):
    results: List[Dict[str, Any]]
    cached: bool = False
    source: str = "live"      # "static_cache" | "intraday_cache" | "live"


def _strip_private(items: List[Dict]) -> List[Dict]:
    """移除以底線開頭的私有欄位（_ticker、_q_data 等），使回傳 JSON 乾淨。"""
    return [{k: v for k, v in item.items() if not k.startswith("_")} for item in items]


def _get_intraday(strategy: str) -> List[Dict]:
    """從盤中排程快取讀取指定策略結果（非同步安全：純字典讀取）。"""
    return _strip_private(_SCAN_CACHE.get(strategy, []))


def _finalize_wanderer_results(items: List[Dict]) -> List[Dict]:
    """淺拷貝後依 disposition_events 補齊處置欄位（StaticCache／舊掃描結果相容）。"""
    out = [dict(r) for r in items]
    enrich_scan_rows_disposition(out)
    return out


# ── 多方布林突破 ───────────────────────────────────────────────────────────────

@router.get("/api/v1/swing/long", response_model=ScanTargetResponse)
async def scan_swing_long(
    response: Response,
    background_tasks: BackgroundTasks,
    req_ma:    bool = Query(True),
    req_vol:   bool = Query(True),
    req_slope: bool = Query(True),
):
    """
    多方布林海選。優先讀取快取（< 1 ms），快取不存在時才執行全市場掃描。
    """
    key    = StaticCache.make_key("swing:long", req_ma=req_ma, req_vol=req_vol, req_slope=req_slope)

    # ── 路徑 1：StaticCache ──────────────────────────────────────────────────
    cached = StaticCache.get(key)
    if cached is not None:
        response.headers["Cache-Control"] = _CACHE_CONTROL
        response.headers["X-Cache"] = "HIT"
        return {"results": cached, "cached": True, "source": "static_cache"}

    # ── 路徑 2：盤中排程快取 _SCAN_CACHE ────────────────────────────────────
    intraday = _get_intraday("long")
    if intraday:
        StaticCache.set(key, intraday, ttl=TTL_12H)
        response.headers["Cache-Control"] = _CACHE_CONTROL
        response.headers["X-Cache"] = "HIT"
        return {"results": intraday, "cached": True, "source": "intraday_cache"}

    # ── 路徑 3：非阻塞回應，掃描改背景預熱（避免 API 逾時） ────────────────
    background_tasks.add_task(_maybe_warm_scanner)
    try:
        results = _strip_private(get_last_signals_from_db("long", limit=500))
        if results:
            StaticCache.set(key, results, ttl=TTL_12H)
        response.headers["Cache-Control"] = _CACHE_CONTROL
        response.headers["X-Cache"] = "MISS"
        return {"results": results, "cached": False, "source": "live"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 空方布林跌破 ───────────────────────────────────────────────────────────────

@router.get("/api/v1/swing/short", response_model=ScanTargetResponse)
async def scan_swing_short(
    response: Response,
    background_tasks: BackgroundTasks,
    req_ma:        bool = Query(True),
    req_slope:     bool = Query(True),
    req_chips:     bool = Query(True),
    req_near_band: bool = Query(True),
):
    key    = StaticCache.make_key("swing:short",
        req_ma=req_ma, req_slope=req_slope,
        req_chips=req_chips, req_near_band=req_near_band)

    cached = StaticCache.get(key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return {"results": cached, "cached": True, "source": "static_cache"}

    intraday = _get_intraday("short")
    if intraday:
        StaticCache.set(key, intraday, ttl=TTL_12H)
        response.headers["X-Cache"] = "HIT"
        return {"results": intraday, "cached": True, "source": "intraday_cache"}

    background_tasks.add_task(_maybe_warm_scanner)
    try:
        results = _strip_private(get_last_signals_from_db("short", limit=500))
        if results:
            StaticCache.set(key, results, ttl=TTL_12H)
        response.headers["X-Cache"] = "MISS"
        return {"results": results, "cached": False, "source": "live"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 浪子回頭 ──────────────────────────────────────────────────────────────────

@router.get("/api/v1/swing/wanderer", response_model=ScanTargetResponse)
async def scan_swing_wanderer(
    response: Response,
    background_tasks: BackgroundTasks,
    req_slope:    bool = Query(True),
    req_bb_level: bool = Query(True),
):
    key    = StaticCache.make_key("swing:wanderer", req_slope=req_slope, req_bb_level=req_bb_level)

    cached = StaticCache.get(key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return {"results": _finalize_wanderer_results(cached), "cached": True, "source": "static_cache"}

    intraday = _get_intraday("wanderer")
    if intraday:
        enriched = _finalize_wanderer_results(intraday)
        StaticCache.set(key, enriched, ttl=TTL_12H)
        response.headers["X-Cache"] = "HIT"
        return {"results": enriched, "cached": True, "source": "intraday_cache"}

    background_tasks.add_task(_maybe_warm_scanner)
    try:
        raw_w = get_last_signals_from_db("wanderer", limit=500)
        results = _strip_private(_finalize_wanderer_results(raw_w))
        if results:
            StaticCache.set(key, results, ttl=TTL_12H)
        response.headers["X-Cache"] = "MISS"
        return {"results": results, "cached": False, "source": "live"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 快取管理 ──────────────────────────────────────────────────────────────────

@router.delete("/api/v1/swing/cache")
async def clear_swing_cache():
    """清除 StaticCache 中所有雙刀戰法快取（日 K 更新後呼叫）。"""
    n = StaticCache.invalidate_prefix("swing:")
    return {"message": f"已清除 {n} 筆雙刀戰法快取"}


# ── 內部工具 ──────────────────────────────────────────────────────────────────

def _maybe_warm_scanner() -> None:
    """
    當快取為空時，在背景觸發盤中掃描器（同步版本，放在 BackgroundTask 中執行）。
    若掃描已在進行中則跳過。
    """
    if _SCAN_CACHE.get("status") not in ("running",):
        try:
            _intraday_run_scan()
            StaticCache.invalidate_prefix("swing:")
        except Exception as exc:
            print(f"[swing warm-up] 背景掃描失敗: {exc}")
