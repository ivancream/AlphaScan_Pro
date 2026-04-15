/**
 * 波段選股海選 hooks
 *
 * 回應速度策略（雙路徑）：
 *   1. 快速路徑 GET /api/v1/scanner/results/{strategy}
 *      → 讀取盤中排程快取（< 100ms），有結果時立刻顯示
 *
 *   2. 慢速路徑 GET /api/v1/swing/{strategy}
 *      → 觸發全市場 BollingerStrategy 掃描（1~3 分鐘，首次/快取過期時）
 *      → 後端已加三層快取：StaticCache(12h) → _SCAN_CACHE → live scan
 *
 * 實作：
 *   - 優先用快速路徑 (useSwingFast)；若 count = 0 才發送慢速路徑
 *   - 慢速路徑的 staleTime 15 分鐘，重整不重掃
 */

import { useQuery } from '@tanstack/react-query';
import axios, { isAxiosError } from 'axios';

const SWING_SCAN_TIMEOUT_MS = 90_000;
const SWING_SCAN_MAX_RETRIES = 2;

const api = axios.create({
    baseURL: 'http://localhost:8000/api/v1',
    timeout: SWING_SCAN_TIMEOUT_MS,
});

const shouldRetrySwingScan = (failureCount: number, error: unknown): boolean => {
    if (failureCount >= SWING_SCAN_MAX_RETRIES) return false;
    if (!isAxiosError(error)) return false;
    const status = error.response?.status;
    if (typeof status === 'number' && status >= 400 && status < 500) return false;
    return true;
};

// ── 快速路徑：讀 intraday scanner 記憶體快取（幾乎即時回應） ──────────────────

export const useSwingFast = (strategy: 'long' | 'short' | 'wanderer', enabled: boolean) =>
    useQuery({
        queryKey: ['swingFast', strategy],
        queryFn: async () => {
            const { data } = await api.get(`/scanner/results/${strategy}`, {
                params: { limit: 500, fallback_db: true },
                timeout: 8_000,
            });
            return data as { strategy: string; count: number; source: string; last_run: string | null; items: Record<string, unknown>[] };
        },
        enabled,
        staleTime:            15 * 60 * 1000,   // 15 分鐘
        gcTime:               30 * 60 * 1000,
        refetchOnWindowFocus: false,
        retry: 1,
    });

// ── 慢速路徑：觸發完整 BollingerStrategy 全市場掃描 ──────────────────────────

export const useSwingLong = (
    enabled: boolean,
    params?: { req_ma: boolean; req_vol: boolean; req_slope: boolean },
) =>
    useQuery({
        queryKey: ['swingLongScan', params],
        queryFn: async () => {
            const { data } = await api.get('/swing/long', { params });
            return data.results as Record<string, unknown>[];
        },
        enabled,
        staleTime:            15 * 60 * 1000,
        refetchOnWindowFocus: false,
        retry: shouldRetrySwingScan,
        retryDelay: (attemptIndex) => Math.min(1500 * 2 ** attemptIndex, 8000),
    });

export const useSwingShort = (
    enabled: boolean,
    params?: { req_ma: boolean; req_slope: boolean; req_chips: boolean; req_near_band: boolean },
) =>
    useQuery({
        queryKey: ['swingShortScan', params],
        queryFn: async () => {
            const { data } = await api.get('/swing/short', { params });
            return data.results as Record<string, unknown>[];
        },
        enabled,
        staleTime:            15 * 60 * 1000,
        refetchOnWindowFocus: false,
        retry: shouldRetrySwingScan,
        retryDelay: (attemptIndex) => Math.min(1500 * 2 ** attemptIndex, 8000),
    });

export const useSwingWanderer = (
    enabled: boolean,
    params?: { req_slope: boolean; req_bb_level: boolean },
) =>
    useQuery({
        queryKey: ['swingWandererScan', params],
        queryFn: async () => {
            const { data } = await api.get('/swing/wanderer', { params });
            return data.results as Record<string, unknown>[];
        },
        enabled,
        staleTime:            15 * 60 * 1000,
        refetchOnWindowFocus: false,
        retry: shouldRetrySwingScan,
        retryDelay: (attemptIndex) => Math.min(1500 * 2 ** attemptIndex, 8000),
    });
