"""
ML dataset builder for AlphaScan Pro.

Builds feature matrix X and label vector y with strict timestamp alignment
to avoid look-ahead bias.
"""

from __future__ import annotations

import warnings
from typing import Iterable, List, Optional, Tuple

import duckdb
import numpy as np
import pandas as pd

from backend.db.connection import DUCKDB_PATH
from backend.engines.feature_engineering.momentum import build_momentum_features
from backend.engines.feature_engineering.volume_chips import (
    calculate_obv_slope,
    calculate_orthogonalized_flow,
    calculate_price_volume_corr,
    calculate_trust_penetration,
    calculate_volume_zscore,
)

_CHIP_FEATURES_MISSING_WARNED = False


def list_distinct_symbols() -> List[str]:
    """Return sorted distinct symbols from historical_kbars_adj."""
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT DISTINCT symbol
            FROM historical_kbars_adj
            WHERE symbol IS NOT NULL AND trim(cast(symbol AS VARCHAR)) <> ''
            ORDER BY 1
            """
        ).fetchall()
    finally:
        con.close()
    return [str(r[0]).strip() for r in rows if r and r[0]]


def load_macro_df() -> pd.DataFrame:
    """Load full macro_indicators table (small)."""
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        macro_df = con.execute(
            """
            SELECT
                date,
                taiex_close,
                taiex_volume,
                vix
            FROM macro_indicators
            ORDER BY date
            """
        ).df()
    finally:
        con.close()
    return macro_df


def _load_price_chips_for_symbols(
    symbols: Optional[Iterable[str]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load price + chips for optional symbol subset (memory-friendly batching).
    When symbols is None, load entire tables.
    """
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        if symbols is None:
            price_df = con.execute(
                """
                SELECT
                    symbol,
                    date,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    amount
                FROM historical_kbars_adj
                ORDER BY symbol, date
                """
            ).df()
            chips_df = con.execute(
                """
                SELECT
                    symbol,
                    date,
                    foreign_buy,
                    foreign_sell,
                    investment_trust_buy,
                    investment_trust_sell,
                    dealer_buy,
                    dealer_sell,
                    total_shares_outstanding
                FROM historical_chips
                ORDER BY symbol, date
                """
            ).df()
        else:
            sym_list = [str(s).strip() for s in symbols if str(s).strip()]
            if not sym_list:
                return pd.DataFrame(), pd.DataFrame()
            placeholders = ", ".join(["?"] * len(sym_list))
            price_df = con.execute(
                f"""
                SELECT
                    symbol,
                    date,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    amount
                FROM historical_kbars_adj
                WHERE symbol IN ({placeholders})
                ORDER BY symbol, date
                """,
                sym_list,
            ).df()
            chips_df = con.execute(
                f"""
                SELECT
                    symbol,
                    date,
                    foreign_buy,
                    foreign_sell,
                    investment_trust_buy,
                    investment_trust_sell,
                    dealer_buy,
                    dealer_sell,
                    total_shares_outstanding
                FROM historical_chips
                WHERE symbol IN ({placeholders})
                ORDER BY symbol, date
                """,
                sym_list,
            ).df()
    finally:
        con.close()
    return price_df, chips_df


