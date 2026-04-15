export type LiveProvider = 'shioaji' | 'yfinance';

export interface LiveQuote {
  stock_id: string;
  ticker: string;
  name: string;
  last_price: number;
  change_pct: number;
  volume: number;
  provider: LiveProvider;
  ts: string;
}

export interface LiveSnapshotEvent {
  type: 'snapshot';
  payload: LiveQuote[];
}

export interface LiveQuoteEvent {
  type: 'quote';
  payload: LiveQuote;
}

export interface LiveHeartbeatEvent {
  type: 'heartbeat';
  ts: string;
  provider: LiveProvider;
  symbol_count: number;
}

export interface LiveErrorEvent {
  type: 'error';
  code: string;
  message: string;
  ts: string;
}

export interface LiveEmptyEvent {
  type: 'empty';
  message: string;
  ts: string;
}

export type LiveSocketEvent =
  | LiveSnapshotEvent
  | LiveQuoteEvent
  | LiveHeartbeatEvent
  | LiveErrorEvent
  | LiveEmptyEvent;

// ──────────────────────────────────────────────────────────────────────────────
// 全方位報價 (AllAroundTicker) 型別
// ──────────────────────────────────────────────────────────────────────────────

export type AssetType = 'STOCK' | 'FUTURES' | 'WARRANT';
export type TickType  = 'BUY_UP' | 'SELL_DOWN' | 'NEUTRAL';

export interface UnifiedTick {
  ts:         string;      // UTC ISO-8601
  symbol:     string;
  name:       string;
  asset_type: AssetType;
  price:      number;
  volume:     number;      // 張 (股票/權證) / 口 (期貨)
  tick_type:  TickType;
}
