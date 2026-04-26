"""
Daily ML inference: latest HMM regime, cross-sectional features, WFO rule picks.

Uses the same feature stack as ``dataset_builder.build_training_dataset`` (without
forward labels or liquidity filter). Loads persisted ``regime_hmm_bundle.joblib``
when present (written by ``03_build_dataset.py``); otherwise retrains on macro.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from backend.db.connection import duck_read


def load_macro_df_global() -> pd.DataFrame:
    """與 API / init_all 共用同一 DuckDB 連線，避免 Windows 下雙重連線設定衝突。"""
    with duck_read() as conn:
        return conn.execute(
            """
            SELECT date, taiex_close, taiex_volume, vix
            FROM macro_indicators
            ORDER BY date
            """
        ).df()
from backend.engines.feature_engineering.momentum import build_momentum_features
from backend.engines.feature_engineering.volume_chips import (
    calculate_obv_slope,
    calculate_orthogonalized_flow,
    calculate_price_volume_corr,
    calculate_trust_penetration,
    calculate_volume_zscore,
)
from backend.engines.ml_pipeline.dataset_builder import _chips_data_missing
from backend.engines.ml_pipeline.regime_hmm import (
    RegimeHMMBundle,
    infer_current_regime,
    load_regime_bundle,
    predict_regime_series,
    save_regime_bundle,
    train_regime_hmm,
)
from backend.engines.ml_pipeline.rule_miner import RuleCondition


def ml_datasets_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "ml_datasets"


def default_rules_path() -> Path:
    return ml_datasets_dir() / "wfo_surviving_rules.json"


def default_hmm_bundle_path() -> Path:
    return ml_datasets_dir() / "regime_hmm_bundle.joblib"


def _load_or_train_regime_bundle(
    macro_df: pd.DataFrame,
    *,
    bundle_path: Optional[Path] = None,
    n_states: int = 3,
    random_state: int = 42,
    persist_if_trained: bool = False,
) -> RegimeHMMBundle:
    path = bundle_path or default_hmm_bundle_path()
    if path.is_file():
        try:
            return load_regime_bundle(path)
        except Exception:  # noqa: BLE001
            pass
    bundle = train_regime_hmm(
        macro_df,
        n_states=int(n_states),
        random_state=int(random_state),
    )
    if persist_if_trained:
        try:
            save_regime_bundle(bundle, path)
        except Exception:  # noqa: BLE001
            pass
    return bundle


def get_latest_market_regime(
    *,
    bundle_path: Optional[Path] = None,
    hmm_states: int = 3,
    hmm_seed: int = 42,
    persist_if_trained: bool = False,
) -> Dict[str, Any]:
    """
    讀取 macro_indicators，載入（或重訓）HMM，回傳最新一個交易日的 regime_state (0~n-1) 與語意 label。
    """
    macro_df = load_macro_df_global()
    if macro_df is None or macro_df.empty:
        raise ValueError("macro_indicators 無資料，無法推論大盤 regime。")

    bundle = _load_or_train_regime_bundle(
        macro_df,
        bundle_path=bundle_path,
        n_states=int(hmm_states),
        random_state=int(hmm_seed),
        persist_if_trained=persist_if_trained,
    )
    info = infer_current_regime(bundle, macro_df)
    return {
        "date": info["date"],
        "regime_state": int(info["regime_state"]),
        "regime_label": str(info["regime_label"]),
    }


def _load_recent_price_chips(
    conn: Any,
    *,
    lookback_trading_days: int,
    symbols: Optional[Sequence[str]],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    n = int(max(1, lookback_trading_days))
    sym_list: Optional[List[str]] = None
    if symbols is not None:
        sym_list = [str(s).strip() for s in symbols if str(s).strip()]
        if not sym_list:
            return pd.DataFrame(), pd.DataFrame()

    if sym_list is None:
        price_df = conn.execute(
            f"""
            WITH d AS (
                SELECT DISTINCT date
                FROM historical_kbars_adj
                ORDER BY date DESC
                LIMIT {n}
            )
            SELECT
                h.symbol,
                h.date,
                h.open,
                h.high,
                h.low,
                h.close,
                h.volume,
                h.amount
            FROM historical_kbars_adj h
            INNER JOIN d ON h.date = d.date
            ORDER BY h.symbol, h.date
            """
        ).df()
        chips_df = conn.execute(
            f"""
            WITH d AS (
                SELECT DISTINCT date
                FROM historical_kbars_adj
                ORDER BY date DESC
                LIMIT {n}
            )
            SELECT
                c.symbol,
                c.date,
                c.foreign_buy,
                c.foreign_sell,
                c.investment_trust_buy,
                c.investment_trust_sell,
                c.dealer_buy,
                c.dealer_sell,
                c.total_shares_outstanding
            FROM historical_chips c
            INNER JOIN d ON c.date = d.date
            ORDER BY c.symbol, c.date
            """
        ).df()
    else:
        ph = ", ".join(["?"] * len(sym_list))
        price_df = conn.execute(
            f"""
            WITH d AS (
                SELECT DISTINCT date
                FROM historical_kbars_adj
                ORDER BY date DESC
                LIMIT {n}
            )
            SELECT
                h.symbol,
                h.date,
                h.open,
                h.high,
                h.low,
                h.close,
                h.volume,
                h.amount
            FROM historical_kbars_adj h
            INNER JOIN d ON h.date = d.date
            WHERE h.symbol IN ({ph})
            ORDER BY h.symbol, h.date
            """,
            sym_list,
        ).df()
        chips_df = conn.execute(
            f"""
            WITH d AS (
                SELECT DISTINCT date
                FROM historical_kbars_adj
                ORDER BY date DESC
                LIMIT {n}
            )
            SELECT
                c.symbol,
                c.date,
                c.foreign_buy,
                c.foreign_sell,
                c.investment_trust_buy,
                c.investment_trust_sell,
                c.dealer_buy,
                c.dealer_sell,
                c.total_shares_outstanding
            FROM historical_chips c
            INNER JOIN d ON c.date = d.date
            WHERE c.symbol IN ({ph})
            ORDER BY c.symbol, c.date
            """,
            sym_list,
        ).df()

    return price_df, chips_df


def _build_feature_panel(
    price_df: pd.DataFrame,
    chips_df: pd.DataFrame,
    macro_df: pd.DataFrame,
    regime_df: pd.DataFrame,
) -> pd.DataFrame:
    """Mirror dataset_builder feature path (no label / no liquidity filter)."""
    if price_df.empty:
        return pd.DataFrame()

    price_df = price_df.copy()
    price_df["date"] = pd.to_datetime(price_df["date"])

    chips_missing = _chips_data_missing(chips_df)
    if not chips_missing:
        chips_df = chips_df.copy()
        chips_df["date"] = pd.to_datetime(chips_df["date"])
        base = price_df.merge(chips_df, on=["symbol", "date"], how="left")
    else:
        base = price_df.copy()
        for c in (
            "foreign_buy",
            "foreign_sell",
            "investment_trust_buy",
            "investment_trust_sell",
            "dealer_buy",
            "dealer_sell",
            "total_shares_outstanding",
        ):
            base[c] = np.nan

    feat = build_momentum_features(base)
    feat = calculate_volume_zscore(feat, window=20)
    feat = calculate_price_volume_corr(feat, window=10)
    feat = calculate_obv_slope(feat, window=10)

    if not chips_missing:
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

    if not macro_df.empty:
        m = macro_df.copy()
        m["date"] = pd.to_datetime(m["date"])
        feat = feat.merge(m, on="date", how="left")

    if not regime_df.empty:
        r = regime_df[["date", "regime_state"]].copy()
        r["date"] = pd.to_datetime(r["date"])
        r = r.rename(columns={"regime_state": "market_regime"})
        feat = feat.merge(r, on="date", how="left")
    else:
        feat["market_regime"] = np.nan

    feat = feat.sort_values(["symbol", "date"]).reset_index(drop=True)
    for c in feat.columns:
        if pd.api.types.is_numeric_dtype(feat[c]):
            feat[c] = pd.to_numeric(feat[c], errors="coerce").replace([np.inf, -np.inf], np.nan)
    return feat


def get_latest_features(
    universe: Union[str, Iterable[str]] = "all",
    *,
    lookback_trading_days: int = 100,
) -> pd.DataFrame:
    """
    自 DB 撈最近 ``lookback_trading_days`` 個交易日的價量與籌碼，套用特徵工程後，
    只保留「全樣本中最新一個交易日」的橫斷面。
    """
    sym_filter: Optional[List[str]] = None
    if isinstance(universe, str) and universe.lower() == "all":
        sym_filter = None
    elif isinstance(universe, str):
        raise ValueError(f"Unsupported universe: {universe}")
    else:
        sym_filter = [str(s).strip() for s in universe if str(s).strip()]
        if not sym_filter:
            return pd.DataFrame()

    with duck_read() as conn:
        price_df, chips_df = _load_recent_price_chips(
            conn,
            lookback_trading_days=int(lookback_trading_days),
            symbols=sym_filter,
        )

    macro_df = load_macro_df_global()
    if macro_df.empty:
        regime_df = pd.DataFrame(columns=["date", "regime_state", "regime_label"])
    else:
        bundle = _load_or_train_regime_bundle(macro_df.copy())
        regime_df = predict_regime_series(bundle, macro_df)

    panel = _build_feature_panel(price_df, chips_df, macro_df, regime_df)
    if panel.empty:
        return pd.DataFrame()

    last_d = panel["date"].max()
    out = panel.loc[panel["date"] == last_d].copy().reset_index(drop=True)
    return out


def _split_regime_conditions(
    conditions: Sequence[RuleCondition],
) -> Tuple[List[RuleCondition], List[RuleCondition]]:
    regime_feats = {"market_regime"}
    reg_conds = [c for c in conditions if c.feature in regime_feats]
    other = [c for c in conditions if c.feature not in regime_feats]
    return reg_conds, other


def _regime_conditions_hold(conds: Sequence[RuleCondition], current_regime: int) -> bool:
    v = float(current_regime)
    for c in conds:
        thr = float(c.threshold)
        col_v = v
        if c.op == "<=":
            if not (col_v <= thr):
                return False
        elif c.op == ">":
            if not (col_v > thr):
                return False
        else:
            return False
    return True


_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _conditions_to_query(conds: Sequence[RuleCondition]) -> str:
    parts: List[str] = []
    for c in conds:
        name = c.feature
        qcol = name if _SAFE_IDENT.match(name) else f"`{name}`"
        thr = float(c.threshold)
        if c.op == "<=":
            parts.append(f"({qcol} <= {thr})")
        elif c.op == ">":
            parts.append(f"({qcol} > {thr})")
        else:
            raise ValueError(f"Unsupported op in query: {c.op}")
    return " & ".join(parts) if parts else "index >= 0"


def _df_records_json_safe(df: pd.DataFrame) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        clean: Dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                clean[k] = None
            elif v is pd.NA:  # pragma: no cover
                clean[k] = None
            else:
                clean[k] = v
        rows.append(clean)
    return rows


def evaluate_daily_picks(
    latest_features_df: pd.DataFrame,
    current_regime: int,
    *,
    rules_path: Optional[Path] = None,
) -> pd.DataFrame:
    """
    讀取 WFO surviving rules，依當前 regime 過濾規則後，以 pandas ``query`` 評估其餘條件。

    回傳欄位：symbol, close, rule_human_readable, fold_id, is_win_rate, oos_win_rate
    （同一檔股票可因多條規則出現多列）。
    """
    path = rules_path or default_rules_path()
    if not path.is_file():
        return pd.DataFrame(
            columns=[
                "symbol",
                "close",
                "rule_human_readable",
                "fold_id",
                "is_win_rate",
                "oos_win_rate",
            ]
        )

    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    raw_rules: List[Dict[str, Any]] = payload.get("rules") or []

    if latest_features_df.empty or not raw_rules:
        return pd.DataFrame(
            columns=[
                "symbol",
                "close",
                "rule_human_readable",
                "fold_id",
                "is_win_rate",
                "oos_win_rate",
            ]
        )

    df = latest_features_df.copy()
    if "symbol" not in df.columns:
        raise ValueError("latest_features_df 必須包含 symbol 欄位")
    if "close" not in df.columns:
        raise ValueError("latest_features_df 必須包含 close 欄位")

    rows_out: List[Dict[str, Any]] = []
    for rule in raw_rules:
        cond_dicts = rule.get("conditions") or []
        conds = [
            RuleCondition(
                feature=str(d["feature"]),
                op=str(d["op"]),
                threshold=float(d["threshold"]),
            )
            for d in cond_dicts
        ]
        if not conds:
            continue

        reg_conds, feat_conds = _split_regime_conditions(conds)
        if reg_conds and not _regime_conditions_hold(reg_conds, int(current_regime)):
            continue
        if not feat_conds:
            continue

        q = _conditions_to_query(feat_conds)
        try:
            hit = df.query(q, engine="python")
        except Exception:  # noqa: BLE001
            continue

        human = str(rule.get("human_readable") or "")
        fold_id = int(rule.get("fold_id", -1))
        is_wr = float(rule.get("is_win_rate", float("nan")))
        oos_wr = float(rule.get("oos_win_rate", float("nan")))

        for _, r in hit.iterrows():
            rows_out.append(
                {
                    "symbol": str(r["symbol"]).strip(),
                    "close": float(pd.to_numeric(r["close"], errors="coerce")),
                    "rule_human_readable": human,
                    "fold_id": fold_id,
                    "is_win_rate": is_wr,
                    "oos_win_rate": oos_wr,
                }
            )

    return pd.DataFrame(rows_out)


def run_daily_inference(
    *,
    universe: Union[str, Iterable[str]] = "all",
    lookback_trading_days: int = 100,
    rules_path: Optional[Path] = None,
    hmm_bundle_path: Optional[Path] = None,
    hmm_states: int = 3,
    hmm_seed: int = 42,
) -> Dict[str, Any]:
    """
    單次完整推論：大盤 regime + 最新特徵 + 規則選股。

    ``universe`` 僅接受字串 ``\"all\"`` 或股票代碼可迭代物件（已在 API 層解析 watchlist）。
    """
    sym_arg: Optional[List[str]] = None
    if isinstance(universe, str):
        if universe.lower() != "all":
            raise ValueError('universe 字串僅支援 "all"；watchlist 等請先展開為代碼清單。')
    else:
        sym_arg = [str(s).strip() for s in universe if str(s).strip()]

    with duck_read() as conn:
        price_df, chips_df = _load_recent_price_chips(
            conn,
            lookback_trading_days=int(lookback_trading_days),
            symbols=sym_arg,
        )

    macro_df = load_macro_df_global()
    if macro_df.empty:
        raise ValueError("macro_indicators 無資料。")

    bundle = _load_or_train_regime_bundle(
        macro_df,
        bundle_path=hmm_bundle_path,
        n_states=int(hmm_states),
        random_state=int(hmm_seed),
    )
    regime_info = infer_current_regime(bundle, macro_df)
    regime_df = predict_regime_series(bundle, macro_df)

    panel = _build_feature_panel(price_df, chips_df, macro_df, regime_df)
    if panel.empty:
        return {
            "as_of_date": None,
            "regime": regime_info,
            "n_universe": 0,
            "picks": [],
            "rules_path": str(rules_path or default_rules_path()),
        }

    last_d = panel["date"].max()
    latest = panel.loc[panel["date"] == last_d].copy().reset_index(drop=True)

    picks_df = evaluate_daily_picks(
        latest,
        int(regime_info["regime_state"]),
        rules_path=rules_path,
    )
    picks = _df_records_json_safe(picks_df) if not picks_df.empty else []

    return {
        "as_of_date": str(pd.Timestamp(last_d).date()),
        "regime": {
            "date": regime_info["date"],
            "regime_state": int(regime_info["regime_state"]),
            "regime_label": str(regime_info["regime_label"]),
        },
        "n_universe": int(len(latest)),
        "picks": picks,
        "rules_path": str(rules_path or default_rules_path()),
    }


def resolve_universe(universe: str, symbols_csv: Optional[str] = None) -> Union[str, List[str]]:
    """CLI / API helper: universe=all|watchlist|symbols (comma-separated)."""
    u = (universe or "all").strip().lower()
    if u in ("", "all"):
        return "all"
    if u == "watchlist":
        try:
            from backend.db.user_db import get_watchlist

            wl = get_watchlist()
            return wl if wl else "all"
        except Exception:  # noqa: BLE001
            return "all"
    if u == "symbols":
        if not (symbols_csv or "").strip():
            raise ValueError("universe=symbols 時需搭配 symbols 參數")
        return [s.strip() for s in symbols_csv.split(",") if s.strip()]
    raise ValueError(f"Unknown universe={universe!r}; use all|watchlist|symbols")
