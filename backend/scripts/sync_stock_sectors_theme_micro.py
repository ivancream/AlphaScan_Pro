"""
依專案根目錄 theme.json（及 data/stock_themes.json 覆寫）更新 DuckDB stock_sectors.micro。

執行：
    python -m backend.scripts.sync_stock_sectors_theme_micro

不需下載證交所 CSV；僅讀現有 stock_sectors 並覆寫／補齊題材欄位。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.db.sector_micro_sync import apply_theme_json_to_stock_sectors


def main() -> None:
    n, inserted = apply_theme_json_to_stock_sectors()
    print(f"[ThemeMicroSync] Upserted {n} stock_sectors rows (new from theme-only: {inserted}).")


if __name__ == "__main__":
    main()
