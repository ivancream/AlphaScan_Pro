"""
從公開資訊觀測站 t187 上市公司／上櫃公司 CSV 匯入產業別 → DuckDB stock_sectors。

執行：
    python -m backend.scripts.refresh_stock_sectors_twse

DuckDB 連線為「用完即關」，FastAPI 未在處理請求時檔案鎖會釋放，獨立程序可寫入；若仍遇鎖定，connect 會自動重試數次。

排程：見 backend.scheduler job_stock_sectors_refresh
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import urllib.request

from backend.db import writer
from backend.db.writer import log_update_error
from backend.db.sector_micro_sync import apply_theme_json_to_stock_sectors
from backend.engines.theme_loader import THEMES_JSON, load_json_theme_micro_lists
from backend.scripts.industry_codes import industry_name

TSE_CSV = "https://mopsfin.twse.com.tw/opendata/t187ap03_L.csv"
OTC_CSV = "https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv"


def _fetch_csv(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "AlphaScanPro/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8")


def _parse_rows(csv_text: str) -> list[dict[str, Any]]:
    # 處理 BOM
    if csv_text.startswith("\ufeff"):
        csv_text = csv_text[1:]
    reader = csv.DictReader(io.StringIO(csv_text))
    return list(reader)


def _norm_keys(row: dict) -> dict[str, str]:
    """統一欄位名（含 BOM 的 出表日期）。"""
    out: dict[str, str] = {}
    for k, v in row.items():
        nk = k.lstrip("\ufeff").strip()
        out[nk] = (v or "").strip() if v is not None else ""
    return out


def _tags_to_db_micro(tags: list[str]) -> str | None:
    if not tags:
        return None
    if len(tags) == 1:
        return tags[0]
    return "、".join(tags)


def run_stock_sectors_refresh() -> int:
    print("[StockSectors] Downloading TWSE / TPEx CSV …")
    try:
        import twstock

        tw_codes = twstock.codes
    except Exception:
        tw_codes = {}

    theme_lists = load_json_theme_micro_lists()

    all_rows: list[tuple[str, str, str, str | None, str]] = []
    seen: set[str] = set()

    for url, label in ((TSE_CSV, "上市"), (OTC_CSV, "上櫃")):
        try:
            text = _fetch_csv(url)
        except Exception as exc:
            print(f"[StockSectors] Failed {label}: {exc}")
            continue
        for raw in _parse_rows(text):
            row = _norm_keys(raw)
            sid = row.get("公司代號", "").strip()
            if not sid or not sid.isdigit():
                continue
            code = row.get("產業別", "").strip()
            raw_industry = code
            name_cn = industry_name(code) or "其他"

            tw = tw_codes.get(sid) if sid in tw_codes else None
            tw_group = getattr(tw, "group", None) if tw else None
            tw_group = (tw_group or "").strip() or None

            macro = name_cn
            meso = tw_group if tw_group else macro

            tags = theme_lists.get(sid)
            micro = _tags_to_db_micro(tags) if tags else None

            if sid in seen:
                continue
            seen.add(sid)
            all_rows.append((sid, macro, meso, micro, raw_industry))

    if not all_rows:
        log_update_error("stock_sectors", "no rows from CSV")
        print("[StockSectors] No rows imported.")
        return 0

    n = writer.upsert_stock_sectors(all_rows)
    print(f"[StockSectors] Upserted {n} rows (TWSE industry + themes).")
    t_n, t_ins = apply_theme_json_to_stock_sectors()
    print(
        f"[StockSectors] Theme micro sync: {t_n} rows "
        f"(theme-only inserts: {t_ins}; theme.json + stock_themes.json → micro)."
    )
    return n


def _ensure_example_themes_file() -> None:
    """若不存在則建立空 stock_themes.json（不覆寫既有檔）。"""
    THEMES_JSON.parent.mkdir(parents=True, exist_ok=True)
    if THEMES_JSON.exists():
        return
    THEMES_JSON.write_text('{\n  "themes": {}\n}\n', encoding="utf-8")
    print(f"[StockSectors] Created {THEMES_JSON}")


if __name__ == "__main__":
    _ensure_example_themes_file()
    run_stock_sectors_refresh()
