"""
Centralized data-update scheduler for AlphaScan Pro.

Replaces the ad-hoc asyncio loops previously in intraday.py and
engine_intraday_scanner.py, and adds proper scheduling for data sources
that previously had no automatic refresh.

Schedule (Asia/Taipei):
  Every 5 min  (09:00–13:35)  intraday daily_prices snapshot
  Every 5 min  (09:00–13:35)  capital flow (theme.json delta volume → Discord if ignite)
  Every 30 min (09:00–13:35)  technical scanner
  Every 5 min  (09:05–13:30, weekdays)  technical scanner + Discord（盤中即時，含防洗版）
  14:00  weekdays             reset intraday alert counter (daily_alerts_count)
  14:05  once/trading-day     post-close OHLCV settle
  15:05  once/trading-day     disposition events refresh
  02:00  daily                dividend backfill (yfinance, yearly guard)
  03:00  weekly (Saturday)    correlation matrix rebuild
  03:00  weekly (Monday)      stock universe (stock_info) refresh
  08:00  daily (weekdays)     TWSE/TPEx industry → stock_sectors
  09:30  weekdays             morning theme brief (Discord)
"""

import asyncio
import datetime
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

_TZ = ZoneInfo("Asia/Taipei")
_scheduler: AsyncIOScheduler | None = None
_log = logging.getLogger(__name__)

# Guard: post-close job runs at most once per calendar day
_last_post_close_date: str | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _is_trading_day() -> bool:
    """True on Mon–Fri. Does not account for public holidays."""
    return datetime.datetime.now(_TZ).weekday() < 5


def _is_market_hours() -> bool:
    now = datetime.datetime.now(_TZ)
    if not _is_trading_day():
        return False
    o = now.replace(hour=9,  minute=0,  second=0, microsecond=0)
    c = now.replace(hour=13, minute=35, second=0, microsecond=0)
    return o <= now <= c


def _is_intraday_alert_window() -> bool:
    """盤中即時警報輪詢視窗：週一至週五 09:05–13:30（台北）。"""
    now = datetime.datetime.now(_TZ)
    if not _is_trading_day():
        return False
    o = now.replace(hour=9, minute=5, second=0, microsecond=0)
    c = now.replace(hour=13, minute=30, second=0, microsecond=0)
    return o <= now <= c


async def _run_scan_notify_with_intraday_record() -> None:
    """執行盤中掃描、推送 Discord（若佇列有資料）、並更新防洗版計數。"""
    from backend.engines.cache_store import IntradayAlertCounter
    from backend.engines.engine_intraday_scanner import run_scan, pop_pending_scan_notify
    from backend.engines import notifier as _notifier

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, run_scan)

    pending = pop_pending_scan_notify()
    if not pending:
        return
    try:
        res = await _notifier.notify_scan_results(
            results_long=pending["long"],
            results_short=pending["short"],
            scan_id=pending["scan_id"],
            scan_time=pending["scan_time"],
            only_new_triggers=pending.get("only_new_triggers", False),
            results_wanderer=pending.get("wanderer"),
        )
        IntradayAlertCounter.apply_after_discord_notify(res, pending)
    except Exception as notify_exc:
        _log.error("[Scheduler] scanner Discord notify failed: %s", notify_exc)


# ──────────────────────────────────────────────────────────────────────────────
# Job functions
# ──────────────────────────────────────────────────────────────────────────────

async def job_intraday_update() -> None:
    """Snapshot intraday OHLCV — every 5 min, self-guarded to market hours."""
    if not _is_market_hours():
        return
    _log.info("[Scheduler] intraday_update: starting")
    loop = asyncio.get_event_loop()
    try:
        from backend.api.v1.intraday import _run_intraday_update
        await loop.run_in_executor(None, _run_intraday_update)
    except Exception as exc:
        _log.error("[Scheduler] intraday_update failed: %s", exc)


async def job_capital_flow() -> None:
    """5 分鐘盤中族群資金流量監控（方法 A），符合點火條件時發 Discord。"""
    if not _is_market_hours():
        return
    _log.info("[Scheduler] capital_flow: starting")
    loop = asyncio.get_event_loop()
    try:
        from backend.engines.engine_capital_flow import run_capital_flow_tick
        from backend.engines import notifier as _notifier

        alerts = await loop.run_in_executor(None, run_capital_flow_tick)
        if alerts:
            await _notifier.notify_capital_flow_ignites(alerts)
    except Exception as exc:
        _log.error("[Scheduler] capital_flow failed: %s", exc)


