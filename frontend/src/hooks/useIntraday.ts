import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';

import { API_V1_BASE } from '@/lib/apiBase';

const api = axios.create({ baseURL: API_V1_BASE });

export interface IntradayStatus {
    status: 'idle' | 'running' | 'done' | 'error';
    last_updated: string | null;
    stocks_updated: number;
    total_stocks: number;
    message: string;
    elapsed_sec: number;
    is_market_hours: boolean;
}

/** 輪詢盤中更新狀態 (更新中時每 2 秒，否則每 30 秒) */
export const useIntradayStatus = () => {
    return useQuery<IntradayStatus>({
        queryKey: ['intradayStatus'],
        queryFn: async () => {
            const { data } = await api.get('/intraday/status');
            return data;
        },
        refetchInterval: (query) => {
            const data = query.state.data;
            // 更新中 -> 2s 輪詢; 否則 30s
            if (data?.status === 'running') return 2000;
            return 30000;
        },
    });
};

/** 手動觸發盤中更新 */
export const useIntradayRefresh = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async () => {
            const { data } = await api.post('/intraday/refresh');
            return data;
        },
        onSuccess: () => {
            // 觸發後立即重新查詢狀態
            queryClient.invalidateQueries({ queryKey: ['intradayStatus'] });
            // 清除策略掃描快取，下次掃描時會用最新價格
            queryClient.invalidateQueries({ queryKey: ['swingLongScan'] });
            queryClient.invalidateQueries({ queryKey: ['swingShortScan'] });
            queryClient.invalidateQueries({ queryKey: ['swingWandererScan'] });
        },
    });
};
