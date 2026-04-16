import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

import { API_V1_BASE } from '@/lib/apiBase';

const api = axios.create({ baseURL: API_V1_BASE });

export const useFloorBounceScan = (showMode: string, requireVol: boolean, filterInactive: boolean, enabled: boolean) => {
    return useQuery({
        queryKey: ['floorBounceScan', showMode, requireVol, filterInactive],
        queryFn: async () => {
            const { data } = await api.get(`/floor-bounce/scan`, {
                params: { show_mode: showMode, require_vol: requireVol, filter_inactive: filterInactive }
            });
            return data.results;
        },
        enabled: enabled,
        staleTime: 1000 * 60 * 15,
    });
};

export const useFloorBounceChart = (stockCode: string, enabled: boolean) => {
    return useQuery({
        queryKey: ['floorBounceChart', stockCode],
        queryFn: async () => {
            const { data } = await api.get(`/floor-bounce/chart/${stockCode}`);
            return data;
        },
        enabled: enabled && !!stockCode,
        staleTime: 1000 * 60 * 15,
    });
};
