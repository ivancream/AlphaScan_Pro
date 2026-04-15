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

export type AssetType   = '現貨' | '期貨' | '認購' | '認售';
export type TickDir     = 'OUTER' | 'INNER' | 'NONE';
export type ChgType     = 'LIMIT_UP' | 'UP' | 'FLAT' | 'DOWN' | 'LIMIT_DOWN';

export interface UnifiedTick {
  ts:         string;      // HH:MM:SS
  symbol:     string;
  name:       string;
  asset_type: AssetType;
  price:      number;
  volume:     number;      // 張 (股票/權證) / 口 (期貨)
  tick_dir:   TickDir;     // 外盤/內盤
  chg_type:   ChgType;    // 漲跌註記（決定價格顏色）
  pct_chg:    number;      // 漲跌幅 %
}
