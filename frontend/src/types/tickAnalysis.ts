export interface LargePlayerTrade {
    ts?: string;
    time?: string;
    price?: number;
    amount?: number;
    volume?: number;
    lot_size?: number;
    lots?: number;
    qty?: number;
    direction?: string;
    side?: string;
    tick_dir?: string;
}

export interface LargePlayerSummary {
    threshold?: number;
    large_order_threshold?: number;
    buy_lots?: number;
    sell_lots?: number;
    net_lots?: number;
}

export interface LargePlayerResponse {
    symbol?: string;
    /** 第幾百分位數，例如 97 表示 PR97 */
    pr?: number;
    /** 0.0–1.0，與 pr 對應 */
    percentile?: number;
    /** 僅 PR 分位計算出的金額門檻（未與動態下限合併前） */
    threshold_quantile?: number;
    /** 依樣本中位數推導的動態下限（元） */
    min_amount_floor?: number;
    threshold?: number;
    large_order_threshold?: number;
    buy_lots?: number;
    sell_lots?: number;
    net_lots?: number;
    summary?: LargePlayerSummary;
    rows?: LargePlayerTrade[];
    details?: LargePlayerTrade[];
    trades?: LargePlayerTrade[];
}
