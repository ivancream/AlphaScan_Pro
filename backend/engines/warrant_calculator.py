from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Optional

from scipy.optimize import brentq

OptionSide = Literal["call", "put"]


@dataclass
class WarrantComputedMetrics:
    dte_days: int
    t_years: float
    moneyness_pct: Optional[float]
    spread_pct: Optional[float]
    bid_iv: Optional[float]
    ask_iv: Optional[float]
    bid_delta: Optional[float]
    ask_delta: Optional[float]
    bid_effective_gearing: Optional[float]
    ask_effective_gearing: Optional[float]
    spread_gearing_ratio_bid: Optional[float]
    spread_gearing_ratio_ask: Optional[float]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _safe_float(v: object) -> Optional[float]:
    try:
        if v is None:
            return None
        val = float(v)
        if not math.isfinite(val):
            return None
        return val
    except Exception:
        return None


def _to_option_side(cp: str) -> OptionSide:
    """
    支援常見輸入:
    - 認購 / call / C
    - 認售 / put / P
    """
    token = (cp or "").strip().lower()
    if token in {"認售", "put", "p"}:
        return "put"
    return "call"


def _calc_d1(
    s: float,
    k: float,
    t: float,
    r: float,
    sigma: float,
    q: float = 0.0,
) -> float:
    num = math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t
    den = sigma * math.sqrt(t)
    return num / den


def bs_price(
    *,
    side: OptionSide,
    s: float,
    k: float,
    t: float,
    r: float,
    sigma: float,
    q: float = 0.0,
) -> Optional[float]:
    if s <= 0 or k <= 0 or t <= 0 or sigma <= 0:
        return None

    try:
        d1 = _calc_d1(s=s, k=k, t=t, r=r, sigma=sigma, q=q)
        d2 = d1 - sigma * math.sqrt(t)
        disc_q = math.exp(-q * t)
        disc_r = math.exp(-r * t)

        if side == "call":
            return s * disc_q * _norm_cdf(d1) - k * disc_r * _norm_cdf(d2)
        return k * disc_r * _norm_cdf(-d2) - s * disc_q * _norm_cdf(-d1)
    except Exception:
        return None


def bs_delta(
    *,
    side: OptionSide,
    s: float,
    k: float,
    t: float,
    r: float,
    sigma: float,
    q: float = 0.0,
) -> Optional[float]:
    if s <= 0 or k <= 0 or t <= 0 or sigma <= 0:
        return None

    try:
        d1 = _calc_d1(s=s, k=k, t=t, r=r, sigma=sigma, q=q)
        disc_q = math.exp(-q * t)
        if side == "call":
            return disc_q * _norm_cdf(d1)
        return disc_q * (_norm_cdf(d1) - 1.0)
    except Exception:
        return None


def implied_volatility(
    *,
    market_price: float,
    side: OptionSide,
    s: float,
    k: float,
    t: float,
    r: float,
    q: float = 0.0,
    exercise_ratio: float = 1.0,
    sigma_low: float = 1e-4,
    sigma_high: float = 5.0,
) -> Optional[float]:
    """
    用 Brent root-finding 反推 Black-Scholes IV。

    權證市價對應 ``exercise_ratio * bs_price(…)``（每股選擇權理論價乘以行使比例），
    與台股權證報價單位一致；若省略 ``exercise_ratio`` 則視為 1（純選擇權）。
    """
    scale = _safe_float(exercise_ratio)
    if scale is None or scale <= 0:
        return None
    if market_price <= 0 or s <= 0 or k <= 0 or t <= 0:
        return None

    per_share = max(0.0, s - k) if side == "call" else max(0.0, k - s)
    intrinsic = scale * per_share
    if market_price + 1e-9 < intrinsic:
        return None

    def objective(sig: float) -> float:
        price = bs_price(side=side, s=s, k=k, t=t, r=r, sigma=sig, q=q)
        if price is None:
            return 1e9
        return scale * price - market_price

    try:
        low_val = objective(sigma_low)
        high_val = objective(sigma_high)
        if low_val == 0:
            return sigma_low
        if high_val == 0:
            return sigma_high
        if low_val * high_val > 0:
            return None
        iv = brentq(objective, sigma_low, sigma_high, maxiter=200, xtol=1e-8)
        if not math.isfinite(iv):
            return None
        return float(iv)
    except Exception:
        return None


