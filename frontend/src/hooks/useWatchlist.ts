import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';

import { API_V1_BASE } from '@/lib/apiBase';

const api = axios.create({ baseURL: API_V1_BASE });

export const useWatchlist = () => {
    return useQuery({
        queryKey: ['watchlist'],
        queryFn: async () => {
            const { data } = await api.get('/watchlist');
            return data;
        },
    });
};

export const useAddToWatchlist = () => {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: async (stockId: string) => {
            await api.post('/watchlist', { stock_id: stockId });
        },
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['watchlist'] });
        }
    });
};

export const useRemoveFromWatchlist = () => {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: async (stockId: string) => {
            await api.delete(`/watchlist/${stockId}`);
        },
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['watchlist'] });
        }
    });
};
