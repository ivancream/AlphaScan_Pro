/**
 * ML Quant — 每日 WFO 規則推論（後端 /api/v1/ml-quant/daily-picks）
 */

import { useCallback, useEffect, useState } from 'react';

import { API_V1_BASE } from '@/lib/apiBase';

/** 後端 `run_daily_inference` 回傳之 `regime` 物件 */
export interface MlQuantRegime {
    date: string;
    regime_state: number;
    regime_label: string;
}

/** 單一觸發規則之標的列 */
export interface MlQuantPick {
    symbol: string;
    close: number | null;
    rule_human_readable: string;
    fold_id: number;
    is_win_rate: number | null;
    oos_win_rate: number | null;
}

/** GET /api/v1/ml-quant/daily-picks 完整回應 */
export interface MlQuantDailyPicksResponse {
    as_of_date: string | null;
    regime: MlQuantRegime;
    n_universe: number;
    picks: MlQuantPick[];
    rules_path: string;
}

export type MlQuantUniverseParam = 'all' | 'watchlist' | 'symbols';

export interface UseMlQuantOptions {
    /** 對應後端 `universe` query，預設 all */
    universe?: MlQuantUniverseParam;
    /** 對應後端 `lookback`，預設 100 */
    lookback?: number;
    /** `universe=symbols` 時必填，逗號分隔代碼 */
    symbols?: string;
    /** 覆寫規則檔路徑（選填） */
    rulesPath?: string;
    /** 是否自動載入（預設 true） */
    enabled?: boolean;
}

function buildDailyPicksUrl(options: UseMlQuantOptions): string {
    const universe = options.universe ?? 'all';
    const lookback = options.lookback ?? 100;
    const params = new URLSearchParams();
    params.set('universe', universe);
    params.set('lookback', String(lookback));
    if (universe === 'symbols' && (options.symbols ?? '').trim()) {
        params.set('symbols', options.symbols!.trim());
    }
    if ((options.rulesPath ?? '').trim()) {
        params.set('rules_path', options.rulesPath!.trim());
    }
    return `${API_V1_BASE}/ml-quant/daily-picks?${params.toString()}`;
}

export function useMlQuant(options: UseMlQuantOptions = {}) {
    const {
        universe = 'all',
        lookback = 100,
        symbols = '',
        rulesPath,
        enabled = true,
    } = options;

    const [data, setData] = useState<MlQuantDailyPicksResponse | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchData = useCallback(async () => {
        setIsLoading(true);
        setError(null);
        try {
            const url = buildDailyPicksUrl({ universe, lookback, symbols, rulesPath });
            const res = await fetch(url);
            if (!res.ok) {
                let detail = `HTTP ${res.status}`;
                try {
                    const body = (await res.json()) as { detail?: string };
                    if (typeof body?.detail === 'string') detail = body.detail;
                } catch {
                    /* ignore */
                }
                if (res.status === 502 || res.status === 503) {
                    throw new Error(
                        `無法連到後端（${res.status}）。請確認 FastAPI 已執行（例如 uvicorn backend.main:app --port 8000）。`,
                    );
                }
                throw new Error(detail);
            }
            const json = (await res.json()) as MlQuantDailyPicksResponse;
            setData(json);
        } catch (e: unknown) {
            setData(null);
            setError(e instanceof Error ? e.message : String(e));
        } finally {
            setIsLoading(false);
        }
    }, [universe, lookback, symbols, rulesPath]);

    useEffect(() => {
        if (!enabled) return;
        void fetchData();
    }, [enabled, fetchData]);

    return { data, isLoading, error, refetch: fetchData };
}
