import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

const api = axios.create({ baseURL: 'http://localhost:8000/api/v1' });

export const useDividendScan = (stockCode: string, enabled: boolean) => {
    return useQuery({
        queryKey: ['dividendScan', stockCode],
        queryFn: async () => {
            const { data } = await api.get(`/dividend/${stockCode}/scan`);
            return data;
        },
        enabled: enabled && !!stockCode,
        staleTime: 1000 * 60 * 60,
    });
};

export const useDividendSearch = (query: string) => {
    return useQuery({
        queryKey: ['dividendSearch', query],
        queryFn: async () => {
            const { data } = await api.get(`/dividend/search?q=${query}`);
            return data;
        },
        enabled: !!query && query.length > 0,
        staleTime: 1000 * 60 * 60,
    });
};
