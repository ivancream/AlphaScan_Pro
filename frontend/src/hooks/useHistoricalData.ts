import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { MarketData } from '../types';

import { API_V1_BASE } from '@/lib/apiBase';

const fetchMarketData = async (symbol: string, limit: number): Promise<MarketData> => {
    const { data } = await axios.get(`${API_V1_BASE}/market-data/${symbol}?limit=${limit}`);
    return data;
};

export const useHistoricalData = (symbol: string, limit: number = 5000) => {
    return useQuery({
        queryKey: ['marketData', symbol, limit],
        queryFn: () => fetchMarketData(symbol, limit),
        staleTime: 1000 * 60 * 5, // 5分鐘內不發送重複 Request
        refetchOnWindowFocus: false, // 禁止切換視窗時重新撈取
    });
};
