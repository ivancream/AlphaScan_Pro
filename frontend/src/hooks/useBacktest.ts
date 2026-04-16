import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

import { API_V1_BASE } from '@/lib/apiBase';

const api = axios.create({ baseURL: API_V1_BASE });

export const useSimpleBacktest = (stockId: string, strategy: string) => {
    return useQuery({
        queryKey: ['backtest', stockId, strategy],
        queryFn: async () => {
            const { data } = await api.get(`/backtest/history?stock_id=${stockId}&strategy=${strategy}`);
            return data;
        },
        enabled: !!stockId && !!strategy,
    });
};
