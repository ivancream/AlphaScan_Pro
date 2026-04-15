import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';

const api = axios.create({ baseURL: 'http://localhost:8000/api/v1' });

export const useCbScan = (
    ytpMin: number,
    debtMax: number,
    arbMax: number,
    securedOnly: string,
    daysMax: number,
    enabled: boolean = true
) => {
    return useQuery({
        queryKey: ['cbScan', ytpMin, debtMax, arbMax, securedOnly, daysMax],
        queryFn: async () => {
            const { data } = await api.get('/cb/scan', {
                params: {
                    ytp_min: ytpMin,
                    debt_max: debtMax,
                    arb_max: arbMax,
                    secured_only: securedOnly,
                    days_max: daysMax
                }
            });
            return data;
        },
        enabled: enabled
    });
};

export const useCbStats = () => {
    return useQuery({
        queryKey: ['cbStats'],
        queryFn: async () => {
            const { data } = await api.get('/cb/stats');
            return data;
        }
    });
};

export const useCbHistory = (cbId: string) => {
    return useQuery({
        queryKey: ['cbHistory', cbId],
        queryFn: async () => {
            const { data } = await api.get(`/cb/history/${cbId}`);
            return data;
        },
        enabled: !!cbId
    });
};

export const useCbReverse = (minArb: number, minCbPrice: number) => {
    return useQuery({
        queryKey: ['cbReverse', minArb, minCbPrice],
        queryFn: async () => {
            const { data } = await api.get('/cb/reverse', {
                params: { min_arb: minArb, min_cb_price: minCbPrice }
            });
            return data;
        }
    });
};

export const useCbUpdate = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (type: string) => {
            const { data } = await api.post(`/cb/update?type=${type}`);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['cbScan'] });
            queryClient.invalidateQueries({ queryKey: ['cbStats'] });
            queryClient.invalidateQueries({ queryKey: ['cbReverse'] });
        }
    })
}
