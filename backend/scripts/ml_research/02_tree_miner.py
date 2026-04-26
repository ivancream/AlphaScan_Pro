"""Train a baseline decision tree for alpha-factor research."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier


def run_tree_experiment(
    data_path: Path,
    target_col: str,
    test_size: float = 0.2,
    random_state: int = 42,
) -> None:
    """Train and evaluate a simple DecisionTree classifier."""
    df = pd.read_parquet(data_path)
    if target_col not in df.columns:
        raise ValueError(f"Target column '{target_col}' not found in dataset")

    X = df.drop(columns=[target_col])
    y = df[target_col]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )

    model = DecisionTreeClassifier(
        max_depth=5,
        min_samples_leaf=20,
        random_state=random_state,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    print("=== Decision Tree Report ===")
    print(classification_report(y_test, y_pred))


def main() -> None:
    parser = argparse.ArgumentParser(description="Decision tree alpha miner")
    parser.add_argument("--data-path", required=True, help="Parquet path from 01_data_prep")
    parser.add_argument("--target-col", required=True, help="Supervised target column name")
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args()

    run_tree_experiment(
        data_path=Path(args.data_path),
        target_col=args.target_col,
        test_size=args.test_size,
        random_state=args.random_state,
    )


if __name__ == "__main__":
    main()