def calc_moneyness_pct(side: OptionSide, s: float, k: float) -> Optional[float]:
    if s <= 0 or k <= 0:
        return None
    if side == "call":
        return ((s - k) / k) * 100.0
    return ((k - s) / k) * 100.0


def calc_spread_pct(bid: float, ask: float, last: float = 0.0) -> Optional[float]:
    sr = calc_spread_ratio_bid_ask(bid, ask)
    if sr is not None:
        return sr * 100.0
    lp = _safe_float(last) or 0.0
    if lp > 0 and bid >= 0 and bid <= lp:
        return ((lp - bid) / lp) * 100.0
    return None


def calc_spread_ratio_bid_ask(bid: float, ask: float) -> Optional[float]:
    """
    買賣價差比（小數，非百分比）::

        (委賣價 - 委買價) / 委賣價

    委賣價 ≤ 0、委買 < 0、或委買 > 委賣時回傳 None。
    """
    if ask <= 0 or bid < 0 or bid > ask:
        return None
    try:
        return (ask - bid) / ask
    except Exception:
        return None


def calc_effective_gearing(
    *,
    underlying_price: float,
    warrant_price: float,
    exercise_ratio: float,
    delta: Optional[float],
) -> Optional[float]:
    """
    實質槓桿（Effective Gearing）::

        (標的股價 / 權證價格) × 行使比例 × Delta

    買入權證時成本通常看 **委賣價 (Ask)**，請將 ``warrant_price`` 設為 Ask。

    若資料來源沒有 Delta，請先以 Black-Scholes（或本模組的 ``bs_delta`` /
    ``implied_volatility`` + ``compute_warrant_metrics``）反推，再帶入；此處
    ``delta is None`` 時回傳 None。
    """
    if delta is None:
        return None
    if underlying_price <= 0 or warrant_price <= 0 or exercise_ratio <= 0:
        return None
    try:
        return (underlying_price / warrant_price) * exercise_ratio * float(delta)
    except Exception:
        return None


def calc_spread_gearing_ratio(
    spread_pct: Optional[float],
    effective_gearing: Optional[float],
) -> Optional[float]:
    """
    相容舊式：以「價差百分比」除以實質槓桿（spread_pct 為 (ask-bid)/ask×100）。
    新邏輯請改用 :func:`calc_spread_gearing_ratio_decimal`。
    """
    if spread_pct is None or effective_gearing is None:
        return None
    if abs(effective_gearing) < 1e-15:
        return None
    try:
        return spread_pct / effective_gearing
    except Exception:
        return None


def calc_spread_gearing_ratio_decimal(
    spread_ratio: Optional[float],
    effective_gearing: Optional[float],
) -> Optional[float]:
    """
    差槓比（Spread / Gearing Ratio）::

        買賣價差比 / 實質槓桿

    其中買賣價差比為小數 :math:`(Ask - Bid) / Ask`，請先以
    :func:`calc_spread_ratio_bid_ask` 計算。

    實質槓桿為 0 或極接近 0、或輸入為 None 時回傳 None。
    """
    if spread_ratio is None or effective_gearing is None:
        return None
    if abs(effective_gearing) < 1e-15:
        return None
    try:
        return spread_ratio / effective_gearing
    except Exception:
        return None


def days_to_expiry(expiry: date | datetime, today: Optional[date] = None) -> int:
    base = today or date.today()
    exp = expiry.date() if isinstance(expiry, datetime) else expiry
    return max((exp - base).days, 0)


def dte_to_years(dte_days: int) -> float:
    # 避免 t=0 造成模型不可計算；最小給 1/365
    return max(dte_days / 365.0, 1.0 / 365.0)


def calc_spread_ratio_bid_ask_last(bid_p: float, ask_p: float, last_p: float) -> Optional[float]:
    """
    買賣價差比（小數）：有委賣用 (ask-bid)/ask；委賣為 0 時改以成交價 (last-bid)/last。
    """
    base = calc_spread_ratio_bid_ask(bid_p, ask_p)
    if base is not None:
        return base
    lp = _safe_float(last_p) or 0.0
    if lp <= 0 or bid_p < 0 or bid_p > lp:
        return None
    try:
        return (lp - bid_p) / lp
    except Exception:
        return None


