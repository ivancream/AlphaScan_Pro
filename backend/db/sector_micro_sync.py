"""
將專案根目錄 theme.json 的題材寫入 DuckDB stock_sectors.micro（不讀 stock_themes.json）。

- 既有列：只 UPDATE micro，**絕不**覆寫 macro／meso／industry_raw（避免破壞證交所產業分類）。
- 題材表有、但 stock_sectors 尚無列：INSERT macro/meso=「其他」、industry_raw=NULL（待 CSV 刷新補產業）。
- 題材表沒有的代號：micro 清空為 NULL。
"""

from __future__ import annotations

from typing import Any

from backend.db.connection import DUCKDB_PATH, duck_read
from backend.db import writer
from backend.engines.theme_loader import load_theme_catalog_stock_tags


def _stock_id_str(raw: Any) -> str:
    if raw is None:
        return ""
    return str(raw).strip()


def _tags_to_db_micro(tags: list[str]) -> str | None:
    if not tags:
        return None
    if len(tags) == 1:
        return tags[0]
    return "、".join(tags)


def apply_theme_json_to_stock_sectors() -> tuple[int, int]:
    """
    回傳 (upsert 總筆數, 本次因僅在題材表而新增的代號數)。
    若無 DuckDB 檔則回傳 (0, 0)。
    """
    if not DUCKDB_PATH.exists():
        return 0, 0

    theme_lists = load_theme_catalog_stock_tags()

    with duck_read() as conn:
        rows = conn.execute("SELECT stock_id FROM stock_sectors").fetchall()

    existing: set[str] = set()
    for r in rows:
        sid = _stock_id_str(r[0])
        if sid:
            existing.add(sid)

    micro_rows: list[tuple[str, str | None]] = []
    for sid in existing:
        if sid in theme_lists:
            micro_rows.append((sid, _tags_to_db_micro(theme_lists[sid])))
        else:
            micro_rows.append((sid, None))

    n_updated = writer.update_stock_sectors_micro_only(micro_rows)

    inserted = 0
    insert_rows: list[tuple[str, str, str, str | None, str | None]] = []
    for sid, tags in theme_lists.items():
        if sid in existing:
            continue
        micro = _tags_to_db_micro(tags)
        if not micro:
            continue
        insert_rows.append((sid, "其他", "其他", micro, None))
        inserted += 1

    n_ins = writer.upsert_stock_sectors(insert_rows) if insert_rows else 0
    return n_updated + n_ins, inserted
