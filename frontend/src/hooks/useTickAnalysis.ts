import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

import { API_V1_BASE } from '@/lib/apiBase';
import type { LargePlayerResponse } from '@/types/tickAnalysis';

const api = axios.create({ baseURL: API_V1_BASE });

export const useTickAnalysis = (symbol: string, enabled = true, pr = 97) =>
    useQuery({
        queryKey: ['tick-analysis', 'large-players', symbol, pr],
        queryFn: async () => {
            const { data } = await api.get<LargePlayerResponse>(
                `/ticks/large_players/${encodeURIComponent(symbol)}`,
                { params: { pr } },
            );
            return data;
        },
        enabled: enabled && !!symbol,
        staleTime: 10 * 1000,
        refetchInterval: 15 * 1000,
        refetchOnWindowFocus: true,
    });
