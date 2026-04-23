export interface WarrantInfo {
    code: string;
    name: string;
    cp: '認購' | '認售';
    strike: number;
    exercise_ratio: number;
    bid: number;
    ask: number;
    last: number;
    /** 當日累積成交量（張），無快照時為 null */
    volume?: number | null;
    /** 漲跌幅（%），快照 change_rate */
    change_pct?: number | null;
    /** 委買量（張或口，依券商） */
    bid_size?: number | null;
    /** 委賣量（張或口，依券商） */
    ask_size?: number | null;
    underlying_symbol: string;
    underlying_price: number;
    underlying_reference: number | null;
    expiry_date: string;
    dte_days: number;
    moneyness_pct: number | null;
    spread_pct: number | null;
    bid_iv: number | null;
    ask_iv: number | null;
    bid_delta: number | null;
    ask_delta: number | null;
    bid_effective_gearing: number | null;
    ask_effective_gearing: number | null;
    spread_gearing_ratio_bid: number | null;
    spread_gearing_ratio_ask: number | null;
}

/** GET /warrants/{symbol} 回傳本體（含主檔為空時的標的報價） */
export interface WarrantsByUnderlyingResponse {
    underlying_symbol: string;
    underlying_price: number | null;
    underlying_reference: number | null;
    warrants: WarrantInfo[];
}
