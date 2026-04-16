from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import pandas as pd
import os
import datetime

from backend.engines.cache_store import StaticCache, TTL_12H

_CACHE_CONTROL = f"public, max-age={TTL_12H}, stale-while-revalidate=600"

from backend.engines.cb_crawler import (
    CBDB, update_cb_info, update_cb_daily, update_stock_fundamentals,
    get_cb_with_latest_price, get_cb_history,
    calc_arbitrage, calc_premium, calc_ytp
)
from backend.db import queries as _db_queries
from backend.db.connection import duck_read

router = APIRouter()


class _MarketDBCompat:
    """Lightweight shim replacing the deleted core.market_db.MarketDB."""

    @property
    def conn(self):
        raise AttributeError(
            "_MarketDBCompat has no .conn — use duck_read() directly"
        )

    def get_stock_data(self, stock_id: str, period: str = "1y") -> pd.DataFrame:
        df = _db_queries.get_price_df(str(stock_id).strip(), period)
        if df.empty:
            return df
        df = df.rename(columns={"date": "Date"})
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date")
        return df

    def get_stock_name(self, stock_id: str) -> str:
        return _db_queries.get_stock_name(str(stock_id).strip())


def get_cbdb():
    return CBDB()

def get_mdb():
    return _MarketDBCompat()

def _days_to_maturity(maturity_date_str: Optional[str]) -> Optional[int]:
    if not maturity_date_str:
        return None
    try:
        mat = datetime.date.fromisoformat(maturity_date_str[:10])
        return (mat - datetime.date.today()).days
    except Exception:
        return None

def _enrich_df(df: pd.DataFrame, mdb: _MarketDBCompat) -> pd.DataFrame:
    if df.empty:
        return df

    stock_prices = {}
    for sid in df["stock_id"].dropna().unique():
        sd = mdb.get_stock_data(str(sid))
        if not sd.empty:
            stock_prices[sid] = sd["close"].iloc[-1]

    def arb(row):
        sp = stock_prices.get(row["stock_id"])
        if sp is None or not row["conv_price"] or not row["cb_close"]:
            return None
        return calc_arbitrage(row["cb_close"], sp, row["conv_price"])

    def prem(row):
        sp = stock_prices.get(row["stock_id"])
        if sp is None or not row["conv_price"] or not row["cb_close"]:
            return None
        return calc_premium(row["cb_close"], sp, row["conv_price"])

    def ytp(row):
        if not row["cb_close"] or not pd.notna(row.get("put_price")) or not pd.notna(row.get("put_date")):
            return None
        return calc_ytp(row["cb_close"], row["put_price"], row["put_date"])

    df = df.copy()
    df["stock_price"] = df["stock_id"].map(stock_prices)
    df["arb_pct"]     = df.apply(arb, axis=1)
    df["premium_pct"] = df.apply(prem, axis=1)
    df["ytp_pct"]     = df.apply(ytp, axis=1)
    df["days_left"]   = df["maturity_date"].apply(_days_to_maturity)
    df["put_days_left"] = df["put_date"].apply(_days_to_maturity)
    df["secured_label"] = df["is_secured"].map({0: "無", 1: "有"})
    
    try:
        with duck_read() as conn:
            tdcc_df = conn.execute("""
                SELECT stock_id, whale_1000_pct AS large_holders_pct, total_holders
                FROM tdcc_distribution
                WHERE date = (SELECT MAX(date) FROM tdcc_distribution)
            """).df()
        tdcc_large = tdcc_df.set_index("stock_id")["large_holders_pct"].to_dict()
        tdcc_total = tdcc_df.set_index("stock_id")["total_holders"].to_dict()
    except Exception:
        tdcc_large = {}
        tdcc_total = {}
        
    df["tdcc_large_pct"] = df["stock_id"].map(tdcc_large)
    df["tdcc_total"]     = df["stock_id"].map(tdcc_total)
    
    def calc_mkt_val(row):
        return None
        
    df["mkt_value"] = df.apply(calc_mkt_val, axis=1)
    
    return df

