"""
永豐金 Shioaji Snapshot 工具函式

【架構說明】
本模組不再自行建立 Shioaji Session（已移除 login/logout per-call 設計）。
所有呼叫都委派給 sinopac_session（全域共享連線）。

【volume 換算說明（來自 Shioaji 官方文件）】
  snap.volume      = 最後一筆的成交張數（例如 48 張）← 日K 不能用這個
  snap.total_volume = 當日累積成交張數（例如 77,606 張）← 日K 要用這個
  daily_price 表的 volume 欄位以「股」(share) 儲存（1張 = 1000股），
  因此回傳 Volume = total_volume × 1000 以保持一致。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from backend.engines.sinopac_session import sinopac_session


def fetch_sinopac_ohlcv_map(stock_ids: List[str]) -> Dict[str, Dict]:
    """
    批次取得盤中 OHLCV 快照（委派給共享 Session）。

    回傳格式::

        {
            "2330": {
                "Open": 580.0, "High": 590.0, "Low": 578.0,
                "Close": 585.0,
                "Volume": 77_606_000.0,  # total_volume（張）× 1000 → 股
                "ChangeRate": 2.77,
            },
            ...
        }

    若 sinopac_session 未連線（API Key 未設定或登入失敗），回傳 {}。
    """
    if not sinopac_session.is_connected:
        return {}
    return sinopac_session.get_ohlcv_map(stock_ids)


def fetch_sinopac_change_pct_map(stock_ids: List[str]) -> Dict[str, float]:
    """
    批次取得 change_rate（漲跌幅 %）。

    回傳 {stock_id: change_rate}，例如 {"2330": 2.77}。
    若 sinopac_session 未連線，回傳 {}。
    """
    if not sinopac_session.is_connected:
        return {}
    return sinopac_session.get_change_pct_map(stock_ids)


def fetch_single_stock_ohlcv(stock_id: str) -> Optional[Dict]:
    """
    取得單支股票的盤中 OHLCV 快照，供 engine_technical.fetch_data() 補今日 K 棒使用。
    失敗時回傳 None。
    """
    result = fetch_sinopac_ohlcv_map([str(stock_id).strip()])
    return result.get(str(stock_id).strip())


def merge_sinopac_change_pct_into_rows(
    results_list: List[dict],
    key_symbol: str = "代號",
    key_pct: str = "今日漲跌幅(%)",
) -> None:
    """
    就地更新選股結果列：以永豐 snapshots 的 change_rate 覆寫漲跌幅。
    若 API 無資料或該檔未回傳，保留原有（多為 DB 兩日收盤推算）數值。
    """
    if not results_list:
        return

    ids = [
        str(r.get(key_symbol, "")).strip()
        for r in results_list
        if r.get(key_symbol)
    ]
    pct_map = fetch_sinopac_change_pct_map(ids)
    if not pct_map:
        return

    for row in results_list:
        sid = str(row.get(key_symbol, "")).strip()
        if sid in pct_map:
            row[key_pct] = round(pct_map[sid], 2)
