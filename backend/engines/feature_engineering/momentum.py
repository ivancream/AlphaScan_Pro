"""
Momentum and relative-strength feature engineering utilities.

Expected input DataFrame columns:
- symbol: stock identifier
- date: trading date
- close: close price

All functions are vectorized with pandas groupby/transform operations.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import pandas as pd


REQUIRED_COLUMNS = {"symbol", "date", "close"}


def _validate_input(df: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Input DataFrame missing required columns: {sorted(missing)}")


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    _validate_input(df)
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["symbol"] = out["symbol"].astype(str)
    out = out.sort_values(["symbol", "date"]).reset_index(drop=True)
    return out


def calculate_rs_rank(df: pd.DataFrame, window: Sequence[int] = (20, 60)) -> pd.DataFrame:
    """
    Cross-sectional relative-strength rank (0~100 percentile by date).

    Steps:
    1. For each symbol, compute trailing return over each window.
    2. Within each date, rank all symbols and convert to percentile [0, 100].
    """
    out = _prepare(df)
    grp = out.groupby("symbol", group_keys=False, sort=False)

    for w in window:
        w_int = int(w)
        ret_col = f"ret_{w_int}d"
        rank_col = f"rs_rank_{w_int}d"
        out[ret_col] = grp["close"].pct_change(periods=w_int)
        out[rank_col] = (
            out.groupby("date", group_keys=False, sort=False)[ret_col]
            .rank(method="average", pct=True)
            .mul(100.0)
        )
    return out


def calculate_ma_divergence(df: pd.DataFrame) -> pd.DataFrame:
    """
    Moving-average divergence as dimensionless ratios.

    Output columns:
    - ma_ratio_5_20: MA(5) / MA(20)
    - ma_ratio_10_60: MA(10) / MA(60)
    """
    out = _prepare(df)
    grp_close = out.groupby("symbol", group_keys=False, sort=False)["close"]

    out["ma_5"] = grp_close.transform(lambda s: s.rolling(5, min_periods=5).mean())
    out["ma_10"] = grp_close.transform(lambda s: s.rolling(10, min_periods=10).mean())
    out["ma_20"] = grp_close.transform(lambda s: s.rolling(20, min_periods=20).mean())
    out["ma_60"] = grp_close.transform(lambda s: s.rolling(60, min_periods=60).mean())

    out["ma_ratio_5_20"] = out["ma_5"] / out["ma_20"]
    out["ma_ratio_10_60"] = out["ma_10"] / out["ma_60"]
    return out


def calculate_bias_zscore(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    Bias Z-Score:
    (Price - MA(window)) / RollingStd(window)
    """
    out = _prepare(df)
    w = int(window)
    grp_close = out.groupby("symbol", group_keys=False, sort=False)["close"]

    ma_col = f"ma_{w}"
    std_col = f"rolling_std_{w}"
    z_col = f"bias_zscore_{w}"

    out[ma_col] = grp_close.transform(lambda s: s.rolling(w, min_periods=w).mean())
    out[std_col] = grp_close.transform(lambda s: s.rolling(w, min_periods=w).std())
    out[z_col] = (out["close"] - out[ma_col]) / out[std_col]
    return out


def calculate_acceleration(df: pd.DataFrame) -> pd.DataFrame:
    """
    Second-derivative style acceleration features:
    1) Daily change of MACD histogram.
    2) Change of 20MA slope.
    """
    out = _prepare(df)
    grp = out.groupby("symbol", group_keys=False, sort=False)

    ema12 = grp["close"].transform(lambda s: s.ewm(span=12, adjust=False).mean())
    ema26 = grp["close"].transform(lambda s: s.ewm(span=26, adjust=False).mean())
    out["macd_line"] = ema12 - ema26
    out["macd_signal"] = grp["macd_line"].transform(
        lambda s: s.ewm(span=9, adjust=False).mean()
    )
    out["macd_hist"] = out["macd_line"] - out["macd_signal"]
    out["macd_hist_delta_1d"] = grp["macd_hist"].diff(1)

    out["ma_20"] = grp["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    out["ma20_slope_1d"] = grp["ma_20"].diff(1)
    out["ma20_slope_delta_1d"] = grp["ma20_slope_1d"].diff(1)
    return out


def build_momentum_features(
    df: pd.DataFrame,
    rs_windows: Iterable[int] = (20, 60),
    bias_window: int = 20,
) -> pd.DataFrame:
    """
    Convenience pipeline to build all momentum/price features in one call.
    """
    out = calculate_rs_rank(df, window=tuple(rs_windows))
    out = calculate_ma_divergence(out)
    out = calculate_bias_zscore(out, window=bias_window)
    out = calculate_acceleration(out)
    return out
