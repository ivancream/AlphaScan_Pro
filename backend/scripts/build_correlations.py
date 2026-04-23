"""
build_correlations.py — 雙刀戰法配對：Pearson 初篩 + 收盤價比值 ADF + 半衰期。

流程：
  1. 以報酬 Pearson 相關係數挑出每檔股票 Top-N 候選（省運算）。
  2. 對候選計算收盤價比值 Ratio = close_A / close_B，對 Ratio 做 ADF 檢定；
     p < 0.05 視為比值序列平穩（具均值回歸意涵），才寫入資料庫。
  3. 通過 ADF 後，以 OU 一階離散近似迴歸估計半衰期；斜率 ≥ 0、非有限值
     或半衰期 > 250 交易日者，half_life 存為 NULL（配對仍保留）。

Run standalone:
    python -m backend.scripts.build_correlations

Called by scheduler.py every Saturday 03:00.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, coint

from backend import settings
from backend.db.connection import init_duckdb
from backend.db import queries, writer
from backend.db.writer import log_update_error


LOOKBACK_DAYS = 252  # ~1 trading year
MIN_OVERLAP = 60  # minimum shared trading days required
TOP_N_PEERS = 50  # Pearson 初篩候選數（每檔股票）
ADF_ALPHA = 0.05  # ADF 顯著水準：拒絕單根假設 → 比值近似平穩
MAX_HALF_LIFE_DAYS = 250.0  # 半衰期過長則不採用數值（寫 NULL）
# 台股 1 張 = 1000 股；日均量門檻 500 張
MIN_AVG_VOLUME_SHARES = 500 * 1000
EG_ALPHA = 0.05  # Engle-Granger 顯著水準


def _count_mean_crossings(ratio: np.ndarray, ratio_mean: float) -> int:
    """計算 Ratio 穿越均值次數（上穿 + 下穿）。"""
    if ratio.size < 2 or not np.isfinite(ratio_mean):
        return 0
    centered = ratio - ratio_mean
    sign = np.sign(centered)
    if np.all(sign == 0):
        return 0

    # 將剛好等於均值（sign=0）的點補成鄰近方向，避免漏算穿越
    sign = sign.astype(float)
    for i in range(1, sign.size):
        if sign[i] == 0:
            sign[i] = sign[i - 1]
    for i in range(sign.size - 2, -1, -1):
        if sign[i] == 0:
            sign[i] = sign[i + 1]
    return int(np.sum(sign[1:] * sign[:-1] < 0))


def _calc_hedge_ratio(price_a: np.ndarray, price_b: np.ndarray) -> Optional[float]:
    """
    用 OLS 近似估計對沖比例（hedge ratio）。
    模型：log(Price_A) = α + β * log(Price_B)，取 β 作為 hedge_ratio。
    """
    try:
        a = np.asarray(price_a, dtype=float).ravel()
        b = np.asarray(price_b, dtype=float).ravel()
        if a.size < MIN_OVERLAP or b.size < MIN_OVERLAP:
            return None
        if np.any(a <= 0) or np.any(b <= 0):
            return None
        la = np.log(a)
        lb = np.log(b)
        mask = np.isfinite(la) & np.isfinite(lb)
        la = la[mask]
        lb = lb[mask]
        if la.size < MIN_OVERLAP:
            return None
        var_b = float(np.var(lb))
        if not np.isfinite(var_b) or var_b < 1e-18:
            return None
        beta = float(np.polyfit(lb, la, 1)[0])
        if not np.isfinite(beta) or abs(beta) > 100:
            return None
        return beta
    except Exception:
        return None


def _calc_eg_pvalue(price_a: np.ndarray, price_b: np.ndarray) -> Optional[float]:
    """
    Engle-Granger 協整檢定（coint），回傳 p-value。
    僅當 p < EG_ALPHA 時視為通過第二層協整濾網。
    """
    try:
        a = np.asarray(price_a, dtype=float).ravel()
        b = np.asarray(price_b, dtype=float).ravel()
        if a.size < MIN_OVERLAP or b.size < MIN_OVERLAP:
            return None
        if np.any(a <= 0) or np.any(b <= 0):
            return None
        la = np.log(a)
        lb = np.log(b)
        mask = np.isfinite(la) & np.isfinite(lb)
        la = la[mask]
        lb = lb[mask]
        if la.size < MIN_OVERLAP:
            return None
        p_val = float(coint(la, lb)[1])
        if not np.isfinite(p_val):
            return None
        return p_val
    except Exception:
        return None


def _calc_composite_score(correlation: float, half_life: Optional[float], zero_crossings: int) -> float:
    """
    綜合分數（0~100）：
      - zero_crossings: 越高越好（震盪次數，代表可交易頻率）
      - half_life: 越短越好（收斂速度）
      - correlation: 越高適度加分（避免過度依賴單一指標）
    """
    zc = max(0.0, float(zero_crossings))
    corr = float(np.clip(correlation, -1.0, 1.0))

    # 上限裁切避免極端值主導分數；>=40 次視為高分區
    zc_norm = float(np.clip(zc / 40.0, 0.0, 1.0))

    # 半衰期 1~120 天內線性映射；越短分數越高
    if half_life is None or not np.isfinite(half_life):
        hl_norm = 0.0
    else:
        hl_clip = float(np.clip(half_life, 1.0, 120.0))
        hl_norm = 1.0 - (hl_clip - 1.0) / 119.0

    # 只對正相關給加分（0~1）
    corr_norm = max(0.0, corr)

    w_cross = max(0.0, float(settings.CORR_WEIGHT_CROSSINGS))
    w_half = max(0.0, float(settings.CORR_WEIGHT_HALFLIFE))
    w_pearson = max(0.0, float(settings.CORR_WEIGHT_PEARSON))
    w_sum = w_cross + w_half + w_pearson
    if w_sum <= 1e-12:
        w_cross, w_half, w_pearson = 0.50, 0.35, 0.15
        w_sum = 1.0
    # 權重正規化：即使 .env 設定總和不為 1，也能維持穩定分數區間
    w_cross /= w_sum
    w_half /= w_sum
    w_pearson /= w_sum

    score = 100.0 * (w_cross * zc_norm + w_half * hl_norm + w_pearson * corr_norm)
    return float(np.clip(score, 0.0, 100.0))


def _adf_pvalue_half_life_and_ratio_stats(
    ratio: np.ndarray,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[int]]:
    """
    對價格比值序列做 ADF，並用 Δratio ~ ratio_{t-1} 斜率 λ 估計半衰期。

    半衰期公式：Half-Life = -ln(2) / λ（需 λ < 0）。
    回傳 (adf_p_value, half_life, ratio_mean, ratio_std, zero_crossings)；
    ADF 未通過時回傳全 None 表示應捨棄該配對。
    """
    try:
        r = np.asarray(ratio, dtype=float).ravel()
        if r.size < MIN_OVERLAP or np.any(~np.isfinite(r)):
            return None, None, None, None, None
        # 極端比值（除零殘留、異常飆股）直接略過
        if np.any(np.abs(r) > 1e6) or np.nanstd(r) < 1e-12:
            return None, None, None, None, None

        # ADF：單根假設下 p 越小越支持平穩（與協整檢定第一步概念一致）
        adf_res = adfuller(r, autolag="AIC")
        p_val = float(adf_res[1])
        if not np.isfinite(p_val) or p_val >= ADF_ALPHA:
            return None, None, None, None, None

        ratio_mean = float(np.mean(r))
        ratio_std = float(np.std(r, ddof=1))
        if not np.isfinite(ratio_mean):
            return None, None, None, None, None
        if not np.isfinite(ratio_std) or ratio_std <= 1e-12:
            ratio_std = None
        zero_crossings = _count_mean_crossings(r, ratio_mean)

        x = r[:-1]
        y = np.diff(r)
        mask = np.isfinite(x) & np.isfinite(y)
        x = x[mask]
        y = y[mask]
        if x.size < 10:
            return p_val, None, ratio_mean, ratio_std, zero_crossings

        var_x = float(np.var(x))
        if var_x < 1e-18 or not np.isfinite(var_x):
            return p_val, None, ratio_mean, ratio_std, zero_crossings

        lam = float(np.polyfit(x, y, 1)[0])
        if not np.isfinite(lam) or lam >= 0:
            return p_val, None, ratio_mean, ratio_std, zero_crossings

        hl = -np.log(2.0) / lam
        if not np.isfinite(hl) or hl <= 0 or hl > MAX_HALF_LIFE_DAYS:
            return p_val, None, ratio_mean, ratio_std, zero_crossings

        return p_val, float(hl), ratio_mean, ratio_std, zero_crossings
    except Exception:
        return None, None, None, None, None


def _screen_pair(
    df_pivot: pd.DataFrame, stock_id: str, peer_id: str
) -> Tuple[
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[int],
    Optional[float],
]:
    """對齊兩檔收盤價、取最近 LOOKBACK_DAYS，計算 ADF/EG/半衰期/比值統計/hedge ratio。"""
    try:
        pair = df_pivot[[stock_id, peer_id]].dropna(how="any")
        if len(pair) < MIN_OVERLAP:
            return None, None, None, None, None, None, None
        pair = pair.iloc[-LOOKBACK_DAYS:]
        ca = pair[stock_id].to_numpy(dtype=float, copy=False)
        cb = pair[peer_id].to_numpy(dtype=float, copy=False)
        if np.any(cb == 0) or np.any(~np.isfinite(ca)) or np.any(~np.isfinite(cb)):
            return None, None, None, None, None, None, None
        ratio = ca / cb
        p_adf, hl, ratio_mean, ratio_std, zero_crossings = _adf_pvalue_half_life_and_ratio_stats(ratio)
        if p_adf is None:
            return None, None, None, None, None, None, None
        eg_p = _calc_eg_pvalue(ca, cb)
        if eg_p is None or eg_p >= EG_ALPHA:
            return None, None, None, None, None, None, None
        hedge_ratio = _calc_hedge_ratio(ca, cb)
        return p_adf, eg_p, hl, ratio_mean, ratio_std, zero_crossings, hedge_ratio
    except Exception:
        return None, None, None, None, None, None, None


def run_correlation_build() -> None:
    print("[CorrelationBuild] Starting …")
    init_duckdb()
    try:
        print("[CorrelationBuild] Loading price data …")
        df_all = queries.get_price_df_all(cutoff_days=LOOKBACK_DAYS + 30)

        if df_all.empty:
            print("[CorrelationBuild] No price data. Aborting.")
            return

        # 與 API 查詢一致：代號一律字串，避免 pivot 欄位混用 int/str 導致選欄失敗卻被內層 except 吞掉
        df_all = df_all.copy()
        df_all["stock_id"] = df_all["stock_id"].astype(str).str.strip()

        # 流動性過濾：最近 LOOKBACK_DAYS 日均量需達門檻，避免冷門股配對不可交易
        df_liq = df_all.sort_values(["stock_id", "date"]).groupby("stock_id", group_keys=False).tail(LOOKBACK_DAYS)
        vol_stats = (
            df_liq.groupby("stock_id")["volume"]
            .mean()
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
        )
        liquid_ids = vol_stats[vol_stats >= MIN_AVG_VOLUME_SHARES].index
        df_all = df_all[df_all["stock_id"].isin(liquid_ids)]
        print(
            f"[CorrelationBuild] {len(liquid_ids)} stocks with avg volume >= {MIN_AVG_VOLUME_SHARES:,} shares"
        )
        if df_all.empty:
            print("[CorrelationBuild] No liquid stocks after volume filter. Aborting.")
            return

        df_pivot = df_all.pivot_table(
            index="date", columns="stock_id", values="close", aggfunc="last"
        )
        df_pivot = df_pivot.sort_index()

        valid_cols = df_pivot.columns[df_pivot.count() >= MIN_OVERLAP]
        df_pivot = df_pivot[valid_cols]
        print(f"[CorrelationBuild] {len(valid_cols)} stocks with >={MIN_OVERLAP} days data")

        returns = np.log(df_pivot / df_pivot.shift(1)).dropna(how="all")
        print("[CorrelationBuild] Computing Pearson correlation matrix …")
        corr_matrix = returns.corr()

        rows: List[Dict[str, Any]] = []
        calc_date = datetime.date.today().isoformat()
        stocks = list(corr_matrix.columns)

        print("[CorrelationBuild] ADF + EG screening and scoring on Top-N candidates …")
        for stock_id in stocks:
            sid = str(stock_id).strip()
            col = corr_matrix[sid].drop(labels=[sid], errors="ignore")
            col = col.dropna()
            if col.empty:
                continue
            top = col.nlargest(TOP_N_PEERS)
            for peer_id, corr_val in top.items():
                peer_id = str(peer_id).strip()
                try:
                    p_adf, p_eg, hl, ratio_mean, ratio_std, zero_crossings, hedge_ratio = _screen_pair(
                        df_pivot, sid, peer_id
                    )
                    if p_adf is None or p_eg is None:
                        continue
                    composite_score = _calc_composite_score(float(corr_val), hl, int(zero_crossings or 0))
                    rows.append(
                        {
                            "stock_id": sid,
                            "peer_id": peer_id,
                            "correlation": round(float(corr_val), 6),
                            "adf_p_value": round(float(p_adf), 8),
                            "eg_p_value": round(float(p_eg), 8),
                            "half_life": (round(float(hl), 4) if hl is not None else None),
                            "ratio_mean": round(float(ratio_mean), 8) if ratio_mean is not None else None,
                            "ratio_std": round(float(ratio_std), 8) if ratio_std is not None else None,
                            "zero_crossings": int(zero_crossings) if zero_crossings is not None else 0,
                            "hedge_ratio": round(float(hedge_ratio), 6) if hedge_ratio is not None else None,
                            "composite_score": round(float(composite_score), 4),
                        }
                    )
                except Exception:
                    continue

        df_out = pd.DataFrame(rows)
        n = writer.upsert_correlations(df_out, calc_date)
        if n == 0:
            print(
                f"[CorrelationBuild] Done. No pairs passed ADF; table cleared (calc_date={calc_date})."
            )
        else:
            print(f"[CorrelationBuild] Done. {n} pairs stored (calc_date={calc_date}).")
    except Exception as exc:
        log_update_error("correlations", str(exc))
        print(f"[CorrelationBuild] Error: {exc}")
        raise


if __name__ == "__main__":
    run_correlation_build()
