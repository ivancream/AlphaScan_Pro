import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';

const api = axios.create({ baseURL: 'http://localhost:8000/api/v1' });

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
