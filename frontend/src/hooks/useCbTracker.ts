/**
 * 可轉債 (CB) 資料 hooks
 *
 * 快取策略（靜態模組）：
 *   - staleTime:              12 小時 — 後端資料每日更新一次，不需提前標舊
 *   - gcTime:                 13 小時 — 超過 staleTime 後再留 1 小時 GC buffer
 *   - refetchOnWindowFocus:   false   — 切換視窗不重抓
 *   - refetchOnReconnect:     false   — 重新連線不重抓
 *   - refetchOnMount:         false   — 快取有效時不在掛載時重抓
 *
 * 手動強制更新：呼叫 useCbUpdate mutation（POST /cb/update），
 * 成功後會 invalidateQueries 觸發一次重取。
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';

const api = axios.create({ baseURL: 'http://localhost:8000/api/v1' });

const STATIC_STALE   = 12 * 60 * 60 * 1000;   // 12 小時
const STATIC_GC      = 13 * 60 * 60 * 1000;   // 13 小時
const STATIC_OPTIONS = {
    staleTime:            STATIC_STALE,
    gcTime:               STATIC_GC,
    refetchOnWindowFocus: false,
    refetchOnReconnect:   false,
    refetchOnMount:       false,
} as const;

export const useCbScan = (
    ytpMin:      number,
    debtMax:     number,
    arbMax:      number,
    securedOnly: string,
    daysMax:     number,
    enabled = true,
) =>
    useQuery({
        queryKey: ['cbScan', ytpMin, debtMax, arbMax, securedOnly, daysMax],
        queryFn: async () => {
            const { data } = await api.get('/cb/scan', {
                params: {
                    ytp_min:      ytpMin,
                    debt_max:     debtMax,
                    arb_max:      arbMax,
                    secured_only: securedOnly,
                    days_max:     daysMax,
                },
            });
            return data;
        },
        enabled,
        ...STATIC_OPTIONS,
    });

export const useCbStats = () =>
    useQuery({
        queryKey: ['cbStats'],
        queryFn: async () => {
            const { data } = await api.get('/cb/stats');
            return data;
        },
        ...STATIC_OPTIONS,
    });

export const useCbHistory = (cbId: string) =>
    useQuery({
        queryKey: ['cbHistory', cbId],
        queryFn: async () => {
            const { data } = await api.get(`/cb/history/${cbId}`);
            return data;
        },
        enabled: !!cbId,
        ...STATIC_OPTIONS,
    });

export const useCbReverse = (minArb: number, minCbPrice: number) =>
    useQuery({
        queryKey: ['cbReverse', minArb, minCbPrice],
        queryFn: async () => {
            const { data } = await api.get('/cb/reverse', {
                params: { min_arb: minArb, min_cb_price: minCbPrice },
            });
            return data;
        },
        ...STATIC_OPTIONS,
    });

export const useCbUpdate = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (type: string) => {
            const { data } = await api.post(`/cb/update?type=${type}`);
            return data;
        },
        onSuccess: () => {
            // 資料手動更新後清除快取，強制下次請求重新拉取
            queryClient.invalidateQueries({ queryKey: ['cbScan'] });
            queryClient.invalidateQueries({ queryKey: ['cbStats'] });
            queryClient.invalidateQueries({ queryKey: ['cbReverse'] });
        },
    });
};