async def job_post_close_update() -> None:
    """Post-close OHLCV settle — once per trading day at 14:05.
    Uses yfinance to write ALL stocks' daily OHLCV for the full market.
    """
    global _last_post_close_date
    if not _is_trading_day():
        return
    today = datetime.datetime.now(_TZ).date().isoformat()
    if _last_post_close_date == today:
        return
    _log.info("[Scheduler] post_close_update: starting (full-market yfinance)")
    loop = asyncio.get_event_loop()
    try:
        from backend.api.v1.intraday import _backfill_via_yfinance
        from backend.db import queries
        stock_df = queries.get_active_stocks()
        await loop.run_in_executor(
            None, _backfill_via_yfinance, stock_df, "5d"
        )
        _last_post_close_date = today
    except Exception as exc:
        _log.error("[Scheduler] post_close_update failed: %s", exc)


async def job_scanner() -> None:
    """Technical scanner (long/short/wanderer) — every 30 min, market hours only."""
    if not _is_market_hours():
        return
    _log.info("[Scheduler] scanner: starting")
    try:
        await _run_scan_notify_with_intraday_record()
    except Exception as exc:
        _log.error("[Scheduler] scanner failed: %s", exc)


async def job_intraday_scanner_alerts() -> None:
    """盤中即時：交易日 09:05–13:30 每 5 分鐘掃描並推送（防洗版於掃描器內過濾）。"""
    if not _is_intraday_alert_window():
        return
    _log.info("[Scheduler] intraday_scanner_alerts: starting")
    try:
        await _run_scan_notify_with_intraday_record()
    except Exception as exc:
        _log.error("[Scheduler] intraday_scanner_alerts failed: %s", exc)


async def job_intraday_alert_counter_reset() -> None:
    """每日 14:00 清空盤中警報防洗版計數，迎接下一交易日。"""
    if not _is_trading_day():
        return
    _log.info("[Scheduler] intraday_alert_counter_reset: clearing")
    try:
        from backend.engines.cache_store import IntradayAlertCounter

        IntradayAlertCounter.clear_all()
    except Exception as exc:
        _log.error("[Scheduler] intraday_alert_counter_reset failed: %s", exc)


async def job_disposition_refresh() -> None:
    """Refresh disposition list from TWSE/TPEx — once per trading day at 15:05."""
    if not _is_trading_day():
        return
    _log.info("[Scheduler] disposition_refresh: starting")
    loop = asyncio.get_event_loop()
    try:
        from backend.engines.engine_disposition import fetch_and_save_current
        await loop.run_in_executor(None, fetch_and_save_current)
    except Exception as exc:
        _log.error("[Scheduler] disposition_refresh failed: %s", exc)


async def job_dividend_backfill() -> None:
    """Yearly dividend backfill — runs daily at 02:00 but script self-guards."""
    _log.info("[Scheduler] dividend_backfill: starting")
    loop = asyncio.get_event_loop()
    try:
        from backend.scripts.update_dividends import run_dividend_update
        await loop.run_in_executor(None, run_dividend_update)
    except Exception as exc:
        _log.error("[Scheduler] dividend_backfill failed: %s", exc)


async def job_correlation_rebuild() -> None:
    """Rebuild correlation matrix — weekly (Saturday 03:00)."""
    _log.info("[Scheduler] correlation_rebuild: starting")
    loop = asyncio.get_event_loop()
    try:
        from backend.scripts.build_correlations import run_correlation_build
        await loop.run_in_executor(None, run_correlation_build)
    except Exception as exc:
        _log.error("[Scheduler] correlation_rebuild failed: %s", exc)


async def job_universe_refresh() -> None:
    """Refresh stock universe (stock_info) — weekly (Monday 03:00)."""
    _log.info("[Scheduler] universe_refresh: starting")
    loop = asyncio.get_event_loop()
    try:
        from backend.scripts.refresh_universe import run_universe_refresh
        await loop.run_in_executor(None, run_universe_refresh)
    except Exception as exc:
        _log.error("[Scheduler] universe_refresh failed: %s", exc)


async def job_morning_brief() -> None:
    """09:30 早盤族群動能快報 — 每個交易日一次。"""
    if not _is_trading_day():
        return
    _log.info("[Scheduler] morning_brief: starting")
    loop = asyncio.get_event_loop()
    try:
        from backend.engines.engine_market_brief import generate_morning_brief
        from backend.engines import notifier as _notifier

        brief = await loop.run_in_executor(None, generate_morning_brief)
        ok = bool(brief.get("ok"))
        await _notifier.notify_morning_brief(
            brief.get("top_themes") or [],
            brief.get("bottom_themes") or [],
            as_of=brief.get("as_of"),
            error_hint=None if ok else brief.get("reason"),
        )
    except Exception as exc:
        _log.error("[Scheduler] morning_brief failed: %s", exc)


