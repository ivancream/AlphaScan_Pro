"""
Walk-forward rule mining with DecisionTreeClassifier and human-readable IF-THEN rules.

Notes
-----
- 預設使用 ``DecisionTreeClassifier(max_depth=3)`` 以利從樹結構萃取 IF-THEN 規則。
  LightGBM 可後續擴充，但需額外處理規則可讀性（本模組未內建）。
- 各 WFO 折內對特徵做「訓練集 median」填補後再訓練／萃取規則；規則門檻作用在填補後的特徵空間。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

# In-sample ~2y trading days; OOS ~3 months trading days
DEFAULT_TRAIN_TRADING_DAYS = 504
DEFAULT_TEST_TRADING_DAYS = 66
DEFAULT_MARKET_EXCESS = 0.02  # stock forward return > market + 2% (absolute)


@dataclass
class RuleCondition:
    feature: str
    op: str  # '<=' or '>'
    threshold: float

    def to_human(self) -> str:
        return f"{self.feature} {self.op} {self.threshold:.6g}"


@dataclass
class MinedRule:
    conditions: List[RuleCondition]
    fold_id: int
    is_win_rate: float
    oos_win_rate: float
    is_triggers: int
    oos_triggers: int

    def human_readable(self) -> str:
        inner = " AND ".join(c.to_human() for c in self.conditions)
        return f"IF ({inner}) THEN label=1"

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "human_readable": self.human_readable(),
            "conditions": [
                {"feature": c.feature, "op": c.op, "threshold": float(c.threshold)}
                for c in self.conditions
            ],
            "is_win_rate": round(float(self.is_win_rate), 6),
            "oos_win_rate": round(float(self.oos_win_rate), 6),
            "is_triggers": int(self.is_triggers),
            "oos_triggers": int(self.oos_triggers),
        }


def _median_impute_train_test(
    tr: pd.DataFrame, te: pd.DataFrame, cols: Sequence[str]
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Per-column median from train; fill train/test; all-NaN columns -> 0.0."""
    tr_x = tr[list(cols)].apply(pd.to_numeric, errors="coerce").copy()
    te_x = te[list(cols)].apply(pd.to_numeric, errors="coerce").copy()
    for c in cols:
        med = tr_x[c].median()
        if pd.isna(med):
            fill = 0.0
        else:
            mf = float(med)
            fill = mf if np.isfinite(mf) else 0.0
        tr_x[c] = tr_x[c].fillna(fill)
        te_x[c] = te_x[c].fillna(fill)
    return tr_x, te_x


def _numeric_feature_columns(df: pd.DataFrame) -> List[str]:
    exclude = {
        "symbol",
        "date",
        "y_future_return_t1_td",
        "y_binary",
        "market_forward_ret",
        "market_excess_vs_market",
    }
    cols: List[str] = []
    for c in df.columns:
        if c in exclude:
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            cols.append(c)
    return sorted(cols)


def attach_market_forward_return(df: pd.DataFrame, forward_days: int = 5) -> pd.DataFrame:
    """
    Same horizon as training label: close[T+forward_days] / close[T+1] - 1 on taiex_close.
    """
    if "taiex_close" not in df.columns:
        out = df.copy()
        out["market_forward_ret"] = np.nan
        return out

    m = df[["date", "taiex_close"]].drop_duplicates(subset=["date"]).sort_values("date").copy()
    tc = pd.to_numeric(m["taiex_close"], errors="coerce")
    d = int(max(1, forward_days))
    m["market_forward_ret"] = tc.shift(-d) / tc.shift(-1) - 1.0
    return df.merge(m[["date", "market_forward_ret"]], on="date", how="left")


