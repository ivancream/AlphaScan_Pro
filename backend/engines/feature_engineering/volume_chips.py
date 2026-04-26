"""
Volume resonance and chips microstructure feature engineering.

Expected input columns:
- symbol, date
- close, volume
- investment_trust_buy, investment_trust_sell
- total_shares_outstanding
- institutional_net_flow (for orthogonalized flow)
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "symbol" not in out.columns or "date" not in out.columns:
        raise ValueError("Input DataFrame must contain 'symbol' and 'date' columns")
    out["symbol"] = out["symbol"].astype(str)
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values(["symbol", "date"]).reset_index(drop=True)
    return out


def calculate_volume_zscore(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    Volume anomaly Z-score:
    (Volume - RollingMean(Volume)) / RollingStd(Volume)
    """
    out = _prepare(df)
    if "volume" not in out.columns:
        raise ValueError("Input DataFrame must contain 'volume' column")
    w = int(window)
    grp = out.groupby("symbol", group_keys=False, sort=False)["volume"]
    out[f"vol_ma_{w}"] = grp.transform(
        lambda s: pd.to_numeric(s, errors="coerce").rolling(w, min_periods=w).mean()
    )
    out[f"vol_std_{w}"] = grp.transform(
        lambda s: pd.to_numeric(s, errors="coerce").rolling(w, min_periods=w).std()
    )
    out[f"volume_zscore_{w}"] = (
        (pd.to_numeric(out["volume"], errors="coerce") - out[f"vol_ma_{w}"])
        / out[f"vol_std_{w}"]
    )
    return out


def _rolling_spearman_from_rank(
    rank_x: pd.Series, rank_y: pd.Series, window: int
) -> pd.Series:
    """
    Compute rolling Spearman correlation from pre-ranked series.
    Spearman(x, y) == Pearson(rank(x), rank(y))
    """
    out = pd.Series(np.nan, index=rank_x.index, dtype="float64")
    n = len(rank_x)
    for i in range(window - 1, n):
        sx = rank_x.iloc[i - window + 1 : i + 1]
        sy = rank_y.iloc[i - window + 1 : i + 1]
        # need enough non-null pairs
        mask = sx.notna() & sy.notna()
        if mask.sum() < 3:
            continue
        xv = sx[mask].to_numpy(dtype=float)
        yv = sy[mask].to_numpy(dtype=float)
        if np.std(xv) == 0 or np.std(yv) == 0:
            continue
        out.iloc[i] = float(np.corrcoef(xv, yv)[0, 1])
    return out


