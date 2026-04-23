"""
ingest_warrant_master.py — 自證交所公開 CSV 匯入權證主檔（warrant_master）。

執行（專案根目錄）：
    python -m backend.scripts.ingest_warrant_master

注意：Windows 下 DuckDB 檔案通常僅允許單一程序開啟寫入；若 FastAPI 正在跑，
請先停後端再執行，或改用 API：POST /api/v1/warrants/refresh-master
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.db.connection import close_duckdb, init_duckdb
from backend.db.writer import log_update_error, upsert_warrant_master
from backend.engines.warrant_master_build import build_warrant_master_rows


def main() -> None:
    init_duckdb()
    try:
        rows = build_warrant_master_rows()
        if not rows:
            log_update_error("warrant_master", "無資料可寫入（下載失敗或全部略過）")
            print("[ingest_warrant_master] 中止：無資料")
            return
        n = upsert_warrant_master(rows)
        print(f"[ingest_warrant_master] 完成 upsert {n} 筆")
    finally:
        close_duckdb()


if __name__ == "__main__":
    main()
