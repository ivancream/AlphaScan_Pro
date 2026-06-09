# Intraday Monitor Work Log

Last updated: 2026-06-08

## User Requirements

1. Data priority must be Shioaji first.
   - Real-time ticks, tick direction, bid/ask snapshots, and future BidAsk five-level data should come from the Sinopac Shioaji API whenever available.
   - Database data must not replace live Shioaji data during normal market monitoring.

2. Database is the fallback and analysis layer.
   - Use the database for warrant-to-underlying mapping, overnight branch/chips labels, cached display data, and after-hours calculations.
   - When Shioaji is unstable or disconnected, the UI should still show mapping, tags, cached recent ticks, and post-market analysis where possible.

3. Desktop is the primary target.
   - The app should favor Tauri desktop stability over a public web deployment.
   - WebSocket connections, local cache, local database, and sidecar backend behavior should be designed for one local operator running a trading terminal.

4. Maintenance needs a written workflow.
   - Every major monitor change should update this log or a follow-up dated section.
   - Keep clear notes on data source priority, fallback behavior, files changed, and verification status.

## Implementation Added In This Pass

### Backend

Added `backend/engines/engine_intraday_monitor.py`.

Responsibilities:
 - Consumes normalized ticks from `all_around_engine`, which is backed by Shioaji when credentials and connection are available.
 - Detects single large stock orders.
 - Detects continuous large buy/sell orders with a sliding time window.
 - Detects rapid rise/drop moves over a configurable time window.
 - Detects warrant large-order to spot linkage by querying `warrant_master`.
 - Labels events with overnight branch/chips warnings from `key_branch_trades` first, then `branch_trading` as fallback.
 - Provides a micro snapshot API helper with Shioaji snapshot order book first, and recent tick cache as display fallback.

Added `backend/api/v1/intraday_monitor.py`.

Responsibilities:
 - `GET /api/v1/intraday-monitor/health`
 - `GET /api/v1/intraday-monitor/micro/{symbol}`
 - `WS /ws/intraday-monitor`
 - Accepts per-connection thresholds and watchlist symbols.
 - Expands watched stocks to related warrant symbols from `warrant_master` before subscribing.

Updated `backend/main.py`.

Responsibilities:
 - Registers the intraday monitor API router.

### Frontend

Added `frontend/src/types/intradayMonitor.ts`.

Responsibilities:
 - Shared TypeScript contracts for monitor events, readiness payloads, micro snapshots, order book levels, and related warrant activity.

Added `frontend/src/hooks/useIntradayMonitor.ts`.

Responsibilities:
 - Opens the monitor WebSocket.
 - Sends watchlist and threshold parameters.
 - Keeps newest signals at the top.
 - Caps in-memory UI signal history at 500 rows.
 - Reconnects automatically.
 - Polls the selected symbol micro snapshot.

Added `frontend/src/app/intraday-monitor/page.tsx`.

Responsibilities:
 - Desktop-first dark terminal layout.
 - Top global controls and threshold inputs.
 - CSV/text watchlist import.
 - Real-time signal waterfall.
 - Optional sound alert.
 - Detail panel for order book snapshot, related warrants, and recent tape.

Updated:
 - `frontend/src/App.tsx` to add route `/intraday-monitor`.
 - `frontend/src/components/layout/MainLayout.tsx` to add sidebar entry `權現監控`.

## Data Source Rules

### Real-Time Trading Session

Primary:
 - Shioaji WebSocket Tick through `sinopac_session` and `all_around_engine`.
 - Shioaji snapshot API for current quote/order-book style data when available.

Secondary:
 - In-memory recent tick cache from `all_around_engine`.
 - Local DB only for reference data and labels.

Do not use:
 - Daily DB prices as a substitute for live tick direction.
 - yfinance as a preferred source for this monitor. If it is used elsewhere in the app, it should remain a broad fallback, not the main source for this feature.

### Mapping And Labels

Primary:
 - `warrant_master` for warrant-to-underlying mapping.
 - `key_branch_trades` for curated overnight branch warning labels.

Fallback:
 - `branch_trading` latest date ranked by net shares.

### After-Hours Analysis

Use DB tables for:
 - post-market warrant mapping review,
 - branch/chips review,
 - event replay,
 - historical threshold tuning,
 - daily summary statistics.

## Current Limitations