async def job_stock_sectors_refresh() -> None:
    """TWSE / TPEx industry CSV → stock_sectors — daily 08:00 weekdays."""
    if not _is_trading_day():
        return
    _log.info("[Scheduler] stock_sectors_refresh: starting")
    loop = asyncio.get_event_loop()
    try:
        from backend.scripts.refresh_stock_sectors_twse import run_stock_sectors_refresh
        await loop.run_in_executor(None, run_stock_sectors_refresh)
    except Exception as exc:
        _log.error("[Scheduler] stock_sectors_refresh failed: %s", exc)


# ──────────────────────────────────────────────────────────────────────────────
# Lifecycle
# ──────────────────────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    """Start the APScheduler. Must be called after the asyncio event loop exists."""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = AsyncIOScheduler(timezone=_TZ)

    # Intraday: every 5 min (job self-guards market hours)
    _scheduler.add_job(
        job_intraday_update,
        IntervalTrigger(minutes=5, timezone=_TZ),
        id="intraday_update",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

    # Capital flow (5m delta vs theme.json): every 5 min, market hours
    _scheduler.add_job(
        job_capital_flow,
        IntervalTrigger(minutes=5, timezone=_TZ),
        id="capital_flow",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )

    # Post-close: cron 14:05 weekdays (job guards once-per-day)
    _scheduler.add_job(
        job_post_close_update,
        CronTrigger(hour=14, minute=5, day_of_week="mon-fri", timezone=_TZ),
        id="post_close_update",
        max_instances=1,
        coalesce=True,
    )

    # Technical scanner: every 30 min (job self-guards market hours)
    _scheduler.add_job(
        job_scanner,
        IntervalTrigger(minutes=30, timezone=_TZ),
        id="scanner",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )

    # Intraday scanner + Discord: every 5 min during 09:05–13:30 weekdays
    _scheduler.add_job(
        job_intraday_scanner_alerts,
        IntervalTrigger(minutes=5, timezone=_TZ),
        id="intraday_scanner_alerts",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )

    # Reset intraday anti-spam counters: 14:00 weekdays
    _scheduler.add_job(
        job_intraday_alert_counter_reset,
        CronTrigger(hour=14, minute=0, day_of_week="mon-fri", timezone=_TZ),
        id="intraday_alert_counter_reset",
        max_instances=1,
        coalesce=True,
    )

    # Disposition refresh: 15:05 weekdays
    _scheduler.add_job(
        job_disposition_refresh,
        CronTrigger(hour=15, minute=5, day_of_week="mon-fri", timezone=_TZ),
        id="disposition_refresh",
        max_instances=1,
        coalesce=True,
    )

    # Dividends: daily 02:00 (script is idempotent / yearly-guarded)
    _scheduler.add_job(
        job_dividend_backfill,
        CronTrigger(hour=2, minute=0, timezone=_TZ),
        id="dividend_backfill",
        max_instances=1,
        coalesce=True,
    )

    # Correlations: Saturday 03:00
    _scheduler.add_job(
        job_correlation_rebuild,
        CronTrigger(hour=3, minute=0, day_of_week="sat", timezone=_TZ),
        id="correlation_rebuild",
        max_instances=1,
        coalesce=True,
    )

    # Stock universe: Monday 03:00
    _scheduler.add_job(
        job_universe_refresh,
        CronTrigger(hour=3, minute=0, day_of_week="mon", timezone=_TZ),
        id="universe_refresh",
        max_instances=1,
        coalesce=True,
    )

    # Industry sectors (TWSE CSV): weekdays 08:00
    _scheduler.add_job(
        job_stock_sectors_refresh,
        CronTrigger(hour=8, minute=0, day_of_week="mon-fri", timezone=_TZ),
        id="stock_sectors_refresh",
        max_instances=1,
        coalesce=True,
    )

    # Morning theme brief: 09:30 weekdays
    _scheduler.add_job(
        job_morning_brief,
        CronTrigger(hour=9, minute=30, day_of_week="mon-fri", timezone=_TZ),
        id="morning_brief",
        max_instances=1,
        coalesce=True,
    )

    _scheduler.start()
    _log.info("[Scheduler] APScheduler started.")
    print(
        "[Scheduler] Started. Jobs: intraday(5min), capital_flow(5min), scanner(30min), "
        "intraday_alerts(5min@09:05-13:30 weekdays), alert_counter_reset(weekdays@14:00), "
        "post_close(14:05), disposition(15:05), "
        "dividends(daily@02:00), correlations(Sat@03:00), universe(Mon@03:00), "
        "stock_sectors(weekdays@08:00), morning_brief(weekdays@09:30)"
    )


def stop_scheduler() -> None:
    """Shut down the scheduler gracefully."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        _log.info("[Scheduler] Stopped.")