def _load_base_tables(
    symbols: Optional[Iterable[str]] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    price_df, chips_df = _load_price_chips_for_symbols(symbols)
    macro_df = load_macro_df()
    return price_df, chips_df, macro_df


def _apply_universe_filter(df: pd.DataFrame, universe: str | Iterable[str]) -> pd.DataFrame:
    if universe == "all":
        return df
    if isinstance(universe, str):
        # keep extension point for future universe types
        if universe.lower() == "all":
            return df
        raise ValueError(f"Unsupported universe: {universe}")
    symbols = {str(s).strip() for s in universe if str(s).strip()}
    if not symbols:
        return df.iloc[0:0].copy()
    return df[df["symbol"].astype(str).isin(symbols)].copy()


def _add_forward_label(df: pd.DataFrame, forward_return_days: int) -> pd.DataFrame:
    out = df.sort_values(["symbol", "date"]).copy()
    grp = out.groupby("symbol", group_keys=False, sort=False)
    d = int(max(1, forward_return_days))

    # Key anti look-ahead rule:
    # label at T uses only future prices (T+1..T+d), never data from <= T.
    # Return from T+1 to T+d: close[t+d] / close[t+1] - 1
    out["future_return_t1_td"] = (
        grp["close"].shift(-d) / grp["close"].shift(-1) - 1.0
    )
    return out


def _add_liquidity_filter(df: pd.DataFrame) -> pd.DataFrame:
    out = df.sort_values(["symbol", "date"]).copy()
    grp = out.groupby("symbol", group_keys=False, sort=False)
    out["vol_ma_5"] = grp["volume"].transform(
        lambda s: pd.to_numeric(s, errors="coerce").rolling(5, min_periods=5).mean()
    )
    # 500 張 = 500,000 shares
    out = out[out["vol_ma_5"] >= 500_000].copy()
    return out


def _chips_data_missing(chips_df: pd.DataFrame) -> bool:
    """True when chips table is empty or has no usable rows."""
    if chips_df is None or chips_df.empty:
        return True
    return len(chips_df) == 0


def _warn_chips_features_degraded() -> None:
    global _CHIP_FEATURES_MISSING_WARNED
    if _CHIP_FEATURES_MISSING_WARNED:
        return
    _CHIP_FEATURES_MISSING_WARNED = True
    warnings.warn(
        "historical_chips 無資料或為空：投信滲透率、正交化法人流等籌碼特徵將填為 NaN，"
        "管線仍會繼續執行。請補齊 FINMIND 籌碼後重新建置資料集。",
        UserWarning,
        stacklevel=3,
    )


def build_training_dataset(
    universe: str | Iterable[str] = "all",
    forward_return_days: int = 5,
    *,
    macro_df: Optional[pd.DataFrame] = None,
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Build clean training matrices (X, y) for ML models.

    Parameters
    ----------
    universe:
        "all" or an iterable of symbols.
    forward_return_days:
        Label horizon. Default 5 means cumulative return from T+1 to T+5.
    macro_df:
        Optional pre-loaded macro table to avoid repeated DB reads when batching.

    Returns
    -------
    X: pd.DataFrame
        Feature matrix indexed by [symbol, date].
    y: pd.Series
        Label vector aligned with X index.
    """
    sym_filter: Optional[list[str]] = None
    if isinstance(universe, str) and universe.lower() == "all":
        sym_filter = None
    elif isinstance(universe, str):
        raise ValueError(f"Unsupported universe: {universe}")
    else:
        sym_filter = [str(s).strip() for s in universe if str(s).strip()]
        if not sym_filter:
            return pd.DataFrame(), pd.Series(dtype="float64", name="y")

    price_df, chips_df = _load_price_chips_for_symbols(sym_filter)
    if macro_df is None:
        macro_df = load_macro_df()

    if price_df.empty:
        return pd.DataFrame(), pd.Series(dtype="float64", name="y")

    price_df["date"] = pd.to_datetime(price_df["date"])
    if isinstance(universe, str) and universe.lower() == "all":
        price_df = _apply_universe_filter(price_df, universe)
    if price_df.empty:
        return pd.DataFrame(), pd.Series(dtype="float64", name="y")

    chips_missing = _chips_data_missing(chips_df)
    if chips_missing:
        _warn_chips_features_degraded()

    # Join chip data (may be partially empty depending on ingestion stage)
    if not chips_missing:
        chips_df["date"] = pd.to_datetime(chips_df["date"])
        base = price_df.merge(chips_df, on=["symbol", "date"], how="left")
    else:
        base = price_df.copy()
        for c in [
            "foreign_buy",
            "foreign_sell",
            "investment_trust_buy",
            "investment_trust_sell",
            "dealer_buy",
            "dealer_sell",
            "total_shares_outstanding",
        ]:
            base[c] = np.nan

    # Feature pipelines
    feat = build_momentum_features(base)
    feat = calculate_volume_zscore(feat, window=20)
    feat = calculate_price_volume_corr(feat, window=10)
    feat = calculate_obv_slope(feat, window=10)

    if not chips_missing:
        # Net institutional flow for orthogonalization
        num_cols = [
            "foreign_buy",
            "foreign_sell",
            "investment_trust_buy",
            "investment_trust_sell",
            "dealer_buy",
            "dealer_sell",
        ]
        for c in num_cols:
            feat[c] = pd.to_numeric(feat[c], errors="coerce").fillna(0.0)
        feat["institutional_net_flow"] = (
            (feat["foreign_buy"] - feat["foreign_sell"])
            + (feat["investment_trust_buy"] - feat["investment_trust_sell"])
            + (feat["dealer_buy"] - feat["dealer_sell"])
        )

        market_flow = (
            feat.groupby("date", as_index=False)["institutional_net_flow"]
            .sum()
            .rename(columns={"institutional_net_flow": "market_institutional_net_flow"})
        )
        feat = calculate_trust_penetration(feat)
        feat = calculate_orthogonalized_flow(
            feat,
            market_df=market_flow,
            stock_flow_col="institutional_net_flow",
            market_flow_col="market_institutional_net_flow",
            rolling_window=60,
        )
    else:
        feat["institutional_net_flow"] = np.nan
        for col in (
            "trust_net_flow",
            "trust_net_flow_5d",
            "trust_penetration_5d",
            "orthogonalized_flow_residual",
        ):
            feat[col] = np.nan

    # Macro joins for downstream regime-aware models
    if not macro_df.empty:
        macro_df = macro_df.copy()
        macro_df["date"] = pd.to_datetime(macro_df["date"])
        feat = feat.merge(macro_df, on="date", how="left")

    # Label + risk control
    feat = _add_forward_label(feat, forward_return_days=forward_return_days)
    feat = _add_liquidity_filter(feat)

    # Final cleanup
    feat = feat.sort_values(["symbol", "date"]).reset_index(drop=True)
    y = pd.to_numeric(feat["future_return_t1_td"], errors="coerce")

    # Remove target leakage columns from X
    drop_cols = {
        "future_return_t1_td",
    }
    feature_cols = [c for c in feat.columns if c not in drop_cols]
    X = feat[feature_cols].copy()

    # Keep rows with valid label only
    valid = y.notna()
    X = X.loc[valid].copy()
    y = y.loc[valid].copy()

    X = X.set_index(["symbol", "date"], drop=True).sort_index()
    y.index = X.index
    y.name = "y_future_return_t1_td"
    return X, y
