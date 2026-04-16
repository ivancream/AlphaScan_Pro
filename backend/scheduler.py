"""
Centralized data-update scheduler for AlphaScan Pro.

Replaces the ad-hoc asyncio loops previously in intraday.py and
engine_intraday_scanner.py, and adds proper scheduling for data sources
that previously had no automatic refresh.

Schedule (Asia/Taipei):
  Every 5 min  (09:00–13:35)  intraday daily_prices snapshot
  Every 30 min (09:00–13:35)  technical scanner
  14:05  once/trading-day     post-close OHLCV settle
  15:05  once/trading-day     disposition events refresh
  02:00  daily                dividend backfill (yfinance, yearly guard)
  03:00  weekly (Saturday)    correlation matrix rebuild
  03:00  weekly (Monday)      stock universe (stock_info) refresh
  08:00  daily (weekdays)     TWSE/TPEx industry → stock_sectors
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
    loop = asyncio.get_event_loop()
    try:
        from backend.engines.engine_intraday_scanner import run_scan
        await loop.run_in_executor(None, run_scan)
    except Exception as exc:
        _log.error("[Scheduler] scanner failed: %s", exc)


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

    _scheduler.start()
    _log.info("[Scheduler] APScheduler started.")
    print(
        "[Scheduler] Started. Jobs: intraday(5min), scanner(30min), "
        "post_close(14:05), disposition(15:05), "
        "dividends(daily@02:00), correlations(Sat@03:00), universe(Mon@03:00), "
        "stock_sectors(weekdays@08:00)"
    )


def stop_scheduler() -> None:
    """Shut down the scheduler gracefully."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        _log.info("[Scheduler] Stopped.")
