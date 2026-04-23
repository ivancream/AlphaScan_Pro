"""
correlation.py — 雙刀戰法 API

Endpoints:
    GET /api/v1/correlation/spread
    GET /api/v1/correlation/meta/info
    GET /api/v1/correlation/{stock_id}
"""

import math
from datetime import date

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from backend.db import queries
from backend.db.symbol_utils import strip_suffix

router = APIRouter()


def _enrich_pearson_only_rows(
    sid: str,
    rows: list,
    lookback_days: int,
) -> dict[str, dict]:
    """
    pearson_only 時補算：① 近 lookback_days 日收盤價比值之 mean／std／Z；
    ② 若配對通過 build_correlations 同款 ADF／EG，一併填入半衰期、綜合分等。
    """
    from backend.scripts.build_correlations import _calc_composite_score, _screen_pair

    sid_n = str(sid).strip()
    peer_ids = [str(r["peer_id"]).strip() for r in rows if r.get("peer_id")]
    if not peer_ids:
        return {}

    df_raw = queries.get_price_for_symbols([sid_n] + peer_ids, days=max(380, lookback_days * 6))
    if df_raw.empty:
        return {}

    df_raw = df_raw.copy()
    df_raw["stock_id"] = df_raw["stock_id"].astype(str).str.strip()
    pv = df_raw.pivot_table(
        index="date", columns="stock_id", values="close", aggfunc="last"
    ).sort_index()
    if sid_n not in pv.columns:
        return {}

    out: dict[str, dict] = {}
    for r in rows:
        pid = str(r.get("peer_id", "")).strip()
        if not pid or pid not in pv.columns:
            continue
        sub = pv[[sid_n, pid]].dropna(how="any")
        if sub.empty or len(sub) < 20:
            continue

        tail_n = min(int(lookback_days), len(sub))
        block = sub.iloc[-tail_n:]
        ra = block[sid_n].astype(float)
        rb = block[pid].astype(float)
        ratio_s = ra / rb
        ratio_s = ratio_s.replace([float("inf"), float("-inf")], float("nan")).dropna()
        if len(ratio_s) < 2:
            continue
        rs_std = float(ratio_s.std(ddof=1))
        if not math.isfinite(rs_std) or rs_std <= 1e-12:
            continue
        rm60 = float(ratio_s.mean())
        cur = float(ratio_s.iloc[-1])
        z60 = round((cur - rm60) / rs_std, 2) if math.isfinite(cur) and math.isfinite(rm60) else None

        extra: dict = {
            "ratio_mean": rm60,
            "ratio_std": rs_std,
            "current_z_score": z60,
        }

        p_adf, p_eg, hl, rm252, rs252, z_cross, hr = _screen_pair(sub, sid_n, pid)
        if p_adf is not None and p_eg is not None:
            try:
                corr_v = float(r.get("correlation", 0.0))
            except (TypeError, ValueError):
                corr_v = 0.0
            extra["adf_p_value"] = float(p_adf)
            extra["eg_p_value"] = float(p_eg)
            extra["half_life"] = float(hl) if hl is not None and math.isfinite(hl) else None
            extra["zero_crossings"] = int(z_cross or 0)
            extra["hedge_ratio"] = float(hr) if hr is not None and math.isfinite(hr) else None
            extra["composite_score"] = float(
                _calc_composite_score(corr_v, hl, int(z_cross or 0))
            )
            # 雙刀通過時，比值基準改與建置腳本一致（約 252 日），Z 改以該基準計算
            if rm252 is not None and rs252 is not None:
                try:
                    rms = float(rs252)
                    rmm = float(rm252)
                    if math.isfinite(rms) and rms > 1e-12 and math.isfinite(rmm) and math.isfinite(cur):
                        extra["ratio_mean"] = rmm
                        extra["ratio_std"] = rms
                        extra["current_z_score"] = round((cur - rmm) / rms, 2)
                except (TypeError, ValueError):
                    pass

        out[pid] = extra
    return out


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

    pair_meta = queries.get_correlation_pair(sid_a, sid_b)
    is_cointegrated = False
    if pair_meta is not None:
        try:
            p_adf = float(pair_meta.get("adf_p_value"))
            p_eg = float(pair_meta.get("eg_p_value"))
            is_cointegrated = math.isfinite(p_adf) and math.isfinite(p_eg) and p_adf < 0.05 and p_eg < 0.05
        except (TypeError, ValueError):
            is_cointegrated = False

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

    # Scanner-Chart Sync: 若該配對存在於 correlations，優先使用 DB 基準畫圖
    if pair_meta is not None:
        try:
            db_mean = float(pair_meta.get("ratio_mean"))
            db_std = float(pair_meta.get("ratio_std"))
            if math.isfinite(db_mean) and math.isfinite(db_std) and db_std > 1e-12:
                ratio_mean_full = db_mean
                ratio_std_full = db_std
        except (TypeError, ValueError):
            pass

    if not math.isfinite(ratio_std_full) or ratio_std_full <= 1e-12:
        ratio_std_full = 1e-9

    def _num_or_none(v, nd: int):
        if v is None:
            return None
        try:
            x = float(v)
            if not math.isfinite(x):
                return None
            return round(x, nd)
        except (TypeError, ValueError):
            return None

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
        "is_cointegrated": is_cointegrated,
        "calc_date": pair_meta.get("calc_date") if pair_meta else None,
        "correlation": _num_or_none(pair_meta.get("correlation") if pair_meta else None, 4),
        "adf_p_value": _num_or_none(pair_meta.get("adf_p_value") if pair_meta else None, 4),
        "eg_p_value": _num_or_none(pair_meta.get("eg_p_value") if pair_meta else None, 4),
        "half_life": _num_or_none(pair_meta.get("half_life") if pair_meta else None, 2),
        "hedge_ratio": _num_or_none(pair_meta.get("hedge_ratio") if pair_meta else None, 4),
        "composite_score": _num_or_none(pair_meta.get("composite_score") if pair_meta else None, 2),
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
    pearson_only = False
    lookback_days = 252

    if not rows:
        rows = queries.get_pearson_peers_live(sid, top_n)
        if rows:
            pearson_only = True
            lookback_days = 60

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"找不到股票 {sid}：無法從日線計算相關係數（可能無 K 線或與其他股票共同交易日不足）。"
                "請確認代號或補齊價量資料。"
            ),
        )

    calc_date = rows[0].get("calc_date") if rows else None
    if pearson_only or not calc_date:
        calc_date = queries.get_latest_price_date() or date.today().isoformat()
    peer_ids = [r["peer_id"] for r in rows]
    names_map = queries.get_stock_names([sid] + peer_ids)
    sector_map = queries.get_sector_theme_map([sid] + peer_ids)
    base_sector = sector_map.get(sid, {})

    # 用最新收盤價算 current_ratio，再用 DB 儲存的 ratio_mean/std 統一計算 Z-Score
    current_ratios: dict[str, float] = {}
    try:
        all_sids = [sid] + peer_ids
        df_raw = queries.get_price_for_symbols(all_sids, days=20)
        if not df_raw.empty:
            df_pivot = df_raw.pivot_table(
                index="date", columns="stock_id", values="close", aggfunc="last"
            )
            if sid in df_pivot.columns:
                for p_id in peer_ids:
                    if p_id in df_pivot.columns:
                        df_p = df_pivot[[sid, p_id]].dropna()
                        if not df_p.empty:
                            close_a = float(df_p[sid].iloc[-1])
                            close_b = float(df_p[p_id].iloc[-1])
                            if close_b != 0 and math.isfinite(close_a) and math.isfinite(close_b):
                                current_ratios[p_id] = close_a / close_b
    except Exception as exc:
        print(f"[Correlation] Z-Score calc error: {exc}")

    def _num_or_none(v, nd: int):
        if v is None:
            return None
        try:
            x = float(v)
            if not math.isfinite(x):
                return None
            return round(x, nd)
        except (TypeError, ValueError):
            return None

    def _zscore_or_none(current_ratio, ratio_mean, ratio_std):
        try:
            cr = float(current_ratio)
            mean = float(ratio_mean)
            std = float(ratio_std)
            if not (math.isfinite(cr) and math.isfinite(mean) and math.isfinite(std)):
                return None
            if std <= 1e-12:
                return None
            return round((cr - mean) / std, 2)
        except (TypeError, ValueError):
            return None

    def _is_same_sector(peer_id: str) -> bool:
        peer_sector = sector_map.get(peer_id, {})
        base_meso = (base_sector.get("meso") or "").strip()
        peer_meso = (peer_sector.get("meso") or "").strip()
        if base_meso and peer_meso and base_meso == peer_meso:
            return True
        base_micro = (base_sector.get("micro") or "").strip()
        peer_micro = (peer_sector.get("micro") or "").strip()
        return bool(base_micro and peer_micro and base_micro == peer_micro)

    pearson_ctx: dict[str, dict] = {}
    if pearson_only:
        pearson_ctx = _enrich_pearson_only_rows(sid, rows, lookback_days)

    results: list = []
    for rank, r in enumerate(rows):
        pid = str(r.get("peer_id", "")).strip()
        ex = pearson_ctx.get(pid, {})
        src = dict(r)
        if ex:
            src.update(ex)

        if pearson_only and ex and ex.get("current_z_score") is not None:
            z_val = ex["current_z_score"]
        else:
            z_val = _zscore_or_none(
                current_ratios.get(pid),
                src.get("ratio_mean"),
                src.get("ratio_std"),
            )

        results.append(
            {
                "rank": rank + 1,
                "peer_id": pid,
                "peer_name": names_map.get(pid, pid),
                "correlation": round(float(r["correlation"]), 4),
                "adf_p_value": _num_or_none(src.get("adf_p_value"), 6),
                "eg_p_value": _num_or_none(src.get("eg_p_value"), 6),
                "half_life": _num_or_none(src.get("half_life"), 2),
                "ratio_mean": _num_or_none(src.get("ratio_mean"), 6),
                "ratio_std": _num_or_none(src.get("ratio_std"), 6),
                "zero_crossings": int(src.get("zero_crossings") or 0),
                "is_same_sector": _is_same_sector(pid),
                "hedge_ratio": _num_or_none(src.get("hedge_ratio"), 6),
                "composite_score": _num_or_none(src.get("composite_score"), 2),
                "current_z_score": z_val,
            }
        )

    return {
        "stock_id": sid,
        "stock_name": names_map.get(sid, sid),
        "calc_date": calc_date,
        "lookback_days": lookback_days,
        "pearson_only": pearson_only,
        "results": results,
    }
