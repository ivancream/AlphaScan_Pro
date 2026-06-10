export type MonitorConnectionState = 'connecting' | 'open' | 'closed' | 'error';

export type SignalSide = 'buy' | 'sell' | 'neutral';

export interface MonitorThresholds {
  stockLotThreshold: number;
  warrantLotThreshold: number;
  moveWindowSec: number;
  movePctThreshold: number;
  continuousWindowSec: number;
  continuousMinCount: number;
  maxWarrantsPerStock: number;
  includeWarrants: boolean;
  includeIndexFutures?: boolean;
  futuresLotThreshold?: number;
  futuresConsecutiveMinCount?: number;
  futuresConsecutiveMinVolume?: number;
  futuresReversalMinLots?: number;
  futuresVwapDeviationPct?: number;
  futuresWallLots?: number;
  scalpEnabled?: boolean;
  scalpConsecutiveWindowSec?: number;
  scalpConsecutiveMinCount?: number;
  scalpConsecutiveMinVolume?: number;
  scalpReversalMinLots?: number;
  scalpVwapDeviationPct?: number;
  scalpWallLots?: number;
  scalpWallAvgVolumeMultiple?: number;
  scalpNoNewExtremeSec?: number;
  scalpSpoofMinLots?: number;
  scalpSpoofDropPct?: number;
}

export interface MonitorSignalEvent {
  id: string;
  time: string;
  symbol: string;
  name: string;
  instrument_type: 'stock' | 'warrant' | 'futures';
  event_type:
    | 'stock_large_buy'
    | 'stock_large_sell'
    | 'continuous_buy'
    | 'continuous_sell'
    | 'rapid_rise'
    | 'rapid_drop'
    | 'warrant_spot_link'
    | 'block_trade'
    | 'mega_block_trade'
    | 'order_book_spoof_pull'
    | 'scalp_short_exhaustion'
    | 'scalp_long_exhaustion'
    | 'warrant_hedge_exhaustion'
    | 'futures_large_buy'
    | 'futures_large_sell';
  event_label: string;
  side: SignalSide;
  severity: 'normal' | 'high';
  price: number;
  volume: number;
  tag: string;
  tag_items?: Array<{
    label: string;
    branch?: string;
    side?: SignalSide;
    net_lots?: number | null;
  }>;
  message: string;
  related_symbol: string;
  related_name: string;
  warrant_symbol?: string | null;
  warrant_name?: string | null;
  count?: number | null;
  cum_volume?: number | null;
  pct_move?: number | null;
  window_sec?: number | null;
  scalp_context?: Record<string, unknown> | null;
}

export interface MonitorReadyPayload {
  watch_symbols: string[];
  subscribed_symbols: string[];
  futures_aliases?: Record<string, string>;
  thresholds: Record<string, number | boolean>;
  health: {
    shioaji_connected: boolean;
    shioaji_error?: string | null;
    warrant_mapping_count: number;
    overnight_branch_symbol_count: number;
    all_around?: Record<string, unknown>;
  };
}

export type MonitorSocketMessage =
  | { type: 'ready'; payload: MonitorReadyPayload }
  | { type: 'signal'; payload: MonitorSignalEvent };

export interface OrderBookLevel {
  price: number;
  volume: number;
}

export interface RelatedWarrantActivity {
  symbol: string;
  name: string;
  cp: 'call' | 'put';
  last_price: number;
  volume: number;
  last_time: string;
  tick_dir: 'OUTER' | 'INNER' | 'NONE';
}

export interface MonitorTapeTick {
  ts: string;
  symbol: string;
  name: string;
  asset_type: string;
  price: number;
  volume: number;
  tick_dir: 'OUTER' | 'INNER' | 'NONE';
  chg_type: string;
  pct_chg: number;
}

export interface MonitorMicroSnapshot {
  symbol: string;
  name: string;
  underlying_symbol: string;
  underlying_name: string;
  instrument_type?: 'stock' | 'warrant' | 'futures';
  futures_aliases?: Record<string, string>;
  order_book: {
    bid: OrderBookLevel[];
    ask: OrderBookLevel[];
    source?: 'live_bidask' | 'live_fop_bidask' | 'snapshot';
    ts?: string;
  };
  tape: MonitorTapeTick[];
  related_warrants: RelatedWarrantActivity[];
}
