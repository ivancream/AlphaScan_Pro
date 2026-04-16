"""
correlation.py — 雙刀戰法 API

Endpoints:
    GET /api/v1/correlation/spread
    GET /api/v1/correlation/meta/info
    GET /api/v1/correlation/{stock_id}
"""

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from backend.db import queries
from backend.db.symbol_utils import strip_suffix

router = APIRouter()


# ── 配對走勢比較 ─────────────────────────────────────────────────────────────

@router.get("/api/v1/correlation/spread")
def get_price_spread(
    stock_a: str = Query(..., description="主股代號，如 2330"),
    stock_b: str = Query(..., description="配對股代號，如 2317"),
    days: int = Query(default=60, ge=20, le=250),
    recent_days: int = Query(default=10, ge=5, le=30),
):
    """計算兩支股票的收盤價比值序列與 Z-Score。"""
    sid_a = strip_suffix(stock_a).upper()
    sid_b = strip_suffix(stock_b).upper()

    if sid_a == sid_b:
        raise HTTPException(status_code=400, detail="請輸入不同的兩支股票")

    df_raw = queries.get_price_for_symbols([sid_a, sid_b], days=180)
    if df_raw.empty:
        raise HTTPException(status_code=404, detail="找不到兩支股票的價格資料")

    df_pivot = df_raw.pivot_table(
        index="date", columns="stock_id", values="close", aggfunc="last"
    )
    df_pivot.index = pd.to_datetime(df_pivot.index)
    df_pivot = df_pivot.sort_index()

    missing = [s for s in [sid_a, sid_b] if s not in df_pivot.columns]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"找不到 {', '.join(missing)} 的價格資料，請確認代號",
        )

    df_pair = df_pivot[[sid_a, sid_b]].dropna().tail(days)
    if len(df_pair) < max(recent_days, 10):
        raise HTTPException(
            status_code=400,
            detail=f"有效共同交易日不足 {days} 天，請縮小 days 參數",
        )

    df_pair = df_pair.copy()
    df_pair["ratio"] = df_pair[sid_a] / df_pair[sid_b]

    ratio_mean_full = float(df_pair["ratio"].mean())
    ratio_std_full = float(df_pair["ratio"].std())
    ratio_mean_recent = float(df_pair["ratio"].tail(recent_days).mean())

    if ratio_std_full == 0:
        ratio_std_full = 1e-9

    series = []
    for date_idx, row in df_pair.iterrows():
        r = float(row["ratio"])
        series.append({
            "date": str(date_idx.date()),
            "close_a": round(float(row[sid_a]), 2),
            "close_b": round(float(row[sid_b]), 2),
            "ratio": round(r, 4),
            "z_score": round((r - ratio_mean_full) / ratio_std_full, 2),
            "above_mean": r > ratio_mean_full,
            "above_recent": r > ratio_mean_recent,
        })

    return {
        "stock_a": sid_a,
        "stock_a_name": queries.get_stock_name(sid_a),
        "stock_b": sid_b,
        "stock_b_name": queries.get_stock_name(sid_b),
        "days": len(series),
        "recent_days": recent_days,
        "ratio_mean_full": round(ratio_mean_full, 4),
        "ratio_std_full": round(ratio_std_full, 4),
        "ratio_mean_recent": round(ratio_mean_recent, 4),
        "series": series,
    }


# ── 相關係數 DB 狀態 ──────────────────────────────────────────────────────────

@router.get("/api/v1/correlation/meta/info")
def get_correlation_meta():
    meta = queries.get_correlation_meta()
    if not meta:
        raise HTTPException(
            status_code=503,
            detail="相關係數資料庫尚未建立，請先執行 backend/scripts/build_correlations.py",
        )
    return {
        "last_calc_date": meta.get("last_calc_date", "未知"),
        "stock_count": int(meta.get("stock_count", 0)),
    }


# ── Top-N 相關股 ──────────────────────────────────────────────────────────────

@router.get("/api/v1/correlation/{stock_id}")
def get_top_correlations(
    stock_id: str,
    top_n: int = Query(default=10, ge=1, le=50),
):
    sid = strip_suffix(stock_id).upper()
    rows = queries.get_top_correlations(sid, top_n)

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"找不到股票 {sid} 的相關係數資料，請確認代號或重新建立相關係數資料庫",
        )

    calc_date = rows[0].get("calc_date") if rows else None
    peer_ids = [r["peer_id"] for r in rows]

    # Batch-compute latest Z-Scores
    z_scores: dict[str, float] = {}
    try:
        all_sids = [sid] + peer_ids
        df_raw = queries.get_price_for_symbols(all_sids, days=180)
        if not df_raw.empty:
            df_pivot = df_raw.pivot_table(
                index="date", columns="stock_id", values="close", aggfunc="last"
            )
            df_pivot = df_pivot.tail(60)
            if sid in df_pivot.columns:
                for p_id in peer_ids:
                    if p_id in df_pivot.columns:
                        df_p = df_pivot[[sid, p_id]].dropna()
                        if len(df_p) > 10:
                            ratio = df_p[sid] / df_p[p_id]
                            mean, std = ratio.mean(), ratio.std()
                            if std == 0:
                                std = 1e-9
                            z_scores[p_id] = round(float((ratio.iloc[-1] - mean) / std), 2)
    except Exception as exc:
        print(f"[Correlation] Z-Score calc error: {exc}")

    results = [
        {
            "rank": rank + 1,
            "peer_id": r["peer_id"],
            "peer_name": queries.get_stock_name(r["peer_id"]),
            "correlation": round(float(r["correlation"]), 4),
            "current_z_score": z_scores.get(r["peer_id"]),
        }
        for rank, r in enumerate(rows)
    ]

    return {
        "stock_id": sid,
        "stock_name": queries.get_stock_name(sid),
        "calc_date": calc_date,
        "lookback_days": 60,
        "results": results,
    }