def calculate_price_volume_corr(df: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """
    Rolling Spearman rank correlation between:
    - daily return ranks
    - daily volume ranks
    """
    out = _prepare(df)
    if "close" not in out.columns or "volume" not in out.columns:
        raise ValueError("Input DataFrame must contain 'close' and 'volume' columns")
    w = int(window)

    grp = out.groupby("symbol", group_keys=False, sort=False)
    out["ret_1d"] = grp["close"].transform(
        lambda s: pd.to_numeric(s, errors="coerce").pct_change(1)
    )
    out["ret_rank"] = grp["ret_1d"].transform(lambda s: s.rank(method="average"))
    out["vol_rank"] = grp["volume"].transform(
        lambda s: pd.to_numeric(s, errors="coerce").rank(method="average")
    )

    out[f"price_volume_spearman_{w}"] = (
        grp[["ret_rank", "vol_rank"]]
        .apply(
            lambda g: _rolling_spearman_from_rank(
                g["ret_rank"], g["vol_rank"], window=w
            )
        )
        .reset_index(level=0, drop=True)
    )
    return out


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()
    vals = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    out = np.full(len(vals), np.nan, dtype=float)

    for i in range(window - 1, len(vals)):
        y = vals[i - window + 1 : i + 1]
        if np.isnan(y).any():
            continue
        y_mean = y.mean()
        out[i] = float(((x - x_mean) * (y - y_mean)).sum() / denom)
    return pd.Series(out, index=series.index)


def calculate_obv_slope(df: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """
    OBV and rolling linear-regression slope of OBV.
    """
    out = _prepare(df)
    if "close" not in out.columns or "volume" not in out.columns:
        raise ValueError("Input DataFrame must contain 'close' and 'volume' columns")
    w = int(window)

    grp = out.groupby("symbol", group_keys=False, sort=False)
    close_num = pd.to_numeric(out["close"], errors="coerce")
    vol_num = pd.to_numeric(out["volume"], errors="coerce").fillna(0.0)

    out["close_diff_1d"] = grp["close"].transform(
        lambda s: pd.to_numeric(s, errors="coerce").diff()
    )
    direction = np.where(out["close_diff_1d"] > 0, 1, np.where(out["close_diff_1d"] < 0, -1, 0))
    out["obv"] = (vol_num * direction).groupby(out["symbol"]).cumsum()
    out[f"obv_slope_{w}"] = grp["obv"].transform(lambda s: _rolling_slope(s, w))

    # keep explicit numeric close reference in output consistency
    out["close"] = close_num
    return out


def calculate_trust_penetration(df: pd.DataFrame) -> pd.DataFrame:
    """
    Trust penetration ratio:
    - 5-day net buy by investment trust / total shares outstanding
    """
    import warnings

    out = _prepare(df)
    required = {"investment_trust_buy", "investment_trust_sell", "total_shares_outstanding"}
    missing = required - set(out.columns)
    if missing:
        raise ValueError(f"Input DataFrame missing required columns: {sorted(missing)}")

    buy = pd.to_numeric(out["investment_trust_buy"], errors="coerce").fillna(0.0)
    sell = pd.to_numeric(out["investment_trust_sell"], errors="coerce").fillna(0.0)
    tso = pd.to_numeric(out["total_shares_outstanding"], errors="coerce")

    out["trust_net_flow"] = buy - sell
    if tso.notna().sum() == 0:
        warnings.warn(
            "total_shares_outstanding 全為缺失：trust_penetration_5d 將為 NaN。",
            UserWarning,
            stacklevel=2,
        )
        out["trust_net_flow_5d"] = np.nan
        out["trust_penetration_5d"] = np.nan
        return out

    out["trust_net_flow_5d"] = out.groupby("symbol", group_keys=False, sort=False)[
        "trust_net_flow"
    ].transform(lambda s: s.rolling(5, min_periods=5).sum())
    out["trust_penetration_5d"] = out["trust_net_flow_5d"] / tso
    return out


def calculate_orthogonalized_flow(
    df: pd.DataFrame,
    market_df: pd.DataFrame,
    stock_flow_col: str = "institutional_net_flow",
    market_flow_col: str = "market_institutional_net_flow",
    rolling_window: Optional[int] = 60,
) -> pd.DataFrame:
    """
    Orthogonalized institutional flow residuals.

    Regress each stock's net flow against market-wide net flow:
      y_t = alpha + beta * x_t + e_t
    Return residual e_t as abnormal flow.

    If rolling_window is provided, use rolling OLS-style beta/alpha estimates;
    otherwise use full-sample per-symbol regression.
    """
    out = _prepare(df)
    if stock_flow_col not in out.columns:
        raise ValueError(f"Input DataFrame must contain '{stock_flow_col}' column")
    if "date" not in market_df.columns or market_flow_col not in market_df.columns:
        raise ValueError(
            f"market_df must contain 'date' and '{market_flow_col}' columns"
        )

    mkt = market_df.copy()
    mkt["date"] = pd.to_datetime(mkt["date"])
    mkt = mkt[["date", market_flow_col]].drop_duplicates(subset=["date"])
    mkt[market_flow_col] = pd.to_numeric(mkt[market_flow_col], errors="coerce")

    out = out.merge(mkt, on="date", how="left")
    out[stock_flow_col] = pd.to_numeric(out[stock_flow_col], errors="coerce")

    def _full_sample_residual(g: pd.DataFrame) -> pd.Series:
        x = g[market_flow_col]
        y = g[stock_flow_col]
        valid = x.notna() & y.notna()
        res = pd.Series(np.nan, index=g.index, dtype="float64")
        if valid.sum() < 3:
            return res
        xv = x[valid].to_numpy(dtype=float)
        yv = y[valid].to_numpy(dtype=float)
        x_mean = xv.mean()
        y_mean = yv.mean()
        denom = ((xv - x_mean) ** 2).sum()
        if denom == 0:
            return res
        beta = ((xv - x_mean) * (yv - y_mean)).sum() / denom
        alpha = y_mean - beta * x_mean
        fitted = alpha + beta * x
        res.loc[valid.index] = y - fitted
        return res

    def _rolling_residual(g: pd.DataFrame, w: int) -> pd.Series:
        x = g[market_flow_col].to_numpy(dtype=float)
        y = g[stock_flow_col].to_numpy(dtype=float)
        out_res = np.full(len(g), np.nan, dtype=float)
        for i in range(w - 1, len(g)):
            xs = x[i - w + 1 : i + 1]
            ys = y[i - w + 1 : i + 1]
            if np.isnan(xs).any() or np.isnan(ys).any():
                continue
            xm = xs.mean()
            ym = ys.mean()
            denom = ((xs - xm) ** 2).sum()
            if denom == 0:
                continue
            beta = ((xs - xm) * (ys - ym)).sum() / denom
            alpha = ym - beta * xm
            out_res[i] = y[i] - (alpha + beta * x[i])
        return pd.Series(out_res, index=g.index)

    grp = out.groupby("symbol", group_keys=False, sort=False)
    if rolling_window and int(rolling_window) > 1:
        w = int(rolling_window)
        out["orthogonalized_flow_residual"] = grp.apply(
            lambda g: _rolling_residual(g, w)
        ).reset_index(level=0, drop=True)
    else:
        out["orthogonalized_flow_residual"] = grp.apply(_full_sample_residual).reset_index(
            level=0, drop=True
        )

    return out
