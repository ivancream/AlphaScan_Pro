export interface CandleData {
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
}

export interface MarketData {
    symbol: string;
    data: CandleData[];
    session?: string;
    snapshot?: {
        last_price?: number;
        change_pct?: number;
        volume?: number;
        vwap?: number;
        provider?: string;
        ts?: string;
        bb_upper?: number | null;
        bb_lower?: number | null;
    } | null;
}
