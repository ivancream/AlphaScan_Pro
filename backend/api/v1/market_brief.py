"""
大盤氣氛：加權指數、台指期、權值股彙總。

優先使用永豐 Shioaji 盤中 snapshots（加權 TSE001、TXF 近月、權值股批次）。
未設定憑證或連線失敗時降級為 yfinance。
走勢圖 series 仍可能由 yfinance 分鐘線補充（僅輔助視覺，與表頭即時快照可能略有時間差）。

權重為近似市值權重，僅供「一眼判讀」排序與估算貢獻，非證交所官方精算。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf
from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.db import queries as _db_queries

router = APIRouter()

# 近似加權指數成分權重（僅供 UI 估算貢獻，會隨時間漂移）
_INDEX_WEIGHTS: Dict[str, float] = {
    "2330": 0.30,
    "2317": 0.022,
    "2454": 0.018,
    "2308": 0.012,
    "2881": 0.015,
    "2882": 0.014,
    "2412": 0.008,
    "3008": 0.010,
}

_STOCK_IDS = list(_INDEX_WEIGHTS.keys())
_STOCK_TICKERS = [f"{s}.TW" for s in _STOCK_IDS]

# 台指期走勢：優先 TIP 台指期相關指數（Yahoo 常態有資料），其次為美元報價近月代碼
_FUT_CANDIDATES = ("IX0126.TW", "TXFF=F", "TXF=F")


class IntradayStrip(BaseModel):
    last: Optional[float] = None
    change_pct: Optional[float] = None
    series: List[float] = Field(default_factory=list)


class FuturesStrip(BaseModel):
    symbol: Optional[str] = None
    last: Optional[float] = None
    change_pct: Optional[float] = None
    basis_points: Optional[float] = Field(
        default=None,
        description="期現價差（點）：台指期最後價 − 加權指數最後價，正為正價差",
    )
    series: List[float] = Field(default_factory=list)


class WeightStockRow(BaseModel):
    stock_id: str
    name: str
    last: Optional[float] = None
    change_pct: Optional[float] = None
    weight_pct: float = Field(description="近似權重（百分比顯示用，如 30 代表 30%）")
    contrib_points: Optional[float] = Field(
        default=None,
        description="估算點數貢獻：加權指數 × 權重 × (漲跌幅/100)",
    )


class TaiexOverviewResponse(BaseModel):
    updated_at: str
    market_bias: str = Field(description="偏多 / 偏空 / 盤整（啟發式）")
    taiex: IntradayStrip
    futures: FuturesStrip
    stocks: List[WeightStockRow]
    error: Optional[str] = None
    data_source: str = Field(
        default="yfinance",
        description="sinopac=永豐盤中快照；yfinance=降級",
    )
    series_source: Optional[str] = Field(
        default=None,
        description="走勢圖序列來源（若為 yfinance 則可能延遲）",
    )


def _flatten_close_col(df: pd.DataFrame, ticker: str, many: bool) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=float)
    try:
        if many and isinstance(df.columns, pd.MultiIndex):
            return df[ticker]["Close"].dropna()
        return df["Close"].dropna()
    except Exception:  # noqa: BLE001
        return pd.Series(dtype=float)


def _last_vs_prev_close(series: pd.Series) -> Tuple[Optional[float], Optional[float]]:
    """取序列最後收盤與前一日（前一資料點）漲跌幅 %。"""
    if series is None or series.empty:
        return None, None
    c = series.dropna()
    if c.empty:
        return None, None
    last = float(c.iloc[-1])
    if len(c) < 2:
        return last, None
    prev = float(c.iloc[-2])
    if prev == 0:
        return last, None
    return last, round((last - prev) / prev * 100.0, 2)


def _daily_last_change_yf(ticker: str) -> Tuple[Optional[float], Optional[float]]:
    """以日線收盤計算最新價與漲跌幅（較適合非交易時段與假日）。"""
    try:
        h = yf.Ticker(ticker).history(period="14d", interval="1d", auto_adjust=True)
        if h is None or h.empty or "Close" not in h.columns:
            return None, None
        return _last_vs_prev_close(h["Close"])
    except Exception:  # noqa: BLE001
        return None, None


def _download_1m(symbols: List[str]) -> Tuple[pd.DataFrame, bool]:
    if not symbols:
        return pd.DataFrame(), False
    many = len(symbols) > 1
    try:
        raw = yf.download(
            " ".join(symbols),
            period="5d",
            interval="1m",
            progress=False,
            group_by="ticker",
            threads=True,
        )
        if raw is None or raw.empty:
            return pd.DataFrame(), False
        if isinstance(raw.columns, pd.MultiIndex):
            try:
                raw.columns = raw.columns.remove_unused_levels()
            except Exception:  # noqa: BLE001
                pass
        return raw, many
    except Exception:  # noqa: BLE001
        return pd.DataFrame(), False


def _series_list(series: pd.Series, cap: int = 80) -> List[float]:
    if series is None or series.empty:
        return []
    tail = series.dropna().tail(cap)
    return [round(float(x), 2) for x in tail.tolist()]


def _load_stock_names() -> Dict[str, str]:
    out = {sid: sid for sid in _STOCK_IDS}
    try:
        df = _db_queries.get_stock_info_df()
        if df is None or df.empty:
            return out
        for _, row in df.iterrows():
            sid = str(row.get("stock_id", "")).strip()
            if sid in out and row.get("name"):
                out[sid] = str(row["name"])
    except Exception:  # noqa: BLE001
        pass
    return out


def _pick_futures_symbol() -> Optional[str]:
    for sym in _FUT_CANDIDATES:
        last, _ = _daily_last_change_yf(sym)
        if last is not None:
            return sym
    return None


def _download_daily(symbols: List[str]) -> Tuple[pd.DataFrame, bool]:
    if not symbols:
        return pd.DataFrame(), False
    many = len(symbols) > 1
    try:
        raw = yf.download(
            " ".join(symbols),
            period="14d",
            interval="1d",
            progress=False,
            group_by="ticker",
            threads=True,
        )
        if raw is None or raw.empty:
            return pd.DataFrame(), False
        if isinstance(raw.columns, pd.MultiIndex):
            try:
                raw.columns = raw.columns.remove_unused_levels()
            except Exception:  # noqa: BLE001
                pass
        return raw, many
    except Exception:  # noqa: BLE001
        return pd.DataFrame(), False


def _market_bias(twii_pct: Optional[float], basis: Optional[float]) -> str:
    if twii_pct is None:
        return "盤整"
    if twii_pct >= 0.25 and (basis is None or basis >= -20):
        return "偏多"
    if twii_pct <= -0.25 and (basis is None or basis <= 20):
        return "偏空"
    if abs(twii_pct) < 0.08:
        return "盤整"
    return "中性"


def _parse_snap_price_pct(snap: Any) -> Tuple[Optional[float], Optional[float]]:
    if snap is None:
        return None, None
    try:
        cl = float(getattr(snap, "close", 0) or 0)
        chg = float(getattr(snap, "change_rate", 0) or 0)
        if cl <= 0:
            return None, None
        return round(cl, 2), round(chg, 2)
    except (TypeError, ValueError):
        return None, None


def _pick_taiex_index_contract(api: Any) -> Any:
    try:
        tse = api.Contracts.Indexs.TSE
        return tse.get("TSE001") or tse["TSE001"]
    except Exception:  # noqa: BLE001
        return None


def _pick_near_txf_contract(api: Any) -> Any:
    try:
        txf_ns = api.Contracts.Futures.TXF
        contracts = sorted(
            list(txf_ns),
            key=lambda c: str(getattr(c, "delivery_date", "9999")),
        )
        return contracts[0] if contracts else None
    except Exception:  # noqa: BLE001
        return None


def _build_sinopac_overview(
    names: Dict[str, str],
    err_parts: List[str],
) -> Optional[Tuple[IntradayStrip, FuturesStrip, List[WeightStockRow]]]:
    from backend.settings import sinopac_credentials_configured
    from backend.engines.sinopac_session import sinopac_session

    if not sinopac_credentials_configured():
        return None
    if not sinopac_session.is_connected:
        sinopac_session.connect()
    api = sinopac_session.api
    if api is None:
        err_parts.append("sinopac:未連線")
        return None

    idx_c = _pick_taiex_index_contract(api)
    fut_c = _pick_near_txf_contract(api)
    if idx_c is None:
        err_parts.append("sinopac:無加權指數契約")
        return None

    contracts = [idx_c]
    if fut_c is not None:
        contracts.append(fut_c)

    try:
        snaps = api.snapshots(contracts)
    except Exception as exc:  # noqa: BLE001
        err_parts.append(f"sinopac_snapshots:{exc}")
        return None

    snap_idx = snaps[0] if snaps else None
    snap_fut = snaps[1] if len(snaps) > 1 else None

    taiex = IntradayStrip()
    last_i, pct_i = _parse_snap_price_pct(snap_idx)
    taiex.last = last_i
    taiex.change_pct = pct_i

    fut_block = FuturesStrip()
    if fut_c is not None and snap_fut is not None:
        last_f, pct_f = _parse_snap_price_pct(snap_fut)
        fut_block.symbol = str(getattr(fut_c, "code", "") or "")
        fut_block.last = last_f
        fut_block.change_pct = pct_f
        if last_i is not None and last_f is not None:
            fut_block.basis_points = round(float(last_f) - float(last_i), 2)

    ohlcv = sinopac_session.get_ohlcv_map(_STOCK_IDS)
    stocks: List[WeightStockRow] = []
    spot_last = last_i
    for sid in _STOCK_IDS:
        w = _INDEX_WEIGHTS.get(sid, 0.0)
        w_pct = round(w * 100.0, 2)
        row = ohlcv.get(sid)
        if row:
            last_s = round(float(row["Close"]), 2)
            pct_s = round(float(row["ChangeRate"]), 2)
        else:
            last_s, pct_s = None, None
        contrib = None
        if spot_last is not None and pct_s is not None:
            contrib = round(float(spot_last) * w * (pct_s / 100.0), 3)
        stocks.append(
            WeightStockRow(
                stock_id=sid,
                name=names.get(sid, sid),
                last=last_s,
                change_pct=pct_s,
                weight_pct=w_pct,
                contrib_points=contrib,
            )
        )

    if taiex.last is None:
        return None

    return taiex, fut_block, stocks


def _append_yf_series_for_charts(
    taiex: IntradayStrip,
    fut_block: FuturesStrip,
    err_parts: List[str],
) -> Optional[str]:
    """走勢圖仍以 yfinance 分鐘線補形狀（與表頭永豐快照可能略有時間差）。"""
    try:
        raw_tw, many_tw = _download_1m(["^TWII"])
        s_tw = _flatten_close_col(raw_tw, "^TWII", many_tw)
        taiex.series = _series_list(s_tw)
    except Exception as exc:  # noqa: BLE001
        err_parts.append(f"yf_series_twii:{exc}")

    fut_sym = _pick_futures_symbol()
    try:
        if fut_sym:
            raw_f, many_f = _download_1m([fut_sym])
            s_f = _flatten_close_col(raw_f, fut_sym, many_f)
            fut_block.series = _series_list(s_f)
    except Exception as exc:  # noqa: BLE001
        err_parts.append(f"yf_series_fut:{exc}")

    return "yfinance"


@router.get("/api/v1/market/taiex-overview", response_model=TaiexOverviewResponse)
def get_taiex_overview() -> TaiexOverviewResponse:
    updated = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    err_parts: List[str] = []
    names = _load_stock_names()

    sp = _build_sinopac_overview(names, err_parts)
    if sp is not None:
        taiex, fut_block, stocks = sp
        series_src = _append_yf_series_for_charts(taiex, fut_block, err_parts)
        bias = _market_bias(taiex.change_pct, fut_block.basis_points)
        return TaiexOverviewResponse(
            updated_at=updated,
            market_bias=bias,
            taiex=taiex,
            futures=fut_block,
            stocks=stocks,
            error="; ".join(err_parts) if err_parts else None,
            data_source="sinopac",
            series_source=series_src,
        )

    # ── yfinance 降級（無永豐或快照失敗）──────────────────────────────
    taiex = IntradayStrip()
    fut_block = FuturesStrip()
    stocks: List[WeightStockRow] = []

    spot_last: Optional[float] = None

    try:
        last_tw, pct_tw = _daily_last_change_yf("^TWII")
        taiex.last = last_tw
        taiex.change_pct = pct_tw
        spot_last = last_tw
        raw_tw, many_tw = _download_1m(["^TWII"])
        s_tw = _flatten_close_col(raw_tw, "^TWII", many_tw)
        taiex.series = _series_list(s_tw)
    except Exception as exc:  # noqa: BLE001
        err_parts.append(f"twii:{exc}")

    fut_sym = _pick_futures_symbol()
    try:
        if fut_sym:
            fut_block.symbol = fut_sym
            last_f, pct_f = _daily_last_change_yf(fut_sym)
            fut_block.last = last_f
            fut_block.change_pct = pct_f
            raw_f, many_f = _download_1m([fut_sym])
            s_f = _flatten_close_col(raw_f, fut_sym, many_f)
            fut_block.series = _series_list(s_f)
            if (
                spot_last is not None
                and last_f is not None
                and fut_sym not in ("IX0126.TW",)
            ):
                fut_block.basis_points = round(float(last_f) - float(spot_last), 2)
    except Exception as exc:  # noqa: BLE001
        err_parts.append(f"futures:{exc}")

    try:
        raw_d, many_d = _download_daily(_STOCK_TICKERS)
        raw_m, many_m = _download_1m(_STOCK_TICKERS)
        for sid in _STOCK_IDS:
            tkr = f"{sid}.TW"
            daily_ser = _flatten_close_col(raw_d, tkr, many_d)
            last_s, pct_s = _last_vs_prev_close(daily_ser)
            intra_s = _flatten_close_col(raw_m, tkr, many_m)
            if last_s is None and intra_s is not None and not intra_s.empty:
                last_s = float(intra_s.iloc[-1])
            w = _INDEX_WEIGHTS.get(sid, 0.0)
            w_pct = round(w * 100.0, 2)
            contrib = None
            if spot_last is not None and pct_s is not None:
                contrib = round(float(spot_last) * w * (pct_s / 100.0), 3)
            stocks.append(
                WeightStockRow(
                    stock_id=sid,
                    name=names.get(sid, sid),
                    last=last_s,
                    change_pct=pct_s,
                    weight_pct=w_pct,
                    contrib_points=contrib,
                )
            )
    except Exception as exc:  # noqa: BLE001
        err_parts.append(f"stocks:{exc}")

    bias = _market_bias(taiex.change_pct, fut_block.basis_points)

    return TaiexOverviewResponse(
        updated_at=updated,
        market_bias=bias,
        taiex=taiex,
        futures=fut_block,
        stocks=stocks,
        error="; ".join(err_parts) if err_parts else None,
        data_source="yfinance",
        series_source="yfinance",
    )
