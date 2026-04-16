"""
盤中掃描器 API 路由

端點一覽：
  GET  /api/v1/scanner/status              掃描狀態（即時）
  GET  /api/v1/scanner/results/{strategy}  讀取快取結果（多方/空方/浪子）
  POST /api/v1/scanner/trigger             手動觸發一次全市場掃描
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.engines.engine_intraday_scanner import (
    get_scan_status,
    get_scan_results,
    get_last_signals_from_db,
    _is_market_hours,
    _run_scan,
    _SCAN_CACHE,
)

router = APIRouter(prefix="/api/v1/scanner", tags=["Intraday Scanner"])

StrategyType = Literal["long", "short", "wanderer"]


@router.get("/status")
async def scanner_status() -> Dict[str, Any]:
    """
    回傳目前掃描器的執行狀態與各策略命中數量。

    Response 範例::

        {
          "status":   "done",
          "message":  "完成！多方 12 / 空方 5 / 浪子 8 檔，耗時 47.3s",
          "last_run": "2026-04-15T10:00:03+08:00",
          "elapsed_sec": 47.3,
          "scan_id":  "a1b2c3d4",
          "counts":   {"long": 12, "short": 5, "wanderer": 8},
          "is_market_hours": true
        }
    """
    return get_scan_status()


@router.get("/results/{strategy}")
async def scanner_results(
    strategy: StrategyType,
    limit: int = Query(default=200, ge=1, le=1000),
    fallback_db: bool = Query(
        default=True,
        description="若記憶體快取為空，是否改從 intraday_signals 表讀取上次結果",
    ),
) -> Dict[str, Any]:
    """
    取得指定策略的掃描命中標的清單。

    - **strategy**: `long`（多方布林突破） / `short`（空方）/ `wanderer`（浪子回頭）
    - **limit**: 最多回傳幾筆（預設 200）
    - **fallback_db**: 記憶體快取空時自動改讀資料庫（預設 True）

    Response 範例::

        {
          "strategy": "long",
          "count":    12,
          "source":   "cache",
          "last_run": "2026-04-15T10:00:03+08:00",
          "items":    [ { "代號": "2330", "名稱": "台積電", ... }, ... ]
        }
    """
    items = get_scan_results(strategy)
    source = "cache"

    if not items and fallback_db:
        items = get_last_signals_from_db(strategy, limit=limit)
        source = "db" if items else "empty"

    items = items[:limit]
    return {
        "strategy": strategy,
        "count":    len(items),
        "source":   source,
        "last_run": _SCAN_CACHE.get("last_run"),
        "items":    items,
    }


@router.post("/trigger")
async def trigger_scan() -> Dict[str, str]:
    """
    手動觸發一次全市場技術面掃描（背景非同步執行）。

    - 若已有掃描在執行中，回傳 409 Conflict。
    - 掃描結束後結果寫入記憶體快取與 intraday_signals 表。
    - 以 GET /api/v1/scanner/status 輪詢進度。
    - _scan_lock 防重入：即使排程與手動觸發同時執行，也不會重複掃描。
    """
    if _SCAN_CACHE.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="掃描作業進行中，請稍後再試",
        )

    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _run_scan)
    return {
        "message": "已觸發盤中全市場掃描，請以 /api/v1/scanner/status 查詢進度",
        "status":  "started",
    }


@router.post("/start-scheduler")
async def restart_scheduler() -> Dict[str, str]:
    """
    重新啟動 APScheduler（若因例外停止時手動恢復用）。
    正常情況下排程由 FastAPI startup 自動啟動。
    """
    from backend.scheduler import start_scheduler as _start_apscheduler
    _start_apscheduler()
    return {"message": "APScheduler 排程器已（重新）啟動"}
