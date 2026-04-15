import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

const api = axios.create({ baseURL: 'http://localhost:8000/api/v1' });

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