def build_binary_target_vs_market(
    df: pd.DataFrame,
    stock_return_col: str = "y_future_return_t1_td",
    market_excess: float = DEFAULT_MARKET_EXCESS,
) -> pd.Series:
    """
    label = 1 if stock T+1:T+d return > market same-horizon return + market_excess (default 2%).
    """
    y_s = pd.to_numeric(df[stock_return_col], errors="coerce")
    y_m = pd.to_numeric(df["market_forward_ret"], errors="coerce")
    excess = y_s - y_m
    return (excess > float(market_excess)).astype("int8")


def _rolling_date_splits(
    unique_dates: np.ndarray,
    train_days: int,
    test_days: int,
) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
    """
    Rolling window on the sorted unique trading-date array (positions, not calendar gaps).
    """
    n = len(unique_dates)
    need = int(train_days) + int(test_days)
    if n < need:
        return
    start = 0
    while start + need <= n:
        train_dates = unique_dates[start : start + int(train_days)]
        test_dates = unique_dates[start + int(train_days) : start + need]
        yield train_dates, test_dates
        start += int(test_days)


def _rule_mask(df: pd.DataFrame, conditions: Sequence[RuleCondition]) -> pd.Series:
    m = pd.Series(True, index=df.index)
    for cond in conditions:
        if cond.feature not in df.columns:
            return pd.Series(False, index=df.index)
        col = pd.to_numeric(df[cond.feature], errors="coerce")
        thr = float(cond.threshold)
        if cond.op == "<=":
            m &= col <= thr
        elif cond.op == ">":
            m &= col > thr
        else:
            raise ValueError(f"Unsupported op: {cond.op}")
    return m


def _win_rate_and_count(y: pd.Series, mask: pd.Series) -> Tuple[float, int]:
    if not bool(mask.any()):
        return float("nan"), 0
    sel = y.loc[mask & y.notna()]
    n = int(len(sel))
    if n == 0:
        return float("nan"), 0
    return float(sel.mean()), n


def rule_passes_filters(
    is_win_rate: float,
    is_triggers: int,
    oos_win_rate: float,
    *,
    min_is_win_rate: float = 0.65,
    min_is_triggers: int = 100,
    max_oos_relative_drop: float = 0.20,
) -> bool:
    """
    - In-sample win rate > min_is_win_rate
    - In-sample triggers > min_is_triggers
    - OOS win rate must not fall below IS * (1 - max_oos_relative_drop)
    """
    if is_triggers < int(min_is_triggers):
        return False
    if not np.isfinite(is_win_rate) or is_win_rate <= float(min_is_win_rate):
        return False
    if not np.isfinite(oos_win_rate):
        return False
    floor = float(is_win_rate) * (1.0 - float(max_oos_relative_drop))
    return oos_win_rate >= floor


def extract_rules_from_decision_tree(
    clf: DecisionTreeClassifier,
    feature_names: Sequence[str],
    *,
    min_leaf_positive_ratio: float = 0.5,
) -> List[List[RuleCondition]]:
    """
    Extract conjunction rules from leaves where majority class is positive (label=1).
    """
    tree_ = clf.tree_
    feats = list(feature_names)
    rules: List[List[RuleCondition]] = []

    def recurse(node: int, conds: List[RuleCondition]) -> None:
        if tree_.children_left[node] == -1:
            counts = np.asarray(tree_.value[node]).reshape(-1)
            total = float(np.sum(counts))
            if total <= 0:
                return
            if len(counts) < 2:
                return
            p_pos = float(counts[1]) / total
            if p_pos >= float(min_leaf_positive_ratio):
                rules.append(list(conds))
            return

        feat_idx = int(tree_.feature[node])
        thr = float(tree_.threshold[node])
        feat_name = feats[feat_idx] if 0 <= feat_idx < len(feats) else str(feat_idx)

        left = int(tree_.children_left[node])
        right = int(tree_.children_right[node])
        recurse(left, conds + [RuleCondition(feat_name, "<=", thr)])
        recurse(right, conds + [RuleCondition(feat_name, ">", thr)])

    recurse(0, [])
    return rules


