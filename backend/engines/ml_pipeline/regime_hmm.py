"""
Market regime modeling with Gaussian HMM.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Union

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler


@dataclass
class RegimeHMMBundle:
    model: GaussianHMM
    scaler: StandardScaler
    feature_columns: list[str]
    state_label_map: dict[int, str]


def build_regime_features(macro_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build HMM input features from macro indicators.

    Required columns in macro_df:
    - date
    - taiex_close
    - taiex_volume
    - vix (optional but recommended)
    """
    required = {"date", "taiex_close", "taiex_volume"}
    missing = required - set(macro_df.columns)
    if missing:
        raise ValueError(f"macro_df missing required columns: {sorted(missing)}")

    out = macro_df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values("date").reset_index(drop=True)

    out["taiex_return_1d"] = pd.to_numeric(out["taiex_close"], errors="coerce").pct_change(1)
    out["taiex_realized_vol_20"] = out["taiex_return_1d"].rolling(20, min_periods=20).std()
    out["taiex_volume_chg_1d"] = pd.to_numeric(out["taiex_volume"], errors="coerce").pct_change(1)
    out["vix"] = pd.to_numeric(out.get("vix"), errors="coerce")

    feature_cols = [
        "taiex_return_1d",
        "taiex_realized_vol_20",
        "taiex_volume_chg_1d",
        "vix",
    ]
    out = out[["date", *feature_cols]].copy()
    for c in feature_cols:
        out[c] = pd.to_numeric(out[c], errors="coerce").replace([np.inf, -np.inf], np.nan)
    return out


def train_regime_hmm(
    macro_df: pd.DataFrame,
    n_states: int = 3,
    random_state: int = 42,
    n_iter: int = 300,
) -> RegimeHMMBundle:
    """
    Train a Gaussian HMM (default 3 states).
    """
    feat = build_regime_features(macro_df)
    feature_cols = [c for c in feat.columns if c != "date"]
    feat_clean = feat.dropna(subset=feature_cols).reset_index(drop=True)
    if feat_clean.empty:
        raise ValueError("No valid rows available to train HMM after dropping NaNs.")

    scaler = StandardScaler()
    X = scaler.fit_transform(feat_clean[feature_cols].to_numpy(dtype=float))

    model = GaussianHMM(
        n_components=int(n_states),
        covariance_type="full",
        n_iter=int(n_iter),
        random_state=int(random_state),
    )
    model.fit(X)
    states = model.predict(X)

    # Map state id -> bull/sideways/bear by mean index return in that state
    state_ret = (
        pd.DataFrame({"state": states, "ret": feat_clean["taiex_return_1d"].to_numpy()})
        .groupby("state", as_index=True)["ret"]
        .mean()
        .sort_values()
    )
    ordered_states = state_ret.index.tolist()  # low -> high
    state_label_map: dict[int, str] = {}
    if len(ordered_states) >= 1:
        state_label_map[ordered_states[0]] = "bear"
    if len(ordered_states) >= 2:
        state_label_map[ordered_states[-1]] = "bull"
    for s in ordered_states[1:-1]:
        state_label_map[s] = "sideways"

    return RegimeHMMBundle(
        model=model,
        scaler=scaler,
        feature_columns=feature_cols,
        state_label_map=state_label_map,
    )


def predict_regime_series(
    bundle: RegimeHMMBundle,
    macro_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Predict regime states for the full macro time series.
    """
    feat = build_regime_features(macro_df)
    feat_clean = feat.dropna(subset=bundle.feature_columns).reset_index(drop=True)
    if feat_clean.empty:
        return pd.DataFrame(columns=["date", "regime_state", "regime_label"])

    X = bundle.scaler.transform(feat_clean[bundle.feature_columns].to_numpy(dtype=float))
    states = bundle.model.predict(X)

    out = feat_clean[["date"]].copy()
    out["regime_state"] = states
    out["regime_label"] = out["regime_state"].map(bundle.state_label_map).fillna("unknown")
    return out


def save_regime_bundle(bundle: RegimeHMMBundle, path: Union[str, Path]) -> None:
    """Persist trained HMM + scaler for inference (joblib)."""
    try:
        import joblib
    except ImportError as exc:  # pragma: no cover
        raise ImportError("joblib is required to save regime bundle; pip install joblib") from exc

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)


def load_regime_bundle(path: Union[str, Path]) -> RegimeHMMBundle:
    """Load bundle written by ``save_regime_bundle``."""
    try:
        import joblib
    except ImportError as exc:  # pragma: no cover
        raise ImportError("joblib is required to load regime bundle; pip install joblib") from exc

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Regime bundle not found: {path}")
    obj = joblib.load(path)
    if not isinstance(obj, RegimeHMMBundle):
        raise TypeError(f"Expected RegimeHMMBundle, got {type(obj)}")
    return obj


def infer_current_regime(
    bundle: RegimeHMMBundle,
    macro_df: pd.DataFrame,
) -> dict:
    """
    Infer current regime from the latest available macro row.
    Returns regime id + semantic label (bull/sideways/bear).
    """
    pred_df = predict_regime_series(bundle, macro_df)
    if pred_df.empty:
        raise ValueError("No valid macro rows to infer regime.")
    last = pred_df.iloc[-1]
    return {
        "date": str(pd.to_datetime(last["date"]).date()),
        "regime_state": int(last["regime_state"]),
        "regime_label": str(last["regime_label"]),
    }
