"""
永豐金 Shioaji — 以 `api.snapshots(contracts)` 取得官方盤中/快照漲跌幅 (change_rate %)。

文件：https://sinotrade.github.io/tutor/market_data/snapshot/
每批最多 500 檔；未設定 SINOPAC_API_KEY 或連線失敗時回傳空 dict，由上層保留 DB 備援值。
"""
from __future__ import annotations

from typing import Dict, List

from backend.settings import get_sinopac_env, sinopac_credentials_configured

# Shioaji 文件：每批 snapshots 上限 500
_SNAPSHOT_BATCH = 450


def fetch_sinopac_change_pct_map(stock_ids: List[str]) -> Dict[str, float]:
    """
    依股票代號向永豐 API 取得 change_rate（百分比數值，例如 2.77 代表 2.77%）。
    失敗時回傳 {}。
    """
    if not stock_ids or not sinopac_credentials_configured():
        return {}

    # 去重、保留順序
    seen: set[str] = set()
    unique_ids: List[str] = []
    for sid in stock_ids:
        s = str(sid).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        unique_ids.append(s)

    if not unique_ids:
        return {}

    creds = get_sinopac_env()
    api = None
    out: Dict[str, float] = {}

    try:
        import shioaji as sj

        api = sj.Shioaji(simulation=creds["simulation"])
        api.login(
            api_key=creds["api_key"],
            secret_key=creds["secret_key"],
            fetch_contract=True,
        )

        for start in range(0, len(unique_ids), _SNAPSHOT_BATCH):
            chunk = unique_ids[start : start + _SNAPSHOT_BATCH]
            contracts = []
            for sid in chunk:
                try:
                    c = api.Contracts.Stocks.get(sid)
                except Exception:  # noqa: BLE001
                    c = None
                if c is not None:
                    contracts.append(c)

            if not contracts:
                continue

            try:
                snapshots = api.snapshots(contracts)
            except Exception as exc:  # noqa: BLE001
                print(f"[Sinopac snapshots] 批次失敗: {exc}")
                continue

            if not snapshots:
                continue

            for c, snap in zip(contracts, snapshots):
                if snap is None:
                    continue
                code = getattr(snap, "code", None) or getattr(c, "code", None)
                if not code:
                    continue
                code = str(code).strip()
                rate = getattr(snap, "change_rate", None)
                if rate is None:
                    continue
                try:
                    out[code] = float(rate)
                except (TypeError, ValueError):
                    continue

        if out:
            print(f"[Sinopac snapshots] 已取得 {len(out)} 檔漲跌幅 (change_rate)")
        return out

    except Exception as exc:  # noqa: BLE001
        print(f"[Sinopac snapshots] 無法取得漲跌幅: {exc}")
        return {}
    finally:
        if api is not None:
            try:
                api.logout()
            except Exception:  # noqa: BLE001
                pass


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

    ids = [str(r.get(key_symbol, "")).strip() for r in results_list if r.get(key_symbol)]
    pct_map = fetch_sinopac_change_pct_map(ids)
    if not pct_map:
        return

    for row in results_list:
        sid = str(row.get(key_symbol, "")).strip()
        if sid in pct_map:
            row[key_pct] = round(pct_map[sid], 2)
