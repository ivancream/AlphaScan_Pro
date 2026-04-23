import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

import { API_V1_BASE } from '@/lib/apiBase';
import type { WarrantsByUnderlyingResponse } from '@/types/warrant';

const api = axios.create({ baseURL: API_V1_BASE });

export const useWarrants = (symbol: string, enabled = true) =>
    useQuery({
        queryKey: ['warrants', symbol],
        queryFn: async () => {
            const { data } = await api.get<WarrantsByUnderlyingResponse>(
                `/warrants/${encodeURIComponent(symbol)}`,
            );
            return data;
        },
        enabled: enabled && !!symbol,
        staleTime: 15 * 1000,
        refetchInterval: 8 * 1000,
        refetchOnWindowFocus: true,
    });
