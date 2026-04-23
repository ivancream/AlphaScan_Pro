"""
從證交所公開資訊觀測站（MOPS）CSV 建構權證主檔列，供 ingest 腳本與 API 共用。

資料來源（UTF-8-sig）：
  - t187ap36_{L,O}.csv
  - t187ap37_{L,O}.csv
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

AP36_URLS = (
    ("TSE", "https://mopsfin.twse.com.tw/opendata/t187ap36_L.csv"),
    ("OTC", "https://mopsfin.twse.com.tw/opendata/t187ap36_O.csv"),
)
AP37_URLS = (
    ("TSE", "https://mopsfin.twse.com.tw/opendata/t187ap37_L.csv"),
    ("OTC", "https://mopsfin.twse.com.tw/opendata/t187ap37_O.csv"),
)

COL36_CODE = "權證代號"
COL36_NAME = "名稱"
COL36_UNDER = "標的代號"
COL36_UNDER_NAME = "標的名稱"

COL37_CODE = "權證代號"
COL37_NAME = "權證簡稱"
COL37_CP = "權證類型"
COL37_EXPIRY = "履約截止日"
COL37_STRIKE = "最新履約價格(元)/履約指數"
COL37_RATIO = "最新標的履約配發數量(每仟單位權證)"
COL37_UNDER_TEXT = "標的證券/指數"


def _fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "AlphaScanPro/1.0"})
    with urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8-sig")


def _parse_roc_yyyymmdd(raw: object) -> Optional[date]:
    s = str(raw or "").strip()
    if len(s) < 7 or not s[:7].isdigit():
        return None
    roc_y = int(s[:3])
    m = int(s[3:5])
    d = int(s[5:7])
    try:
        return date(roc_y + 1911, m, d)
    except ValueError:
        return None


def _parse_float(raw: object) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if not s:
        return None
    try:
        v = float(s)
        if v != v:
            return None
        return v
    except ValueError:
        return None


def _underlying_from_text(text: object) -> Optional[str]:
    s = str(text or "").strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})\b", s)
    if m:
        return m.group(1)
    return None


def _resolve_cp(cell: object) -> str:
    s = str(cell or "")
    if "售" in s:
        return "認售"
    return "認購"


def _exercise_ratio_from_delivery(delivery: Optional[float]) -> float:
    if delivery is None or delivery <= 0:
        return 1.0
    return float(delivery) / 1000.0


def _load_ap36(board: str, url: str) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    try:
        text = _fetch_text(url)
    except URLError:
        return out
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        code = str(row.get(COL36_CODE, "") or "").strip()
        if not code:
            continue
        u = str(row.get(COL36_UNDER, "") or "").strip()
        out[code] = {
            "underlying_symbol": u,
            "underlying_name": str(row.get(COL36_UNDER_NAME, "") or "").strip(),
            "warrant_name_36": str(row.get(COL36_NAME, "") or "").strip(),
            "board": board,
        }
    return out


def _load_ap37(board: str, url: str) -> List[Dict[str, Any]]:
    try:
        text = _fetch_text(url)
    except URLError:
        return []
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def build_warrant_master_rows() -> List[
    Tuple[str, str, str, Optional[str], str, float, float, date, str]
]:
    """
    回傳 upsert_warrant_master 所需 rows。
    下載失敗或欄位不完整時可能回傳空 list。
    """
    meta: Dict[str, Dict[str, str]] = {}
    for board, url in AP36_URLS:
        meta.update(_load_ap36(board, url))

    upsert_rows: List[Tuple[str, str, str, Optional[str], str, float, float, date, str]] = []

    for board, url in AP37_URLS:
        for row in _load_ap37(board, url):
            code = str(row.get(COL37_CODE, "") or "").strip()
            if not code:
                continue
            m = meta.get(code, {})
            underlying = str(m.get("underlying_symbol", "") or "").strip()
            if not underlying:
                underlying = _underlying_from_text(row.get(COL37_UNDER_TEXT)) or ""
            if not underlying:
                continue

            exp = _parse_roc_yyyymmdd(row.get(COL37_EXPIRY))
            if exp is None:
                continue

            strike = _parse_float(row.get(COL37_STRIKE))
            if strike is None or strike <= 0:
                continue

            delivery = _parse_float(row.get(COL37_RATIO))
            ratio = _exercise_ratio_from_delivery(delivery)

            name37 = str(row.get(COL37_NAME, "") or "").strip()
            name36 = str(m.get("warrant_name_36", "") or "").strip()
            warrant_name = name37 or name36 or code

            uname = str(m.get("underlying_name", "") or "").strip() or None
            cp = _resolve_cp(row.get(COL37_CP))
            row_board = str(m.get("board", "") or "").strip() or board

            upsert_rows.append(
                (
                    code,
                    warrant_name,
                    underlying,
                    uname,
                    cp,
                    float(strike),
                    float(ratio),
                    exp,
                    row_board,
                )
            )

    return upsert_rows
