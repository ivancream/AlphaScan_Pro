"""
本機測試每日 ML 推論（不需啟動 FastAPI）。

印出：最新交易日大盤 regime、符合 WFO surviving rules 的選股清單。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# backend/scripts/ml_research/this_file.py -> repo root is 3 levels up
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.db.connection import init_all  # noqa: E402
from backend.engines.ml_pipeline.daily_inference import (  # noqa: E402
    resolve_universe,
    run_daily_inference,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily ML inference (WFO rules + HMM)")
    parser.add_argument(
        "--universe",
        type=str,
        default="all",
        help="all | watchlist | symbols（symbols 時搭配 --symbols）",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="逗號分隔代碼，僅 universe=symbols 時需要",
    )
    parser.add_argument("--lookback", type=int, default=100, help="回溯交易日數")
    parser.add_argument(
        "--rules",
        type=Path,
        default=None,
        help="wfo_surviving_rules.json 路徑（預設 data/ml_datasets/wfo_surviving_rules.json）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="額外印出完整 JSON（便於管線重導向）",
    )
    args = parser.parse_args()

    init_all()

    try:
        u = resolve_universe(args.universe, args.symbols or None)
    except ValueError as exc:
        print(f"[05] {exc}")
        sys.exit(1)

    out = run_daily_inference(
        universe=u,
        lookback_trading_days=int(args.lookback),
        rules_path=args.rules,
    )

    reg = out.get("regime") or {}
    print(
        f"[05] 大盤狀態 as_of={reg.get('date')} "
        f"regime_state={reg.get('regime_state')} label={reg.get('regime_label')}"
    )
    print(f"[05] 特徵截面 as_of_date={out.get('as_of_date')} n_universe={out.get('n_universe')}")
    print(f"[05] rules_path={out.get('rules_path')}")

    picks: list = out.get("picks") or []
    if not picks:
        print("[05] 無符合規則之標的（或規則檔不存在／為空）。")
    else:
        print(f"[05] 觸發規則之標的數 = {len(picks)}")
        for i, row in enumerate(picks, start=1):
            sym = row.get("symbol")
            close = row.get("close")
            rule = row.get("rule_human_readable", "")
            print(f"  {i}. {sym} close={close} | {rule}")

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
