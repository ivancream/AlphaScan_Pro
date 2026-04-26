"""
FinMind Trade API v4 client with hourly request rate limiting.

FinMind 免費／一般方案常見限制：每小時約 600 次 API 請求。
此模組以「滑動 1 小時視窗」計數，達上限時會 sleep 至最早一筆請求滾出視窗後再繼續。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Deque, Dict, List, Optional

import pandas as pd

FINMIND_BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# FinMind `name` -> 我們聚合用的法人分組（與 historical_chips 欄位對齊）
INVESTOR_NAME_TO_GROUP = {
    "Foreign_Investor": "foreign",
    "Foreign_Dealer_Self": "foreign",
    "Investment_Trust": "investment_trust",
    "Dealer_self": "dealer",
    "Dealer_Hedging": "dealer",
}


@dataclass
class HourlyWindowRateLimiter:
    """
    滑動 1 小時內最多允許 max_calls 次 acquire。
    超過時會 sleep 直到最舊的一筆記錄超出視窗，再繼續（優雅等待）。
    """

    max_calls: int = 600
    window_seconds: float = 3600.0
    _events: Deque[float] = field(default_factory=deque)
    _lock: Lock = field(default_factory=Lock)

    def acquire(self) -> None:
        """阻塞直到本次呼叫可在限制內執行。"""
        with self._lock:
            while True:
                now = time.monotonic()
                while self._events and now - self._events[0] >= self.window_seconds:
                    self._events.popleft()

                if len(self._events) < self.max_calls:
                    self._events.append(now)
                    return

                wait_s = self.window_seconds - (now - self._events[0]) + 0.05
                print(
                    f"[FinMind] 已達每小時 {self.max_calls} 次上限（滑動視窗 {self.window_seconds:.0f}s），"
                    f"等待 {wait_s:.1f}s 後繼續…"
                )
                time.sleep(max(wait_s, 0.1))
                now = time.monotonic()


class FinMindClient:
    """
    FinMind API v4 封裝（TaiwanStockInstitutionalInvestorsBuySell 等）。
    """

    def __init__(
        self,
        token: str,
        *,
        max_requests_per_hour: int = 600,
        min_interval_seconds: float = 0.05,
        timeout_seconds: float = 45.0,
    ) -> None:
        if not (token or "").strip():
            raise ValueError("FinMind token is empty; set FINMIND_API_TOKEN in .env")
        self._token = token.strip()
        self._limiter = HourlyWindowRateLimiter(max_calls=max(1, int(max_requests_per_hour)))
        self._min_interval = float(max(0.0, min_interval_seconds))
        self._timeout = float(timeout_seconds)
        self._last_request_mono: float = 0.0

    def _pace_min_interval(self) -> None:
        if self._min_interval <= 0:
            return
        now = time.monotonic()
        gap = now - self._last_request_mono
        if gap < self._min_interval:
            time.sleep(self._min_interval - gap)
        self._last_request_mono = time.monotonic()

    def _http_get_json(self, params: Dict[str, str]) -> dict:
        self._limiter.acquire()
        self._pace_min_interval()
        url = f"{FINMIND_BASE_URL}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "AlphaScan-Pro/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise RuntimeError(f"FinMind HTTP {exc.code}: {body[:500]}") from exc
        return json.loads(raw)

    def fetch_institutional_investors(
        self,
        symbol: str,
        start_date: str,
        end_date: Optional[str] = None,
    ) -> List[dict]:
        """
        呼叫 TaiwanStockInstitutionalInvestorsBuySell，回傳原始 data 陣列。

        Parameters
        ----------
        symbol:
            股票代碼（純數字，如 2330）。
        start_date / end_date:
            YYYY-MM-DD；end_date 預設為今天。
        """
        end = end_date or time.strftime("%Y-%m-%d", time.localtime())
        # v4 文件：個股查詢使用 data_id（股票代碼）
        params = {
            "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
            "data_id": str(symbol).strip(),
            "start_date": start_date,
            "end_date": end,
            "token": self._token,
        }
        payload = self._http_get_json(params)
        data = payload.get("data", [])
        if not isinstance(data, list):
            data = []
        # 少數環境仍接受 stock_id 參數；僅在 data_id 無列時再試一次（仍受同一套限流）
        if not data:
            params_alt = dict(params)
            params_alt.pop("data_id", None)
            params_alt["stock_id"] = str(symbol).strip()
            payload2 = self._http_get_json(params_alt)
            data2 = payload2.get("data", [])
            if isinstance(data2, list) and data2:
                return data2
        return data

    @staticmethod
    def institutional_rows_to_chips_dataframe(symbol: str, rows: List[dict]) -> pd.DataFrame:
        """
        將 FinMind 回傳列轉成 historical_chips 寬表（每日一列）。
        """
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df.columns = [str(c).strip() for c in df.columns]
        # 欄位別名相容（FinMind 版本差異）
        if "Trading_Volume" not in df.columns:
            for alt in ("trading_volume", "Trading_volume", "volume", "Volume"):
                if alt in df.columns:
                    df["Trading_Volume"] = df[alt]
                    break
        if "buy_sell" not in df.columns and "BuySell" in df.columns:
            df["buy_sell"] = df["BuySell"]

        required = {"date", "name", "buy_sell", "Trading_Volume"}
        if not required.issubset(df.columns):
            return pd.DataFrame()

        df = df[df["name"].isin(INVESTOR_NAME_TO_GROUP.keys())].copy()
        if df.empty:
            return pd.DataFrame()

        df["symbol"] = str(symbol).strip()
        df["investor_group"] = df["name"].map(INVESTOR_NAME_TO_GROUP)
        df["buy_sell"] = df["buy_sell"].astype(str).str.lower()
        df["Trading_Volume"] = pd.to_numeric(df["Trading_Volume"], errors="coerce").fillna(0.0)

        grouped = (
            df.groupby(["symbol", "date", "investor_group", "buy_sell"], as_index=False)["Trading_Volume"]
            .sum()
        )
        pivot = grouped.pivot_table(
            index=["symbol", "date"],
            columns=["investor_group", "buy_sell"],
            values="Trading_Volume",
            aggfunc="sum",
            fill_value=0.0,
        )
        pivot.columns = [f"{a}_{b}" for a, b in pivot.columns]
        pivot = pivot.reset_index()

        out = pd.DataFrame()
        out["symbol"] = pivot["symbol"].astype(str)
        out["date"] = pd.to_datetime(pivot["date"]).dt.normalize()
        for col in (
            "foreign_buy",
            "foreign_sell",
            "investment_trust_buy",
            "investment_trust_sell",
            "dealer_buy",
            "dealer_sell",
        ):
            out[col] = pd.to_numeric(pivot.get(col, 0), errors="coerce").fillna(0.0).round().astype("int64")
        out["total_shares_outstanding"] = pd.NA
        return out
