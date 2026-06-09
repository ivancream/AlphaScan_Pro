# Intraday Scalp Trigger Module

This module implements the tick-level and five-level order-book triggers for
very short-term intraday entry/exit signals.

## Backend Entry Points

- Core engine: `backend/engines/engine_scalp_trigger.py`
- Live integration: `backend/engines/engine_intraday_monitor.py`
- WebSocket route: `/ws/intraday-monitor`

The core engine consumes normalized Shioaji-style ticks:

```json
{
  "symbol": "2330",
  "price": 900,
  "volume": 35,
  "tick_dir": "OUTER"
}
```

It can also consume five-level books:

```json
{
  "bid": [{ "price": 899, "volume": 180 }],
  "ask": [{ "price": 900, "volume": 650 }]
}
```

## Trigger Families

### Tick Run Exhaustion

Event types:

- `scalp_short_exhaustion`
- `scalp_long_exhaustion`

Default short setup:

- Price is above VWAP by at least `2%`.
- Last contiguous OUTER run inside `5s` has at least `30` ticks.
- The run volume is at least `300` lots.
- First reversal INNER tick has at least `20` lots.
- At least one confirmation exists: no new high for `2s`, nearby ask wall,
  or nearby key level.

Long setup is symmetric: INNER run below VWAP, followed by OUTER reversal.

The event includes `scalp_context.stop_price` and `scalp_context.take_profit`.
For a short exhaustion, stop is the exhaustion high plus one tick and take
profit is VWAP.

### Block Trades

Event types:

- `block_trade`
- `mega_block_trade`

Defaults:

- Block trade: single tick volume >= `stock_lot_threshold`.
- Mega block trade: single tick volume >= `max(stock_lot_threshold * 2, 100)`.

### Order-Book Wall and Spoof Pull

Event type:

- `order_book_spoof_pull`

Defaults:

- Large wall absolute floor: `500` lots.
- Dynamic wall floor: average tick volume over the last `300s` multiplied by
  `2`.
- Spoof pull: a previously large level loses at least `65%` of its displayed
  lots while price is within one tick of that level.

### Warrant Hedging Exhaustion

Event type:

- `warrant_hedge_exhaustion`

This tracks related warrant ticks. When a warrant has a short burst of
same-side prints and then flips direction, the event maps the likely dealer
hedging direction back to the underlying stock.

## WebSocket Query Parameters

All parameters are optional and have backend defaults:

- `scalp_enabled=true`
- `scalp_consecutive_window_sec=5`
- `scalp_consecutive_min_count=30`
- `scalp_consecutive_min_volume=300`
- `scalp_reversal_min_lots=20`
- `scalp_vwap_deviation_pct=2.0`
- `scalp_wall_lots=500`
- `scalp_wall_avg_volume_multiple=2.0`
- `scalp_no_new_extreme_sec=2.0`
- `scalp_spoof_min_lots=200`
- `scalp_spoof_drop_pct=0.65`

Example:

```text
/ws/intraday-monitor?symbols=2330,2454&scalp_consecutive_min_count=30&scalp_consecutive_min_volume=300&scalp_wall_lots=500
```

## Notes

- VWAP is calculated from the engine's in-memory ticks since startup or since
  the detector was created.
- Previous-day high/low support exists in the core engine through
  `set_reference_levels()`, but the live monitor integration currently uses
  open/day high/day low unless prior levels are loaded by a caller.
- Signals are decision-support events. They are not order execution logic.