def _buy_side_warrant_price(bid_p: float, ask_p: float, last_p: float) -> float:
    """買入參考權證價：委賣 > 0 優先，否則成交價，再否則委買（無掛賣時常見）。"""
    if ask_p > 0:
        return ask_p
    if last_p > 0:
        return last_p
    if bid_p > 0:
        return bid_p
    return 0.0


def _bid_leg_warrant_price(bid_p: float, last_p: float) -> float:
    """委買端權證價：委買為 0 時以成交價遞補。"""
    if bid_p > 0:
        return bid_p
    if last_p > 0:
        return last_p
    return 0.0


def _implied_vol_with_fallbacks(
    *,
    bid_p: float,
    ask_p: float,
    last_p: float,
    side: OptionSide,
    s: float,
    k: float,
    t_years: float,
    r: float,
    q: float,
    ratio: float,
) -> tuple[Optional[float], Optional[float]]:
    """
    先分別用委買／委賣反推 IV；失敗時以對側 IV、中價、成交價遞補，
    避免報價單邊為 0 或一側略低於理論內涵時整列槓桿／Delta 全空。
    """
    bid_iv: Optional[float] = None
    ask_iv: Optional[float] = None
    if bid_p > 0:
        bid_iv = implied_volatility(
            market_price=bid_p,
            side=side,
            s=s,
            k=k,
            t=t_years,
            r=r,
            q=q,
            exercise_ratio=ratio,
        )
    elif last_p > 0:
        bid_iv = implied_volatility(
            market_price=last_p,
            side=side,
            s=s,
            k=k,
            t=t_years,
            r=r,
            q=q,
            exercise_ratio=ratio,
        )
    if ask_p > 0:
        ask_iv = implied_volatility(
            market_price=ask_p,
            side=side,
            s=s,
            k=k,
            t=t_years,
            r=r,
            q=q,
            exercise_ratio=ratio,
        )
    elif last_p > 0:
        ask_iv = implied_volatility(
            market_price=last_p,
            side=side,
            s=s,
            k=k,
            t=t_years,
            r=r,
            q=q,
            exercise_ratio=ratio,
        )
    if bid_iv is None and ask_iv is not None:
        bid_iv = ask_iv
    if ask_iv is None and bid_iv is not None:
        ask_iv = bid_iv
    if bid_iv is None and ask_p > 0 and bid_p > 0:
        mid = 0.5 * (bid_p + ask_p)
        mid_iv = implied_volatility(
            market_price=mid,
            side=side,
            s=s,
            k=k,
            t=t_years,
            r=r,
            q=q,
            exercise_ratio=ratio,
        )
        if mid_iv is not None:
            bid_iv = bid_iv or mid_iv
            ask_iv = ask_iv or mid_iv
    if bid_iv is None and ask_iv is None and last_p > 0:
        last_iv = implied_volatility(
            market_price=last_p,
            side=side,
            s=s,
            k=k,
            t=t_years,
            r=r,
            q=q,
            exercise_ratio=ratio,
        )
        if last_iv is not None:
            bid_iv = last_iv
            ask_iv = last_iv
    return bid_iv, ask_iv


