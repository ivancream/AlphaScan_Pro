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

export interface TopCorrelationResult {
    rank: number;
    peer_id: string;
    peer_name: string;
    correlation: number;
    current_z_score?: number;
    is_cointegrated?: boolean;
    hedge_ratio?: number;
    half_life?: number;
    composite_score?: number;
    adf_p_value?: number;
    eg_p_value?: number;
}

export interface CorrelationSpreadPoint {
    date: string;
    close_a: number;
    close_b: number;
    ratio: number;
    z_score: number;
    above_mean: boolean;
    above_recent: boolean;
}

export interface CorrelationSpreadResponse {
    stock_a: string;
    stock_a_name: string;
    stock_b: string;
    stock_b_name: string;
    is_cointegrated?: boolean;
    hedge_ratio?: number;
    half_life?: number;
    composite_score?: number;
    adf_p_value?: number;
    eg_p_value?: number;
    days: number;
    recent_days: number;
    ratio_mean_full: number;
    ratio_std_full: number;
    ratio_mean_recent: number;
    series: CorrelationSpreadPoint[];
}
