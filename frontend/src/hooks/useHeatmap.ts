// hooks/useHeatmap.ts
/**
 * 資金流向 — 全市場漲跌幅／成交金額與產業標籤
 *
 * 盤中約每 5 分鐘自動重新整理；盤後每 60 分鐘（與後端日線快照節奏一致，無需秒級更新）。
 */

import { useState, useEffect, useCallback } from 'react';

import { API_V1_BASE } from '@/lib/apiBase';

export interface HeatmapStock {
    ticker: string;
    name: string;
    macro: string;
    meso: string;
    micro: string;
    close: number;
    /** 無法可靠計算時為 null（不列入板塊成交加權平均） */
    change_pct: number | null;
    turnover: number;
    volume: number;
    industry_raw?: string;
    /** 後端：intraday = 改採當日開收；unreliable = 僅標記，change_pct 為 null */
    change_pct_basis?: 'intraday' | 'unreliable' | string;
}

export interface HeatmapData {
    date: string | null;
    stocks: HeatmapStock[];
    message?: string;
    as_of_date?: string | null;
    data_freshness?: string | null;
    /** duckdb_daily_prices — 與即時 LiveQuote 解耦 */
    price_source?: string | null;
    /** scheduler_intraday_batch */
    ingest_path?: string | null;
}

function isTaiwanMarketHours(): boolean {
    const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Taipei',
        weekday: 'short',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    }).formatToParts(new Date());
    const map: Record<string, string> = {};
    for (const p of parts) {
        if (p.type !== 'literal') map[p.type] = p.value;
    }
    const wd = map.weekday ?? '';
    const hour = parseInt(map.hour ?? '0', 10);
    const minute = parseInt(map.minute ?? '0', 10);
    const weekdayOk = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].includes(wd);
    if (!weekdayOk) return false;
    const mins = hour * 60 + minute;
    return mins >= 9 * 60 && mins <= 13 * 60 + 35;
}

export function useHeatmapData() {
    const [data, setData] = useState<HeatmapData | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchData = useCallback(async () => {
        setIsLoading(true);
        setError(null);
        try {
            const res = await fetch(`${API_V1_BASE}/heatmap/data`);
            if (!res.ok) throw new Error(`API Error: ${res.status}`);
            const json = await res.json();
            setData(json);
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : String(e));
        } finally {
            setIsLoading(false);
        }
    }, []);

    useEffect(() => {
        let cancelled = false;
        let timeoutId: ReturnType<typeof setTimeout>;

        const scheduleNext = () => {
            const delay = isTaiwanMarketHours() ? 5 * 60 * 1000 : 60 * 60 * 1000;
            timeoutId = setTimeout(() => {
                if (cancelled) return;
                fetchData();
                scheduleNext();
            }, delay);
        };

        fetchData();
        scheduleNext();

        return () => {
            cancelled = true;
            clearTimeout(timeoutId);
        };
    }, [fetchData]);

    return { data, isLoading, error, refetch: fetchData };
}