1. Five-level BidAsk streaming is not wired yet.
   - Current detail panel attempts Shioaji snapshots for bid/ask fields.
   - Next step should add master BidAsk callbacks to `sinopac_session`, then propagate a normalized five-level order book cache.

2. Signal detector is per WebSocket connection.
   - This keeps custom thresholds simple and isolated.
   - If multiple windows are used heavily, move detector state into a shared engine and make thresholds a subscription filter.

3. Sound alerts are frontend-generated tones.
   - No external audio files are required.
   - The user must enable sound because browsers block unsolicited audio.

4. Local `.venv` is currently broken in this workspace.
   - `npm.cmd run build` passed for frontend verification.
   - Backend syntax was checked with Codex bundled Python because `.venv\Scripts\python.exe` points to a missing interpreter.

## Verification Performed

2026-06-08:
 - Frontend baseline build passed before changes with `npm.cmd run build`.
 - Backend new monitor files and `backend/main.py` passed Python syntax check using Codex bundled Python.
 - Frontend build passed after changes with `npm.cmd run build`.
 - Browser/dev-server smoke check was interrupted before completion; do not treat it as verified.

## Recommended Next Work

1. Add Shioaji BidAsk v1 callback support.
   - Extend `sinopac_session` with bidask handler registration.
   - Subscribe watched stock and warrant contracts to BidAsk.
   - Store normalized five-level bid/ask data in an in-memory cache.
   - Replace snapshot-derived order book fields in the detail panel.

2. Add local persistence for signal replay.
   - New SQLite table for intraday monitor events.
   - Store event JSON, threshold profile, and source health.
   - Enable after-hours review and threshold tuning.

3. Add Shioaji connection degradation mode.
   - UI should explicitly show `LIVE`, `CACHE`, or `DB` source state.
   - When live feed is disconnected, disable live-only signals and keep DB/cached panels visible.

4. Add desktop QA checklist.
   - Launch Tauri app.
   - Verify sidecar backend health.
   - Verify Shioaji login.
   - Verify monitor WebSocket.
   - Verify watchlist subscription count.
   - Verify sound toggle.
   - Verify CPU/memory during active market ticks.

## Follow-Up Implementation On 2026-06-08

### Shioaji BidAsk Priority

Updated `backend/engines/sinopac_session.py`.

Responsibilities:
 - Added shared stock BidAsk handler registration.
 - Registers one Shioaji `on_bidask_stk_v1` master callback when available.
 - Dispatches BidAsk events to multiple engines without callback overwrite.

Updated `backend/engines/engine_intraday_monitor.py`.

Responsibilities:
 - Added `LiveOrderBookCache`.
 - Subscribes watched stock and warrant contracts to Shioaji `QuoteType.BidAsk`.
 - Caches normalized five-level bid/ask data in memory.
 - Detail API now reads live BidAsk cache first and falls back to Shioaji snapshot only when live BidAsk is unavailable.
 - Monitor health reports BidAsk handler/cache status.

Updated `backend/api/v1/intraday_monitor.py`.

Responsibilities:
 - Monitor WebSocket now subscribes related symbols to both Tick and BidAsk.

Updated frontend detail panel.

Responsibilities:
 - Shows whether the displayed order book source is `LIVE BIDASK` or `SNAPSHOT`.

### Local Signal Replay

Updated `backend/db/schema.py`.

Responsibilities:
 - Added SQLite table `intraday_monitor_events`.

Updated `backend/db/user_db.py`.

Responsibilities:
 - Added `write_monitor_event`.
 - Added `get_recent_monitor_events`.

Updated `backend/api/v1/intraday_monitor.py`.

Responsibilities:
 - Persists emitted monitor signals to `user.db`.
 - Added `GET /api/v1/intraday-monitor/events`.

Updated `frontend/src/hooks/useIntradayMonitor.ts`.

Responsibilities:
 - Loads recent DB replay events when the monitor page opens.
 - Live Shioaji WebSocket remains the primary source; DB replay is best-effort display fallback.

### Verification Notes

Completed:
 - Backend syntax check passed after BidAsk/replay changes.
 - Frontend build passed after BidAsk/replay changes.

Still pending:
 - Verify Shioaji BidAsk during market hours with real credentials.
 - Confirm actual Shioaji BidAsk payload field names for stocks and warrants.
