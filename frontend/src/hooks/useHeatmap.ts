// hooks/useHeatmap.ts
/**
 * 資金流向熱力圖 - React Hooks
 *
 * - useHeatmapData(): 取得熱力圖資料
 */

import { useState, useEffect, useCallback } from 'react';

const API_BASE = 'http://localhost:8000';

// ==========================================
// 熱力圖數據
// ==========================================
export interface HeatmapStock {
    ticker: string;
    name: string;
    macro: string;
    meso: string;
    micro: string;
    close: number;
    change_pct: number;
    turnover: number;
    volume: number;
}

export interface HeatmapData {
    date: string | null;
    stocks: HeatmapStock[];
    message?: string;
}

export function useHeatmapData() {
    const [data, setData] = useState<HeatmapData | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchData = useCallback(async () => {
        setIsLoading(true);
        setError(null);
        try {
            const res = await fetch(`${API_BASE}/api/v1/heatmap/data`);
            if (!res.ok) throw new Error(`API Error: ${res.status}`);
            const json = await res.json();
            setData(json);
        } catch (e: any) {
            setError(e.message);
        } finally {
            setIsLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchData();
    }, [fetchData]);

    return { data, isLoading, error, refetch: fetchData };
}
