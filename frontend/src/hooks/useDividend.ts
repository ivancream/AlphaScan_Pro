/**
 * 除權息 (Dividend) 資料 hooks
 *
 * 快取策略（靜態模組）：
 *   - staleTime:              12 小時 — 歷史除息資料每日更新一次
 *   - gcTime:                 13 小時 — staleTime 後再留 1 小時 GC buffer
 *   - refetchOnWindowFocus:   false   — 切換視窗不重抓
 *   - refetchOnReconnect:     false   — 重新連線不重抓
 *   - refetchOnMount:         false   — 快取有效時不在掛載時重抓
 *
 * 搜尋 (useDividendSearch) 因為需要即時回應使用者輸入，
 * 保留較短的 staleTime（5 分鐘）並允許掛載時重取。
 */

import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

import { API_V1_BASE } from '@/lib/apiBase';

const api = axios.create({ baseURL: API_V1_BASE });

const STATIC_STALE = 12 * 60 * 60 * 1000;   // 12 小時
const STATIC_GC    = 13 * 60 * 60 * 1000;   // 13 小時

export const useDividendScan = (stockCode: string, enabled: boolean) =>
    useQuery({
        queryKey: ['dividendScan', stockCode],
        queryFn: async () => {
            const { data } = await api.get(`/dividend/${stockCode}/scan`);
            return data;
        },
        enabled: enabled && !!stockCode,
        staleTime:            STATIC_STALE,
        gcTime:               STATIC_GC,
        refetchOnWindowFocus: false,
        refetchOnReconnect:   false,
        refetchOnMount:       false,
    });

export const useDividendSearch = (query: string) =>
    useQuery({
        queryKey: ['dividendSearch', query],
        queryFn: async () => {
            const { data } = await api.get(`/dividend/search?q=${query}`);
            return data;
        },
        enabled: !!query && query.length > 0,
        // 搜尋結果允許 5 分鐘快取（即時感），不阻擋 window focus refetch
        staleTime:            5 * 60 * 1000,
        gcTime:               10 * 60 * 1000,
        refetchOnWindowFocus: false,
    });