def _conditions_key(conds: Sequence[RuleCondition]) -> Tuple[Tuple[str, str, float], ...]:
    return tuple((c.feature, c.op, round(float(c.threshold), 8)) for c in conds)


def run_wfo_rule_mining(
    df: pd.DataFrame,
    *,
    forward_return_days: int = 5,
    train_trading_days: int = DEFAULT_TRAIN_TRADING_DAYS,
    test_trading_days: int = DEFAULT_TEST_TRADING_DAYS,
    market_excess: float = DEFAULT_MARKET_EXCESS,
    random_state: int = 42,
    min_is_win_rate: float = 0.65,
    min_is_triggers: int = 100,
    max_oos_relative_drop: float = 0.20,
    tree_max_depth: int = 3,
    min_samples_leaf: int = 40,
) -> List[MinedRule]:
    """
    Rolling WFO: train on train_trading_days, test on test_trading_days, roll by test window.
    """
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    work = work.sort_values(["date", "symbol"]).reset_index(drop=True)

    work = attach_market_forward_return(work, forward_days=int(forward_return_days))
    work["y_binary"] = build_binary_target_vs_market(work, market_excess=float(market_excess))

    feat_cols = _numeric_feature_columns(work)
    if not feat_cols:
        return []

    unique_dates = np.sort(work["date"].unique())
    surviving: Dict[Tuple[Tuple[str, str, float], ...], MinedRule] = {}

    for fold_id, (train_dates, test_dates) in enumerate(
        _rolling_date_splits(unique_dates, train_trading_days, test_trading_days)
    ):
        train_mask = work["date"].isin(train_dates)
        test_mask = work["date"].isin(test_dates)

        tr = work.loc[train_mask].copy()
        te = work.loc[test_mask].copy()

        tr = tr.dropna(subset=["y_binary", "market_forward_ret"], how="any")
        te = te.dropna(subset=["y_binary", "market_forward_ret"], how="any")
        if len(tr) < 500 or len(te) < 100:
            continue

        tr_x, te_x = _median_impute_train_test(tr, te, feat_cols)
        y_tr = tr["y_binary"].to_numpy(dtype=int)
        y_te = te["y_binary"].to_numpy(dtype=int)

        X_tr = tr_x.to_numpy(dtype=float)
        X_te = te_x.to_numpy(dtype=float)

        clf = DecisionTreeClassifier(
            max_depth=int(tree_max_depth),
            min_samples_leaf=int(min_samples_leaf),
            random_state=int(random_state) + fold_id,
            class_weight="balanced",
        )
        clf.fit(X_tr, y_tr)

        raw_rules = extract_rules_from_decision_tree(clf, feat_cols)
        for conds in raw_rules:
            m_tr = _rule_mask(tr_x, conds)
            m_te = _rule_mask(te_x, conds)
            is_wr, is_n = _win_rate_and_count(tr["y_binary"], m_tr)
            oos_wr, oos_n = _win_rate_and_count(te["y_binary"], m_te)

            if not rule_passes_filters(
                is_wr,
                is_n,
                oos_wr,
                min_is_win_rate=min_is_win_rate,
                min_is_triggers=min_is_triggers,
                max_oos_relative_drop=max_oos_relative_drop,
            ):
                continue

            key = _conditions_key(conds)
            cand = MinedRule(
                conditions=list(conds),
                fold_id=fold_id,
                is_win_rate=is_wr,
                oos_win_rate=oos_wr,
                is_triggers=is_n,
                oos_triggers=oos_n,
            )
            prev = surviving.get(key)
            if prev is None or cand.oos_win_rate > prev.oos_win_rate:
                surviving[key] = cand

    return list(surviving.values())


def rules_to_json_serializable(rules: Sequence[MinedRule]) -> List[Dict[str, Any]]:
    return [r.to_json_dict() for r in rules]


def dump_rules_json(rules: Sequence[MinedRule], path: str) -> None:
    payload = {
        "n_rules": len(rules),
        "rules": rules_to_json_serializable(rules),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