@router.get("/api/v1/cb/scan")
async def get_cb_scan(
    response: Response,
    ytp_min: float = 3.0,
    debt_max: float = 80.0,
    arb_max: float = 0.0,
    secured_only: str = "全部",
    days_max: int = 1095,
):
    """可轉債篩選掃描，結果快取 12 小時。"""
    key    = StaticCache.make_key("cb:scan",
        ytp_min=ytp_min, debt_max=debt_max,
        arb_max=arb_max, secured_only=secured_only, days_max=days_max)
    cached = StaticCache.get(key)
    if cached is not None:
        response.headers["Cache-Control"] = _CACHE_CONTROL
        response.headers["X-Cache"] = "HIT"
        return cached
    try:
        db = get_cbdb()
        mdb = get_mdb()
        df = get_cb_with_latest_price(db)
        if df.empty:
            return {"results": [], "total": 0, "message": "No data"}
            
        df = _enrich_df(df, mdb)
        
        numeric_cols = ["cb_close", "ytp_pct", "debt_ratio", "arb_pct", "put_days_left", "days_left"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        mask = pd.Series([True] * len(df))
        if df["ytp_pct"].notna().any(): mask &= df["ytp_pct"].fillna(-999) >= ytp_min
        if df["debt_ratio"].notna().any(): mask &= df["debt_ratio"].fillna(999) <= debt_max
        if df["arb_pct"].notna().any(): mask &= df["arb_pct"].fillna(0) <= arb_max

        if secured_only == "無擔保優先":
            df = df.sort_values("is_secured")
        elif secured_only == "僅無擔保":
            mask &= df["is_secured"] == 0
            
        if df["put_days_left"].notna().any():
            mask &= df["put_days_left"].fillna(df["days_left"]).fillna(9999) <= days_max

        df_show = df[mask].copy()
        if "ytp_pct" in df_show.columns and not df_show["ytp_pct"].isna().all():
            df_show = df_show.sort_values("ytp_pct", ascending=False)
        else:
            df_show = df_show.sort_values("cb_id")
            
        # Mock asks
        df_show["cb_ask"] = df_show["cb_close"] * 1.002
        df_show["ytp_ask_pct"] = df_show["ytp_pct"] - 0.2
        
        # Replace NaN with None for JSON responses
        df_show = df_show.where(pd.notnull(df_show), None)

        result = {
            "results": df_show.to_dict(orient="records"),
            "total": len(df),
            "filtered": len(df_show),
        }
        StaticCache.set(key, result, ttl=TTL_12H)
        response.headers["Cache-Control"] = _CACHE_CONTROL
        response.headers["X-Cache"] = "MISS"
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/cb/stats")
async def get_cb_stats(response: Response):
    """可轉債統計概覽，結果快取 12 小時。"""
    key    = "cb:stats"
    cached = StaticCache.get(key)
    if cached is not None:
        response.headers["Cache-Control"] = _CACHE_CONTROL
        response.headers["X-Cache"] = "HIT"
        return cached
    try:
        db = get_cbdb()
        mdb = get_mdb()
        df = get_cb_with_latest_price(db)
        if df.empty:
            return {}
            
        df = _enrich_df(df, mdb)
        
        total = len(df)
        unsecured_pct = (df['is_secured']==0).sum() / total * 100 if total > 0 else 0
        valid_arb = df["arb_pct"].dropna()
        avg_arb = valid_arb.mean() if len(valid_arb) > 0 else None
        high_premium_count = (df['premium_pct'].fillna(0) > 30).sum()
        
        # Premium hist
        prem_data = df["premium_pct"].dropna().tolist()
        
        # Vol top 10
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
        vol_df = df[df["volume"].notna()].nlargest(10, "volume")
        vol_top = vol_df[["cb_id", "name", "volume"]].to_dict(orient="records") if not vol_df.empty else []
        
        # Maturity quarters
        mat_df = df[df["maturity_date"].notna()].copy()
        mat_df["maturity_dt"] = pd.to_datetime(mat_df["maturity_date"], errors="coerce")
        mat_df = mat_df[mat_df["maturity_dt"].notna()]
        cutoff = pd.Timestamp.now() + pd.DateOffset(years=3)
        mat_df = mat_df[mat_df["maturity_dt"] <= cutoff]
        
        quarters = []
        if not mat_df.empty:
            mat_df["quarter"] = mat_df["maturity_dt"].dt.to_period("Q").astype(str)
            q_count = mat_df.groupby("quarter").size().reset_index(name="count")
            quarters = q_count.to_dict(orient="records")
            
        result = {
            "metrics": {
                "total": int(total),
                "unsecuredPct": round(unsecured_pct, 1),
                "avgArb": round(avg_arb, 1) if avg_arb is not None else None,
                "highPremiumCount": int(high_premium_count),
            },
            "premiumDist": prem_data,
            "volumeTop10": [{**c, "volume": float(c["volume"])} for c in vol_top],
            "maturityQuarters": quarters,
        }
        StaticCache.set(key, result, ttl=TTL_12H)
        response.headers["Cache-Control"] = _CACHE_CONTROL
        response.headers["X-Cache"] = "MISS"
        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v1/cb/cache")
async def clear_cb_cache():
    """手動清除所有可轉債快取（資料更新後呼叫）。"""
    n = StaticCache.invalidate_prefix("cb:")
    return {"message": f"已清除 {n} 筆可轉債快取"}
        
@router.get("/api/v1/cb/history/{cb_id}")
async def get_cb_hist(cb_id: str):
     try:
         db = get_cbdb()
         mdb = get_mdb()
         
         df_all = get_cb_with_latest_price(db)
         if df_all.empty: return {"history": [], "stockHistory": [], "info": {}}
         
         row = df_all[df_all["cb_id"] == cb_id]
         if row.empty: return {"history": [], "stockHistory": [], "info": {}}
         
         enriched = _enrich_df(row, mdb).iloc[0].where(pd.notnull(row), None).to_dict()
         
         cb_hist = get_cb_history(db, cb_id, days=90)
         
         stock_id = str(row.iloc[0].get("stock_id", ""))
         stock_hist = mdb.get_stock_data(stock_id).tail(90) if stock_id else pd.DataFrame()
         
         return {
             "info": enriched,
             "history": cb_hist.reset_index().to_dict(orient="records") if not cb_hist.empty else [],
             "stockHistory": stock_hist.reset_index().to_dict(orient="records") if not stock_hist.empty else [],
         }
     except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/v1/cb/reverse")
async def get_cb_reverse(min_arb: float = -10, min_cb_price: float = 100):
     try:
        db = get_cbdb()
        mdb = get_mdb()
        
        df = get_cb_with_latest_price(db)
        if df.empty: return []
        
        df = _enrich_df(df, mdb)
        df = df[df["cb_close"].notna() & df["arb_pct"].notna()].copy()
        
        if df.empty: return []
        
        agg = (
            df.groupby("stock_id")
            .agg(
                cb_count    = ("cb_id", "count"),
                avg_arb     = ("arb_pct", "mean"),
                min_arb     = ("arb_pct", "min"),
                total_vol   = ("volume", "sum"),
                avg_cb_price= ("cb_close", "mean"),
                name        = ("name", "first"),
                market      = ("market", "first"),
            )
            .reset_index()
        )
        agg["stock_name"] = agg["stock_id"].apply(lambda s: mdb.get_stock_name(s) if s else "")
        
        agg = agg[agg["avg_arb"] <= min_arb]
        agg = agg[agg["avg_cb_price"] >= min_cb_price]
        agg = agg.sort_values("avg_arb")
        
        agg = agg.where(pd.notnull(agg), None)
        return agg.to_dict(orient="records")
        
     except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/cb/by-stock/{stock_id}")
async def get_cb_by_stock(stock_id: str):
    try:
        db = get_cbdb()
        mdb = get_mdb()
        df = get_cb_with_latest_price(db)
        if df.empty:
            return {"stock_id": stock_id, "has_cb": False, "results": []}

        clean_id = str(stock_id).strip().upper().replace(".TW", "").replace(".TWO", "")
        df = df[df["stock_id"].astype(str).str.upper() == clean_id].copy()
        if df.empty:
            return {"stock_id": clean_id, "has_cb": False, "results": []}

        df = _enrich_df(df, mdb)
        df = df.where(pd.notnull(df), None)
        return {
            "stock_id": clean_id,
            "has_cb": True,
            "results": df.to_dict(orient="records"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
@router.post("/api/v1/cb/update")
async def update_cb_data(type: str = Query(...)):
    """Async data updater"""
    db = get_cbdb()
    if type == "basic":
        n = update_cb_info(db)
        n2 = update_cb_daily(db, days_back=5)
        return {"message": f"Updated {n} info rows and {n2} daily rows"}
    elif type == "fundamentals":
        n = update_stock_fundamentals(db)
        return {"message": f"Updated {n} fundamental rows"}
    else:
        raise HTTPException(status_code=400, detail="Invalid update type")