def compute_warrant_metrics(
    *,
    cp: str,
    strike: float,
    exercise_ratio: float,
    bid: float,
    ask: float,
    underlying_price: float,
    expiry_date: date | datetime,
    risk_free_rate: float = 0.015,
    dividend_yield: float = 0.0,
    today: Optional[date] = None,
    last: float = 0.0,
) -> WarrantComputedMetrics:
    """
    整合版計算入口，供 API 一次算出前端所需欄位。
    """
    side = _to_option_side(cp)
    s = _safe_float(underlying_price) or 0.0
    k = _safe_float(strike) or 0.0
    ratio = _safe_float(exercise_ratio) or 0.0
    bid_p = _safe_float(bid) or 0.0
    ask_p = _safe_float(ask) or 0.0
    last_p = _safe_float(last) or 0.0
    r = _safe_float(risk_free_rate) or 0.015
    q = _safe_float(dividend_yield) or 0.0

    dte_days = days_to_expiry(expiry_date, today=today)
    t_years = dte_to_years(dte_days)

    moneyness_pct = calc_moneyness_pct(side, s, k)
    spread_pct = calc_spread_pct(bid_p, ask_p, last_p)

    buy_px = _buy_side_warrant_price(bid_p, ask_p, last_p)
    bid_leg_px = _bid_leg_warrant_price(bid_p, last_p)

    bid_iv, ask_iv = _implied_vol_with_fallbacks(
        bid_p=bid_p,
        ask_p=ask_p,
        last_p=last_p,
        side=side,
        s=s,
        k=k,
        t_years=t_years,
        r=r,
        q=q,
        ratio=ratio,
    )

    bid_delta = (
        bs_delta(side=side, s=s, k=k, t=t_years, r=r, sigma=bid_iv, q=q)
        if bid_iv
        else None
    )
    ask_delta = (
        bs_delta(side=side, s=s, k=k, t=t_years, r=r, sigma=ask_iv, q=q)
        if ask_iv
        else None
    )

    # 市價低於歐式理論下界（深度價內、報價失真）時 IV 不存在；用固定波動率僅供
    # Delta／槓桿顯示，避免整表空白（數值僅供排序參考，非可交易 IV）。
    if bid_delta is None and ask_delta is None and s > 0 and k > 0 and t_years > 0:
        sigma_fb = 0.35
        bid_delta = bs_delta(side=side, s=s, k=k, t=t_years, r=r, sigma=sigma_fb, q=q)
        ask_delta = bs_delta(side=side, s=s, k=k, t=t_years, r=r, sigma=sigma_fb, q=q)

    bid_effective_gearing = calc_effective_gearing(
        underlying_price=s,
        warrant_price=bid_leg_px,
        exercise_ratio=ratio,
        delta=bid_delta,
    )
    ask_effective_gearing = calc_effective_gearing(
        underlying_price=s,
        warrant_price=buy_px,
        exercise_ratio=ratio,
        delta=ask_delta,
    )

    spread_ratio_dec = calc_spread_ratio_bid_ask_last(bid_p, ask_p, last_p)
    spread_gearing_ratio_bid = calc_spread_gearing_ratio_decimal(
        spread_ratio_dec, bid_effective_gearing
    )
    spread_gearing_ratio_ask = calc_spread_gearing_ratio_decimal(
        spread_ratio_dec, ask_effective_gearing
    )

    return WarrantComputedMetrics(
        dte_days=dte_days,
        t_years=t_years,
        moneyness_pct=moneyness_pct,
        spread_pct=spread_pct,
        bid_iv=bid_iv,
        ask_iv=ask_iv,
        bid_delta=bid_delta,
        ask_delta=ask_delta,
        bid_effective_gearing=bid_effective_gearing,
        ask_effective_gearing=ask_effective_gearing,
        spread_gearing_ratio_bid=spread_gearing_ratio_bid,
        spread_gearing_ratio_ask=spread_gearing_ratio_ask,
    )


if __name__ == "__main__":
    # 測試範例：標的股價 100、委賣 1.0、委買 0.98、行使比例 0.1、Delta 0.5
    _S, _ask, _bid, _ratio, _dlt = 100.0, 1.0, 0.98, 0.1, 0.5
    _eg = calc_effective_gearing(
        underlying_price=_S,
        warrant_price=_ask,
        exercise_ratio=_ratio,
        delta=_dlt,
    )
    _sr = calc_spread_ratio_bid_ask(_bid, _ask)
    _sgr = calc_spread_gearing_ratio_decimal(_sr, _eg)
    print("實質槓桿（權證價=委賣 Ask）:", _eg)
    print("買賣價差比 (Ask-Bid)/Ask:", _sr)
    print("差槓比（價差比 / 實質槓桿）:", _sgr)
    assert _eg is not None and abs(_eg - 5.0) < 1e-9
    assert _sr is not None and abs(_sr - 0.02) < 1e-9
    assert _sgr is not None and abs(_sgr - 0.004) < 1e-9
    assert (
        calc_effective_gearing(
            underlying_price=100.0,
            warrant_price=1.0,
            exercise_ratio=0.1,
            delta=None,
        )
        is None
    ), "無 Delta 時應回傳 None；需先以 Black-Scholes 反推 Delta 再代入。"
    assert calc_spread_gearing_ratio_decimal(0.02, 0.0) is None
    print("assert 全部通過。")
