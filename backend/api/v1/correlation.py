"""
correlation.py
==============
【雙刀戰法】FastAPI Router — 股票相關係數查詢 API

Endpoints:
    GET /api/v1/correlation/spread?stock_a=2330&stock_b=2317&days=60
    GET /api/v1/correlation/meta/info
    GET /api/v1/correlation/{stock_id}?top_n=10

注意：固定路由 (spread, meta) 必須在 {stock_id} 路由之前定義，
      否則 FastAPI 會將 'spread' 字串當成 stock_id 參數捕捉。
"""

import sqlite3
import pandas as pd
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

# ── 路徑設定 ───────────────────────────────────────────────
root_path = Path(__file__).parent.parent.parent.parent.absolute()
CORR_DB = root_path / "databases" / "db_correlation.db"
PRICE_DB = root_path / "databases" / "db_technical_prices.db"


def _get_corr_conn() -> sqlite3.Connection:
    """取得相關係數 DB 連線（唯讀）"""
    if not CORR_DB.exists():
        raise HTTPException(
            status_code=503,
            detail="相關係數資料庫尚未建立，請先執行 databases/build_correlation_db.py"
        )
    return sqlite3.connect(str(CORR_DB), check_same_thread=False)


def _get_stock_name(stock_id: str) -> str:
    """從股票基本資料表查詢股票名稱"""
    try:
        with sqlite3.connect(str(PRICE_DB), check_same_thread=False) as conn:
            cursor = conn.execute(
                "SELECT name FROM stock_info WHERE stock_id = ?", [stock_id]
            )
            row = cursor.fetchone()
            return row[0] if row else stock_id
    except Exception:
        return stock_id


# ═══════════════════════════════════════════════════════════
# [1] 配對走勢比較 — 必須在 /{stock_id} 之前定義！
# ═══════════════════════════════════════════════════════════

@router.get("/api/v1/correlation/spread")
def get_price_spread(
    stock_a: str = Query(..., description="主股代號，如 2330"),
    stock_b: str = Query(..., description="配對股代號，如 2317"),
    days: int = Query(default=60, ge=20, le=250, description="回溯交易日天數"),
    recent_days: int = Query(default=10, ge=5, le=30, description="近期均值計算天數")
):
    """
    配對交易分析：計算兩支股票過去 N 個交易日的收盤價比值序列。
    回傳比值序列、完整 N 日均值、最近 recent_days 天均值，供前端識別走勢分歧。
    """
    sid_a = stock_a.strip().upper()
    sid_b = stock_b.strip().upper()

    if sid_a == sid_b:
        raise HTTPException(status_code=400, detail="請輸入不同的兩支股票")

    if not PRICE_DB.exists():
        raise HTTPException(status_code=503, detail="股價資料庫不存在")

    try:
        conn = sqlite3.connect(str(PRICE_DB), check_same_thread=False)
        # 取近 180 個日曆日的資料，再截取最後 days 個交易日
        query = """
            SELECT stock_id, date, close
            FROM daily_price
            WHERE stock_id IN (?, ?)
              AND date >= date('now', '-180 days')
              AND close IS NOT NULL
            ORDER BY date ASC
        """
        df_raw = pd.read_sql(query, conn, params=[sid_a, sid_b])
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"資料庫讀取失敗: {e}")

    if df_raw.empty:
        raise HTTPException(status_code=404, detail="找不到兩支股票的價格資料")

    # 轉成 pivot：index=日期, columns=股票代號
    df_pivot = df_raw.pivot_table(index="date", columns="stock_id", values="close", aggfunc="last")
    df_pivot.index = pd.to_datetime(df_pivot.index)
    df_pivot = df_pivot.sort_index()

    # 確認兩支股票都有資料
    missing = [s for s in [sid_a, sid_b] if s not in df_pivot.columns]
    if missing:
        names = ", ".join(missing)
        raise HTTPException(status_code=404, detail=f"找不到 {names} 的價格資料，請確認代號")

    # 只保留兩支股票都有收盤價的日期，取最後 days 天
    df_pair = df_pivot[[sid_a, sid_b]].dropna().tail(days)

    if len(df_pair) < max(recent_days, 10):
        raise HTTPException(status_code=400, detail=f"有效共同交易日不足 {days} 天，請縮小 days 參數")

    # 計算收盤價比值 ratio = A / B
    df_pair = df_pair.copy()
    df_pair["ratio"] = df_pair[sid_a] / df_pair[sid_b]

    # 均值計算
    ratio_mean_full = float(df_pair["ratio"].mean())
    ratio_std_full = float(df_pair["ratio"].std())     # 計算標準差
    ratio_mean_recent = float(df_pair["ratio"].tail(recent_days).mean())

    # 為了避免除以零（理論上股價比值標準差極少為零）
    if ratio_std_full == 0:
        ratio_std_full = 1e-9

    # 組裝序列（前端繪圖用）
    series = []
    for date_idx, row in df_pair.iterrows():
        r = float(row["ratio"])
        z_score = (r - ratio_mean_full) / ratio_std_full  # 計算 Z-Score
        
        series.append({
            "date": str(date_idx.date()),
            "close_a": round(float(row[sid_a]), 2),
            "close_b": round(float(row[sid_b]), 2),
            "ratio": round(r, 4),
            "z_score": round(z_score, 2),
            "above_mean": r > ratio_mean_full,
            "above_recent": r > ratio_mean_recent,
        })

    return {
        "stock_a": sid_a,
        "stock_a_name": _get_stock_name(sid_a),
        "stock_b": sid_b,
        "stock_b_name": _get_stock_name(sid_b),
        "days": len(series),
        "recent_days": recent_days,
        "ratio_mean_full": round(ratio_mean_full, 4),
        "ratio_std_full": round(ratio_std_full, 4),        # 新增標準差
        "ratio_mean_recent": round(ratio_mean_recent, 4),
        "series": series
    }


