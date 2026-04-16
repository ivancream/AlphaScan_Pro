"""
將 theme.json + data/stock_themes.json 合併後的題材寫入 DuckDB stock_sectors.micro。

- 題材表內有的代號：覆寫 micro（macro/meso/industry_raw 不變）。
- 題材表有、但 stock_sectors 尚無列：插入 macro/meso=「其他」、industry_raw=NULL。
- 題材表沒有的代號：保留資料庫原有 micro。
"""

from __future__ import annotations

from typing import Any

from backend.db.connection import DUCKDB_PATH, duck_read
from backend.db import writer
from backend.engines.theme_loader import load_json_theme_micro_lists


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

    theme_lists = load_json_theme_micro_lists()
    if not theme_lists:
        return 0, 0

    with duck_read() as conn:
        rows = conn.execute(
            "SELECT stock_id, macro, meso, micro, industry_raw FROM stock_sectors"
        ).fetchall()

    existing: dict[str, tuple[Any, Any, Any, Any]] = {}
    for r in rows:
        sid = _stock_id_str(r[0])
        if sid:
            existing[sid] = (r[1], r[2], r[3], r[4])

    out_rows: list[tuple[str, str, str, str | None, str | None]] = []
    for sid, (macro, meso, old_micro, industry_raw) in existing.items():
        if sid in theme_lists:
            micro = _tags_to_db_micro(theme_lists[sid])
        else:
            micro = old_micro if old_micro is not None and str(old_micro).strip() else None
        raw_ind = industry_raw
        ind_str: str | None = (
            str(raw_ind).strip() if raw_ind is not None and str(raw_ind).strip() else None
        )
        out_rows.append(
            (
                sid,
                str(macro or "").strip() or "其他",
                str(meso or "").strip() or "其他",
                micro,
                ind_str,
            )
        )

    inserted = 0
    for sid, tags in theme_lists.items():
        if sid in existing:
            continue
        micro = _tags_to_db_micro(tags)
        if not micro:
            continue
        out_rows.append((sid, "其他", "其他", micro, None))
        inserted += 1

    n = writer.upsert_stock_sectors(out_rows)
    return n, inserted
