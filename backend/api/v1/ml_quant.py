"""
ML 量化：每日收盤後規則推論（WFO surviving rules + HMM regime）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.engines.ml_pipeline.daily_inference import (
    resolve_universe,
    run_daily_inference,
)

router = APIRouter()


@router.get("/api/v1/ml-quant/daily-picks")
def get_ml_quant_daily_picks(
    universe: str = Query(
        "all",
        description="標的範圍：all | watchlist | symbols（symbols 時需傳 symbols 參數）",
    ),
    symbols: Optional[str] = Query(
        None,
        description="逗號分隔股票代碼，僅當 universe=symbols 時有效",
    ),
    lookback: int = Query(
        100,
        ge=30,
        le=300,
        description="每位特徵計算回溯之交易日數（與歷史 K 視窗一致）",
    ),
    rules_path: Optional[str] = Query(
        None,
        description="覆寫 wfo_surviving_rules.json 路徑（選填，預設 data/ml_datasets）",
    ),
) -> Dict[str, Any]:
    """
    執行最新大盤 regime 與 WFO 規則選股，回傳 JSON 供前端使用。
    """
    try:
        u = resolve_universe(universe, symbols)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    rpath = Path(rules_path) if rules_path else None

    try:
        return run_daily_inference(
            universe=u,
            lookback_trading_days=int(lookback),
            rules_path=rpath,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"推論失敗: {exc!s}") from exc