# ═══════════════════════════════════════════════════════════
# [2] DB 狀態查詢 — 同樣需在 /{stock_id} 之前
# ═══════════════════════════════════════════════════════════

@router.get("/api/v1/correlation/meta/info")
def get_correlation_meta():
    """
    查詢相關係數資料庫狀態（最後計算日期、股票數量）
    """
    conn = _get_corr_conn()
    try:
        cursor = conn.execute("SELECT key, value FROM meta")
        meta = {row[0]: row[1] for row in cursor.fetchall()}
    finally:
        conn.close()

    return {
        "last_calc_date": meta.get("last_calc_date", "未知"),
        "stock_count": int(meta.get("stock_count", 0)),
        "db_path": str(CORR_DB)
    }


# ═══════════════════════════════════════════════════════════
# [3] 相關係數排行 — 路徑參數路由放最後
# ═══════════════════════════════════════════════════════════

@router.get("/api/v1/correlation/{stock_id}")
def get_top_correlations(
    stock_id: str,
    top_n: int = Query(default=10, ge=1, le=50, description="回傳前 N 名，最多 50")
):
    """
    查詢與指定股票相關係數最高的前 N 支股票。

    - **stock_id**: 股票代號（純數字，例如 2330）
    - **top_n**: 回傳筆數，預設 10，最多 50
    """
    sid = stock_id.strip().upper()

    conn = _get_corr_conn()
    try:
        cursor = conn.execute(
            """
            SELECT peer_id, correlation, calc_date
            FROM top_correlations
            WHERE stock_id = ?
            ORDER BY correlation DESC
            LIMIT ?
            """,
            [sid, top_n]
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"找不到股票 {sid} 的相關係數資料，請確認代號是否正確，或資料庫尚未更新"
        )

    stock_name = _get_stock_name(sid)
    calc_date = rows[0][2] if rows else None

    # ── 新增：批次計算這 N 對股票的最新 Z-Score ──
    peer_ids = [r[0] for r in rows]
    all_sids = [sid] + peer_ids
    z_scores = {}
    
    try:
        if PRICE_DB.exists():
            with sqlite3.connect(str(PRICE_DB), check_same_thread=False) as conn_price:
                marks = ",".join(["?"] * len(all_sids))
                query = f"""
                    SELECT stock_id, date, close
                    FROM daily_price
                    WHERE stock_id IN ({marks})
                      AND date >= date('now', '-180 days')
                      AND close IS NOT NULL
                    ORDER BY date ASC
                """
                df_raw = pd.read_sql(query, conn_price, params=all_sids)
                if not df_raw.empty:
                    df_pivot = df_raw.pivot_table(index="date", columns="stock_id", values="close", aggfunc="last")
                    df_pivot = df_pivot.tail(60) # 近 60 交易日
                    
                    if sid in df_pivot.columns:
                        for p_id in peer_ids:
                            if p_id in df_pivot.columns:
                                df_pair = df_pivot[[sid, p_id]].dropna()
                                if len(df_pair) > 10: 
                                    ratio = df_pair[sid] / df_pair[p_id]
                                    mean = ratio.mean()
                                    std = ratio.std()
                                    if std == 0: std = 1e-9
                                    latest_r = ratio.iloc[-1]
                                    z_scores[p_id] = round(float((latest_r - mean) / std), 2)
    except Exception as e:
        print(f"[Warn] Z-Score calculation passed: {e}")

    results = []
    for rank, (peer_id, corr_val, _) in enumerate(rows, start=1):
        peer_name = _get_stock_name(peer_id)
        results.append({
            "rank": rank,
            "peer_id": peer_id,
            "peer_name": peer_name,
            "correlation": round(corr_val, 4),
            "current_z_score": z_scores.get(peer_id)  # 可能為 None
        })

    return {
        "stock_id": sid,
        "stock_name": stock_name,
        "calc_date": calc_date,
        "lookback_days": 60,
        "results": results
    }
